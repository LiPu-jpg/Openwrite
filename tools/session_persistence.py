"""Session 持久化管理器。

将会话数据持久化到文件系统，避免服务器重启后丢失。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SessionPersistence:
    """会话持久化管理器。

    会话数据存储在 data/sessions/ 目录下，每个会话一个 JSON 文件。
    """

    def __init__(self, project_root: Optional[Path] = None):
        """初始化持久化管理器。

        Args:
            project_root: 项目根目录
        """
        self.project_root = project_root or Path.cwd()
        self.sessions_dir = self.project_root / "data" / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _get_session_file(self, session_id: str) -> Path:
        """获取会话文件路径。

        Args:
            session_id: 会话ID

        Returns:
            会话文件路径
        """
        return self.sessions_dir / f"{session_id}.json"

    def save_session(self, session_data: Dict[str, Any]) -> bool:
        """保存会话到文件。

        Args:
            session_data: 会话数据（包含 session_id）

        Returns:
            是否保存成功
        """
        session_id = session_data.get("session_id")
        if not session_id:
            logger.warning("会话数据缺少 session_id")
            return False

        session_file = self._get_session_file(session_id)
        try:
            # 更新时间戳
            session_data["updated_at"] = datetime.now().isoformat()

            with open(session_file, "w", encoding="utf-8") as f:
                json.dump(session_data, f, ensure_ascii=False, indent=2)

            logger.debug("会话已保存: %s", session_id)
            return True

        except Exception as e:
            logger.error("保存会话失败: %s - %s", session_id, e)
            return False

    def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """从文件加载会话。

        Args:
            session_id: 会话ID

        Returns:
            会话数据，不存在返回 None
        """
        session_file = self._get_session_file(session_id)
        if not session_file.exists():
            return None

        try:
            with open(session_file, "r", encoding="utf-8") as f:
                return json.load(f)

        except Exception as e:
            logger.error("加载会话失败: %s - %s", session_id, e)
            return None

    def delete_session(self, session_id: str) -> bool:
        """删除会话文件。

        Args:
            session_id: 会话ID

        Returns:
            是否删除成功
        """
        session_file = self._get_session_file(session_id)
        if not session_file.exists():
            return False

        try:
            session_file.unlink()
            logger.debug("会话已删除: %s", session_id)
            return True

        except Exception as e:
            logger.error("删除会话失败: %s - %s", session_id, e)
            return False

    def list_sessions(self) -> List[Dict[str, Any]]:
        """列出所有会话。

        Returns:
            会话列表
        """
        sessions = []
        try:
            for session_file in self.sessions_dir.glob("*.json"):
                try:
                    with open(session_file, "r", encoding="utf-8") as f:
                        session_data = json.load(f)
                        sessions.append(session_data)
                except Exception as e:
                    logger.warning("读取会话文件失败: %s - %s", session_file, e)

        except Exception as e:
            logger.error("列出会话失败: %s", e)

        return sessions

    def cleanup_old_sessions(self, max_age_days: int = 30) -> int:
        """清理过期会话。

        Args:
            max_age_days: 最大保留天数

        Returns:
            删除的会话数量
        """
        deleted = 0
        cutoff = datetime.now().timestamp() - (max_age_days * 24 * 60 * 60)

        for session_file in self.sessions_dir.glob("*.json"):
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    session_data = json.load(f)

                updated_at = session_data.get("updated_at", "")
                if updated_at:
                    try:
                        ts = datetime.fromisoformat(updated_at).timestamp()
                        if ts < cutoff:
                            session_file.unlink()
                            deleted += 1
                            logger.debug("清理过期会话: %s", session_file.stem)
                    except ValueError:
                        pass

            except Exception as e:
                logger.warning("检查会话文件失败: %s - %s", session_file, e)

        if deleted > 0:
            logger.info("清理了 %d 个过期会话", deleted)

        return deleted
