"""Compatibility wrapper for markdown annotation parsing."""

from typing import Any, Dict

try:
    from tools.parsers.markdown_parser import MarkdownAnnotationParser
except ImportError:  # pragma: no cover - supports legacy path injection
    from parsers.markdown_parser import MarkdownAnnotationParser


def parse_annotations(content: str) -> Dict[str, Any]:
    """Parse all supported annotations from markdown content."""
    parser = MarkdownAnnotationParser()
    return parser.parse_all(content)
