from __future__ import annotations

import itertools
import uuid
from typing import Any

import httpx

from .config import AdapterError


class McpClient:
    def __init__(self, endpoint: str, token: str, http_client: httpx.Client | None = None) -> None:
        self.endpoint = endpoint
        self.token = token
        self.http_client = http_client or httpx.Client(timeout=30)
        self.session_id = str(uuid.uuid4())
        self._ids = itertools.count(1)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": next(self._ids),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        try:
            response = self.http_client.post(
                self.endpoint,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "MCP-Session-Id": self.session_id,
                },
            )
        except httpx.RequestError as exc:
            raise AdapterError(
                f"MCP call {name} failed due to network error: {exc}",
                "mcp_submission_failed",
                "Không thể gửi kết quả AI về Smart Story do lỗi kết nối.",
            )
        try:
            data = response.json()
        except ValueError:
            if response.status_code >= 400:
                raise AdapterError(
                    f"MCP call {name} failed with HTTP {response.status_code}: {response.text[:200]}",
                    "mcp_submission_failed",
                    "Không thể gửi kết quả AI về Smart Story.",
                )
            raise AdapterError(
                f"MCP call {name} failed: Invalid JSON response (HTTP {response.status_code}, body={response.text[:200]!r})",
                "mcp_submission_failed",
                "Không thể đọc kết quả từ Smart Story.",
            )

        if not isinstance(data, dict):
            if response.status_code >= 400:
                raise AdapterError(
                    f"MCP call {name} failed with HTTP {response.status_code}",
                    "mcp_submission_failed",
                    "Không thể gửi kết quả AI về Smart Story.",
                )
            raise AdapterError(
                f"MCP call {name} failed: Invalid JSON response format",
                "mcp_submission_failed",
                "Không thể đọc kết quả từ Smart Story.",
            )

        if data.get("error"):
            raise AdapterError(
                f"MCP call {name} failed: {data['error']}",
                "mcp_submission_failed",
                "Không thể gửi kết quả AI về Smart Story.",
            )

        if response.status_code >= 400:
            raise AdapterError(
                f"MCP call {name} failed with HTTP {response.status_code}",
                "mcp_submission_failed",
                "Không thể gửi kết quả AI về Smart Story.",
            )
        result = data.get("result", {})
        if isinstance(result, dict) and isinstance(result.get("structuredContent"), dict):
            return result["structuredContent"]
        if isinstance(result, dict):
            return result
        return {}

    def report_progress(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.call_tool("report_run_progress", payload)

    def import_private_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.call_tool("import_ai_private_draft", payload)
