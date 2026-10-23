"""文件操作工具"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, List, Optional
import json
import os
import tempfile


def atomic_write(path: Path, content: str) -> None:
    """Replace a UTF-8 document in its own directory, without partial reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent,
                                         prefix=f".{path.name}.", delete=False) as handle:
            temporary = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


class FileOps:
    """文件操作工具（沙箱化）"""

    def __init__(self, project_root: Path, novel_id: str):
        self.project_root = project_root.resolve()
        self.novel_id = novel_id
        self.data_dir = project_root / "data" / "novels" / novel_id

    def _resolve_path(self, path: str) -> Path:
        """解析并验证路径（防止路径穿越）"""
        full_path = (self.data_dir / path).resolve()
        if not str(full_path).startswith(str(self.data_dir)):
            raise ValueError(f"Path traversal detected: {path}")
        return full_path

    def read_file(self, path: str) -> Dict[str, Any]:
        """读取文件"""
        try:
            full_path = self._resolve_path(path)
            if not full_path.exists():
                return {"success": False, "error": f"File not found: {path}"}

            content = full_path.read_text(encoding="utf-8")
            return {"success": True, "result": content}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def write_file(self, path: str, content: str) -> Dict[str, Any]:
        """写入文件"""
        try:
            full_path = self._resolve_path(path)
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")
            return {"success": True, "result": str(full_path)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_files(self, path: str = "") -> Dict[str, Any]:
        """列出目录文件"""
        try:
            full_path = self._resolve_path(path) if path else self.data_dir
            if not full_path.is_dir():
                return {"success": False, "error": "Not a directory"}

            files = [f.name for f in full_path.iterdir()]
            return {"success": True, "result": files}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def file_exists(self, path: str) -> Dict[str, Any]:
        """检查文件是否存在"""
        try:
            full_path = self._resolve_path(path)
            return {"success": True, "result": full_path.exists()}
        except Exception as e:
            return {"success": False, "error": str(e)}
