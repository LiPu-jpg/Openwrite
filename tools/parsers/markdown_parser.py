"""
Markdown 标记解析器
支持伏笔、人物标记、场景标记
"""

import re
from typing import List, Dict, Optional, Any
from dataclasses import dataclass


@dataclass
class Annotation:
    """标记数据类"""

    type: str
    attributes: Dict[str, Any]
    content: str = ""


class MarkdownAnnotationParser:
    """Markdown 标记解析器"""

    # 标记模式
    FORESHADOWING_PATTERN = re.compile(
        r"\<\!\-\-(伏笔|fs)\s+(.*?)\-\-\>(.*?)\<\!\-\-\s*\/\s*(伏笔|fs)\-\-\>",
        re.DOTALL,
    )

    RECOVER_PATTERN = re.compile(
        r"\<\!\-\-\s*(回收|recover|rc)\s+(.*?)\-\-\>(.*?)\<\!\-\-\s*\/\s*(回收|recover|rc)\-\-\>",
        re.DOTALL,
    )

    CHARACTER_PATTERN = re.compile(
        r"\<\!\-\-\s*(人物|char|character)\s+(.*?)\-\-\>(.*?)\<\!\-\-\s*\/\s*(人物|char|character)\-\-\>",
        re.DOTALL,
    )

    SCENE_PATTERN = re.compile(
        r"\<\!\-\-\s*(场景|scene)\s+(.*?)\-\-\>(.*?)\<\!\-\-\s*\/\s*(场景|scene)\-\-\>",
        re.DOTALL,
    )

    def __init__(self):
        """初始化解析器"""
        self.foreshadowings: List[Dict[str, Any]] = []
        self.recovers: List[Dict[str, Any]] = []
        self.characters: List[Dict[str, Any]] = []
        self.scenes: List[Dict[str, Any]] = []

    def parse_attributes(self, attr_str: str) -> Dict[str, Any]:
        """解析标记属性字符串"""
        attributes = {}
        if not attr_str.strip():
            return attributes

        # 键值对解析: key=value 或 key="value" 或 key='value'
        for match in re.finditer(r'(\w+)\s*=\s*(?:["\']?)([^"\'\s]+)(?:["\']?)', attr_str):
            key = match.group(1).strip()
            value = match.group(2).strip('"\'')
            attributes[key] = value

        return attributes

    def parse_foreshadowing(self, content: str) -> List[Dict[str, Any]]:
        """解析伏笔标记"""
        results = []

        for match in self.FORESHADOWING_PATTERN.finditer(content):
            attr_str = match.group(2)
            annotation_content = match.group(3)

            attributes = self.parse_attributes(attr_str)

            results.append(
                {
                    "type": "foreshadowing",
                    "content": annotation_content.strip(),
                    "attributes": attributes,
                    "full_match": match.group(0),
                }
            )

        return results

    def parse_all(self, content: str) -> Dict[str, List[Dict[str, Any]]]:
        """解析所有标记类型"""
        return {
            "foreshadowings": self.parse_foreshadowing(content),
            "recovers": [],
            "characters": [],
            "scenes": [],
        }



def parse_markdown_file(file_path: str) -> Dict[str, Any]:
    """解析 Markdown 文件"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        parser = MarkdownAnnotationParser()
        annotations = parser.parse_all(content)
        
        return {
            'file_path': file_path,
            'annotations': annotations,
            'raw_content': content,
        }
    except Exception as e:
        return {
            'error': str(e),
            'file_path': file_path,
        }