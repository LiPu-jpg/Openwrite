"""Tool Executor — 工具执行器

提供安全的工具调用机制，让 Agent 可以：
- 读取/写入文件
- 查询数据（大纲、角色、世界观等）
- 搜索内容

所有工具调用都在安全沙箱内执行。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class ToolExecutor:
    """工具执行器。
    
    提供统一的工具调用接口，支持：
    - 文件操作（读/写/列表）
    - 数据查询（大纲/角色/世界观/伏笔）
    - 内容搜索
    
    所有路径操作都被限制在项目目录内。
    
    Usage:
        executor = ToolExecutor(project_root=Path.cwd(), novel_id="my_novel")
        
        # 读取文件
        result = executor.execute("read_file", {"path": "outline/outline.md"})
        
        # 查询大纲
        result = executor.execute("query_outline", {"chapter_id": "ch_001"})
    """
    
    def __init__(
        self,
        project_root: Path,
        novel_id: Optional[str] = None,
    ):
        """初始化执行器。
        
        Args:
            project_root: 项目根目录
            novel_id: 当前小说 ID（可选）
        """
        self.project_root = project_root.resolve()
        self.novel_id = novel_id
        self._tools: Dict[str, Callable] = {}
        
        # 注册内置工具
        self._register_builtin_tools()
    
    def _register_builtin_tools(self) -> None:
        """注册内置工具。"""
        # 文件操作
        self.register("read_file", self._read_file)
        self.register("write_file", self._write_file)
        self.register("append_file", self._append_file)
        self.register("list_files", self._list_files)
        self.register("file_exists", self._file_exists)
        self.register("get_file_info", self._get_file_info)
        
        # 内容搜索
        self.register("search_content", self._search_content)
        self.register("grep", self._grep)
        
        # 数据查询（需要 novel_id）
        self.register("query_outline", self._query_outline)
        self.register("query_characters", self._query_characters)
        self.register("query_world", self._query_world)
        self.register("query_foreshadowing", self._query_foreshadowing)
        self.register("query_manuscript", self._query_manuscript)
        self.register("query_style", self._query_style)
    
    def register(self, name: str, handler: Callable) -> None:
        """注册工具。
        
        Args:
            name: 工具名称
            handler: 处理函数
        """
        self._tools[name] = handler
        logger.debug("Registered tool: %s", name)
    
    def execute(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """执行工具。
        
        Args:
            tool_name: 工具名称
            parameters: 参数字典
            
        Returns:
            执行结果字典，包含：
            - success: 是否成功
            - result: 结果数据（成功时）
            - error: 错误信息（失败时）
        """
        if tool_name not in self._tools:
            return {
                "success": False,
                "error": f"Unknown tool: {tool_name}",
                "available_tools": list(self._tools.keys()),
            }
        
        try:
            result = self._tools[tool_name](**parameters)
            return {"success": True, "result": result}
        except PermissionError as e:
            return {"success": False, "error": f"Permission denied: {e}"}
        except FileNotFoundError as e:
            return {"success": False, "error": f"File not found: {e}"}
        except Exception as e:
            logger.exception("Tool execution failed: %s", tool_name)
            return {"success": False, "error": str(e)}
    
    def list_tools(self) -> List[Dict[str, str]]:
        """列出所有可用工具。
        
        Returns:
            工具信息列表
        """
        return [
            {"name": name, "description": handler.__doc__ or ""}
            for name, handler in self._tools.items()
        ]
    
    # ============================================================
    # 路径安全
    # ============================================================
    
    def _resolve_path(self, path: str) -> Path:
        """解析并验证路径安全性。
        
        Args:
            path: 相对或绝对路径
            
        Returns:
            解析后的绝对路径
            
        Raises:
            PermissionError: 路径超出项目目录
        """
        # 处理相对路径
        if path.startswith("~/"):
            full_path = Path(path).expanduser()
        elif path.startswith("/"):
            full_path = Path(path)
        else:
            full_path = self.project_root / path
        
        full_path = full_path.resolve()
        
        # 安全检查：必须在项目目录内
        try:
            full_path.relative_to(self.project_root)
        except ValueError:
            raise PermissionError(f"Path outside project: {path}")
        
        return full_path
    
    def _is_safe_path(self, path: Path) -> bool:
        """检查路径是否安全。"""
        try:
            path.resolve().relative_to(self.project_root)
            return True
        except ValueError:
            return False
    
    def _novel_data_path(self, *parts: str) -> Path:
        """获取小说数据目录路径。
        
        Args:
            *parts: 路径组件
            
        Returns:
            完整路径
            
        Raises:
            ValueError: novel_id 未设置
        """
        if not self.novel_id:
            raise ValueError("novel_id not set")
        
        path = self.project_root / "data" / "novels" / self.novel_id
        for part in parts:
            path = path / part
        return path
    # ============================================================
    # 文件操作工具
    # ============================================================
    
    def _read_file(self, path: str, encoding: str = "utf-8") -> str:
        """读取文件内容。
        
        Args:
            path: 文件路径（相对于项目根目录）
            encoding: 文件编码
            
        Returns:
            文件内容
        """
        full_path = self._resolve_path(path)
        return full_path.read_text(encoding=encoding)
    
    def _write_file(
        self,
        path: str,
        content: str,
        encoding: str = "utf-8",
        create_dirs: bool = True,
    ) -> Dict[str, Any]:
        """写入文件。
        
        Args:
            path: 文件路径（相对于项目根目录）
            content: 文件内容
            encoding: 文件编码
            create_dirs: 是否自动创建目录
            
        Returns:
            操作结果信息
        """
        full_path = self._resolve_path(path)
        
        # 只允许写入 data/novels/ 目录
        try:
            full_path.relative_to(self.project_root / "data" / "novels")
        except ValueError:
            raise PermissionError("Can only write to data/novels/ directory")
        
        if create_dirs:
            full_path.parent.mkdir(parents=True, exist_ok=True)
        
        full_path.write_text(content, encoding=encoding)
        
        return {
            "path": str(full_path.relative_to(self.project_root)),
            "bytes_written": len(content.encode(encoding)),
        }
    
    def _append_file(
        self,
        path: str,
        content: str,
        encoding: str = "utf-8",
    ) -> Dict[str, Any]:
        """追加内容到文件。
        
        Args:
            path: 文件路径
            content: 要追加的内容
            encoding: 文件编码
            
        Returns:
            操作结果信息
        """
        full_path = self._resolve_path(path)
        
        # 只允许写入 data/novels/ 目录
        try:
            full_path.relative_to(self.project_root / "data" / "novels")
        except ValueError:
            raise PermissionError("Can only write to data/novels/ directory")
        
        with full_path.open("a", encoding=encoding) as f:
            f.write(content)
        
        return {
            "path": str(full_path.relative_to(self.project_root)),
            "bytes_appended": len(content.encode(encoding)),
        }
    
    def _list_files(
        self,
        directory: str,
        pattern: str = "*",
        recursive: bool = False,
    ) -> List[str]:
        """列出目录中的文件。
        
        Args:
            directory: 目录路径
            pattern: 文件匹配模式
            recursive: 是否递归搜索
            
        Returns:
            文件路径列表（相对于项目根目录）
        """
        full_path = self._resolve_path(directory)
        
        if not full_path.exists():
            return []
        
        if recursive:
            files = full_path.rglob(pattern)
        else:
            files = full_path.glob(pattern)
        
        return [
            str(f.relative_to(self.project_root))
            for f in files
            if f.is_file()
        ]
    
    def _file_exists(self, path: str) -> bool:
        """检查文件是否存在。
        
        Args:
            path: 文件路径
            
        Returns:
            是否存在
        """
        full_path = self._resolve_path(path)
        return full_path.exists()
    
    def _get_file_info(self, path: str) -> Dict[str, Any]:
        """获取文件信息。
        
        Args:
            path: 文件路径
            
        Returns:
            文件信息字典
        """
        full_path = self._resolve_path(path)
        
        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        stat = full_path.stat()
        
        return {
            "path": str(full_path.relative_to(self.project_root)),
            "size": stat.st_size,
            "is_file": full_path.is_file(),
            "is_dir": full_path.is_dir(),
            "modified": stat.st_mtime,
        }
    
    # ============================================================
    # 内容搜索工具
    # ============================================================
    
    def _search_content(
        self,
        query: str,
        scope: str = "all",
        max_results: int = 20,
    ) -> List[Dict[str, Any]]:
        """搜索内容。
        
        Args:
            query: 搜索查询
            scope: 搜索范围（all/outline/characters/world/manuscript）
            max_results: 最大结果数
            
        Returns:
            搜索结果列表
        """
        if not self.novel_id:
            return []
        
        results = []
        query_lower = query.lower()
        
        # 确定搜索目录
        if scope == "all":
            search_dirs = ["outline", "characters", "world", "manuscript"]
        else:
            search_dirs = [scope]
        
        for dir_name in search_dirs:
            dir_path = self._novel_data_path(dir_name)
            if not dir_path.exists():
                continue
            
            for file_path in dir_path.rglob("*"):
                if not file_path.is_file():
                    continue
                
                try:
                    content = file_path.read_text(encoding="utf-8")
                except Exception:
                    continue
                
                if query_lower in content.lower():
                    # 找到匹配，提取上下文
                    matches = self._extract_contexts(content, query, max_context=2)
                    
                    results.append({
                        "file": str(file_path.relative_to(self.project_root)),
                        "matches": matches[:max_context],
                    })
                    
                    if len(results) >= max_results:
                        return results
        
        return results
    
    def _extract_contexts(
        self,
        content: str,
        query: str,
        max_context: int = 3,
        context_chars: int = 100,
    ) -> List[str]:
        """提取匹配上下文。
        
        Args:
            content: 文件内容
            query: 搜索查询
            max_context: 最大上下文数
            context_chars: 上下文字符数
            
        Returns:
            上下文片段列表
        """
        contexts = []
        query_lower = query.lower()
        content_lower = content.lower()
        
        start = 0
        while len(contexts) < max_context:
            pos = content_lower.find(query_lower, start)
            if pos == -1:
                break
            
            # 提取上下文
            context_start = max(0, pos - context_chars)
            context_end = min(len(content), pos + len(query) + context_chars)
            
            context = content[context_start:context_end]
            if context_start > 0:
                context = "..." + context
            if context_end < len(content):
                context = context + "..."
            
            contexts.append(context)
            start = pos + len(query)
        
        return contexts
    
    def _grep(
        self,
        pattern: str,
        path: str = ".",
        file_pattern: str = "*.md",
        max_results: int = 50,
    ) -> List[Dict[str, Any]]:
        """正则表达式搜索。
        
        Args:
            pattern: 正则表达式模式
            path: 搜索路径
            file_pattern: 文件匹配模式
            max_results: 最大结果数
            
        Returns:
            匹配结果列表
        """
        full_path = self._resolve_path(path)
        
        if not full_path.exists():
            return []
        
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return [{"error": f"Invalid regex: {e}"}]
        
        results = []
        
        for file_path in full_path.rglob(file_pattern):
            if not file_path.is_file():
                continue
            
            try:
                content = file_path.read_text(encoding="utf-8")
            except Exception:
                continue
            
            for i, line in enumerate(content.split("\n"), 1):
                if regex.search(line):
                    results.append({
                        "file": str(file_path.relative_to(self.project_root)),
                        "line": i,
                        "content": line.strip()[:200],
                    })
                    
                    if len(results) >= max_results:
                        return results
        
        return results
    
    # ============================================================
    # 数据查询工具
    # ============================================================
    
    def _query_outline(
        self,
        chapter_id: Optional[str] = None,
        arc_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """查询大纲数据。
        
        Args:
            chapter_id: 章节ID（可选）
            arc_id: 篇章ID（可选）
            
        Returns:
            大纲数据
        """
        if not self.novel_id:
            raise ValueError("novel_id not set")
        
        outline_path = self._novel_data_path("outline", "hierarchy.yaml")
        
        if not outline_path.exists():
            return {"error": "Outline not found", "path": str(outline_path)}
        
        import yaml
        
        with outline_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        
        # 如果指定了章节，只返回该章节
        if chapter_id:
            chapters = data.get("chapters", {})
            if chapter_id in chapters:
                return {"chapter": chapters[chapter_id]}
            return {"error": f"Chapter not found: {chapter_id}"}
        
        # 如果指定了篇章，只返回该篇章
        if arc_id:
            arcs = data.get("arcs", {})
            if arc_id in arcs:
                return {"arc": arcs[arc_id]}
            return {"error": f"Arc not found: {arc_id}"}
        
        return data
    
    def _query_characters(
        self,
        character_id: Optional[str] = None,
        tier: Optional[str] = None,
    ) -> Dict[str, Any]:
        """查询角色数据。
        
        Args:
            character_id: 角色ID（可选）
            tier: 角色层级（主角/重要配角/配角/龙套）
            
        Returns:
            角色数据
        """
        if not self.novel_id:
            raise ValueError("novel_id not set")
        
        chars_dir = self._novel_data_path("characters", "text_profiles")
        
        if not chars_dir.exists():
            return {"error": "Characters directory not found"}
        
        import yaml
        
        characters = {}
        
        for char_file in chars_dir.glob("*.yaml"):
            try:
                with char_file.open("r", encoding="utf-8") as f:
                    char_data = yaml.safe_load(f) or {}
                
                char_id = char_data.get("id", char_file.stem)
                char_tier = char_data.get("char_type", "")
                
                # 按层级过滤
                if tier and tier != char_tier:
                    continue
                
                characters[char_id] = char_data
                
            except Exception as e:
                logger.warning("Failed to load character: %s", e)
        
        # 如果指定了角色ID
        if character_id:
            if character_id in characters:
                return {"character": characters[character_id]}
            return {"error": f"Character not found: {character_id}"}
        
        return {"characters": characters}
    
    def _query_world(
        self,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """查询世界观数据。
        
        Args:
            entity_id: 实体ID（可选）
            entity_type: 实体类型（可选）
            
        Returns:
            世界观数据
        """
        if not self.novel_id:
            raise ValueError("novel_id not set")
        
        world_path = self._novel_data_path("world", "graph.yaml")
        
        if not world_path.exists():
            return {"error": "World graph not found"}
        
        import yaml
        
        with world_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        
        entities = data.get("entities", {})
        
        # 如果指定了实体ID
        if entity_id:
            if entity_id in entities:
                return {"entity": entities[entity_id]}
            return {"error": f"Entity not found: {entity_id}"}
        
        # 按类型过滤
        if entity_type:
            filtered = {
                k: v for k, v in entities.items()
                if v.get("type") == entity_type
            }
            return {"entities": filtered}
        
        return {"entities": entities}
    
    def _query_foreshadowing(
        self,
        node_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """查询伏笔数据。
        
        Args:
            node_id: 伏笔节点ID（可选）
            status: 状态（pending/planted/recovered）
            
        Returns:
            伏笔数据
        """
        if not self.novel_id:
            raise ValueError("novel_id not set")
        
        fs_path = self._novel_data_path("foreshadowing", "dag.yaml")
        
        if not fs_path.exists():
            return {"error": "Foreshadowing DAG not found"}
        
        import yaml
        
        with fs_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        
        nodes = data.get("nodes", {})
        
        # 如果指定了节点ID
        if node_id:
            if node_id in nodes:
                return {"node": nodes[node_id]}
            return {"error": f"Node not found: {node_id}"}
        
        # 按状态过滤
        if status:
            filtered = {
                k: v for k, v in nodes.items()
                if v.get("status") == status
            }
            return {"nodes": filtered}
        
        return {"nodes": nodes}
    
    def _query_manuscript(
        self,
        chapter_id: Optional[str] = None,
        include_drafts: bool = False,
    ) -> Dict[str, Any]:
        """查询草稿数据。
        
        Args:
            chapter_id: 章节ID（可选）
            include_drafts: 是否包含草稿
            
        Returns:
            草稿数据
        """
        if not self.novel_id:
            raise ValueError("novel_id not set")
        
        manuscript_dir = self._novel_data_path("manuscript")
        
        if not manuscript_dir.exists():
            return {"error": "Manuscript directory not found"}
        
        manuscripts = {}
        
        # 搜索所有章节文件
        patterns = ["**/*.md"]
        if not include_drafts:
            patterns = ["**/ch_*.md", "**/chapter_*.md"]
        
        for pattern in patterns:
            for file_path in manuscript_dir.glob(pattern):
                if "_draft" in file_path.name and not include_drafts:
                    continue
                
                ch_id = file_path.stem
                try:
                    content = file_path.read_text(encoding="utf-8")
                    manuscripts[ch_id] = {
                        "path": str(file_path.relative_to(self.project_root)),
                        "length": len(content),
                        "preview": content[:500] if len(content) > 500 else content,
                    }
                except Exception as e:
                    logger.warning("Failed to read manuscript: %s", e)
        
        # 如果指定了章节ID
        if chapter_id:
            # 尝试多种命名格式
            for key in [chapter_id, f"ch_{chapter_id}", f"chapter_{chapter_id}"]:
                if key in manuscripts:
                    return {"manuscript": manuscripts[key]}
            return {"error": f"Manuscript not found: {chapter_id}"}
        
        return {"manuscripts": manuscripts}
    
    def _query_style(self) -> Dict[str, Any]:
        """查询风格数据。
        
        Returns:
            风格数据
        """
        if not self.novel_id:
            raise ValueError("novel_id not set")
        
        style_dir = self._novel_data_path("style")
        
        if not style_dir.exists():
            return {"error": "Style directory not found"}
        
        style_data = {}
        
        for style_file in style_dir.glob("*.yaml"):
            import yaml
            
            try:
                with style_file.open("r", encoding="utf-8") as f:
                    style_data[style_file.stem] = yaml.safe_load(f) or {}
            except Exception as e:
                logger.warning("Failed to load style file: %s", e)
        
        # 也检查 composed 风格
        composed_path = self.project_root / "composed" / f"{self.novel_id}_composed.md"
        if composed_path.exists():
            try:
                style_data["composed"] = composed_path.read_text(encoding="utf-8")
            except Exception:
                pass
        
        return style_data
