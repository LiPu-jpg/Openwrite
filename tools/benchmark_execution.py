"""Execute benchmark stage dependencies and retain verifiable artifact evidence."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any


class BenchmarkExecution:
    def __init__(
        self, path: Path, pipeline: dict[str, Any], *, previous: dict[str, Any] | None = None
    ):
        self.path = path
        self.record = (
            deepcopy(previous)
            if previous
            else {
                "id": pipeline["id"],
                "nodes": [
                    {**node, "status": "pending", "evidence": []} for node in pipeline["nodes"]
                ],
            }
        )
        if self.record["id"] != pipeline["id"]:
            raise ValueError("benchmark pipeline identity changed")
        if [(node["id"], node["depends_on"]) for node in self.record["nodes"]] != [
            (node["id"], node["depends_on"]) for node in pipeline["nodes"]
        ]:
            raise ValueError("benchmark pipeline dependencies changed")
        self.nodes = {node["id"]: node for node in self.record["nodes"]}

    def start(self, stage: str) -> None:
        node = self.nodes[stage]
        if node["status"] != "pending":
            raise ValueError(f"benchmark stage {stage} already started")
        if any(
            self.nodes[dependency]["status"] != "completed" for dependency in node["depends_on"]
        ):
            raise ValueError(f"benchmark stage {stage} dependencies are not completed")
        node["status"] = "running"
        self.save()

    def complete(self, stage: str, artifact: Path, *, status: str = "completed") -> None:
        if self.nodes[stage]["status"] != "running":
            raise ValueError(f"benchmark stage {stage} has not started")
        relative = artifact.resolve().relative_to(self.path.parent.resolve()).as_posix()
        data = artifact.read_bytes()
        self.nodes[stage].update(
            status=status,
            evidence=[
                {
                    "path": relative,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data),
                }
            ],
        )
        self.save()

    def fail(self, stage: str, code: str, artifact: Path | None = None) -> None:
        self.nodes[stage].update(status="failed", error_code=code)
        if artifact is not None and artifact.is_file():
            data = artifact.read_bytes()
            self.nodes[stage]["evidence"] = [
                {
                    "path": artifact.resolve().relative_to(self.path.parent.resolve()).as_posix(),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data),
                }
            ]
        for node in self.record["nodes"]:
            if node["status"] == "pending":
                node.update(status="skipped", reason=f"dependency_failed:{stage}")
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def evidence(self) -> dict[str, Any]:
        return {
            "pipeline_execution": deepcopy(self.record),
            "stage_statuses": {key: node["status"] for key, node in self.nodes.items()},
            "execution_path": str(self.path),
        }
