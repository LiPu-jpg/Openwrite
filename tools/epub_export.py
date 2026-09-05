"""Deterministic EPUB 3 export and structural validation."""

from __future__ import annotations

import hashlib
import mimetypes
import tempfile
import zipfile
from datetime import datetime, timezone
from html import escape
from pathlib import Path, PurePosixPath
from uuid import NAMESPACE_URL, uuid5
from xml.etree import ElementTree

from markdown_it import MarkdownIt

from tools.character_state_index import strip_character_state_annotations
from tools.novel_workspace import list_chapters
from tools.scene_integration import scene_export_chapters


class EpubExportError(ValueError):
    pass


CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/package.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

BOOK_CSS = """body { font-family: serif; line-height: 1.8; margin: 5%; }
h1 { font-size: 1.5em; text-align: center; margin: 2em 0 1.5em; }
p { text-indent: 2em; margin: 0.4em 0; }
nav ol { list-style: none; padding: 0; }
nav li { margin: 0.6em 0; }
"""


def export_epub(
    project_root: Path,
    novel_id: str,
    output: Path,
    *,
    title: str = "",
    author: str = "",
    language: str = "zh-CN",
    cover: Path | None = None,
) -> Path:
    project_root = Path(project_root).resolve()
    chapters = list_chapters(project_root, novel_id)
    if not chapters:
        raise EpubExportError("还没有可导出的章节")
    scene_chapters = scene_export_chapters(project_root, novel_id)
    export_chapters = scene_chapters if scene_chapters is not None else chapters
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    book_title = str(title or novel_id).strip()
    book_author = str(author or "OpenWrite Author").strip()
    book_language = str(language or "zh-CN").strip()
    digest = hashlib.sha256()
    chapter_entries: list[tuple[str, str, str]] = []
    renderer = MarkdownIt("commonmark", {"html": False})
    for index, chapter in enumerate(export_chapters, start=1):
        source_text = (
            chapter.markdown
            if scene_chapters is not None
            else chapter.path.read_text(encoding="utf-8")
        )
        markdown = strip_character_state_annotations(
            source_text
        )
        digest.update(chapter.chapter_id.encode("utf-8"))
        digest.update(markdown.encode("utf-8"))
        chapter_title = chapter.title or chapter.chapter_id
        body = renderer.render(markdown)
        filename = f"chapter-{index:04d}.xhtml"
        xhtml = _xhtml(chapter_title, body, language=book_language)
        ElementTree.fromstring(xhtml)
        chapter_entries.append((filename, chapter_title, xhtml))
    identifier = f"urn:uuid:{uuid5(NAMESPACE_URL, novel_id + ':' + digest.hexdigest())}"
    modified = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    cover_entry: tuple[str, bytes, str] | None = None
    if cover is not None:
        cover_path = Path(cover).expanduser().resolve()
        try:
            cover_path.relative_to(project_root)
        except ValueError as exc:
            raise EpubExportError("封面必须位于项目目录内") from exc
        if not cover_path.is_file():
            raise EpubExportError("封面文件不存在")
        media_type = mimetypes.guess_type(cover_path.name)[0] or ""
        if media_type not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
            raise EpubExportError("封面仅支持 JPEG、PNG、WebP 或 GIF")
        cover_entry = (f"cover{cover_path.suffix.lower()}", cover_path.read_bytes(), media_type)

    nav = _nav(book_title, chapter_entries, language=book_language)
    package = _package(
        book_title,
        book_author,
        book_language,
        identifier,
        modified,
        chapter_entries,
        cover_entry,
    )
    with tempfile.NamedTemporaryFile(
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            archive.writestr(
                zipfile.ZipInfo("mimetype"),
                "application/epub+zip",
                compress_type=zipfile.ZIP_STORED,
            )
            archive.writestr(
                "META-INF/container.xml", CONTAINER_XML, zipfile.ZIP_DEFLATED
            )
            archive.writestr("OEBPS/package.opf", package, zipfile.ZIP_DEFLATED)
            archive.writestr("OEBPS/nav.xhtml", nav, zipfile.ZIP_DEFLATED)
            archive.writestr(
                "OEBPS/styles/book.css", BOOK_CSS, zipfile.ZIP_DEFLATED
            )
            for filename, _, xhtml in chapter_entries:
                archive.writestr(
                    f"OEBPS/text/{filename}", xhtml, zipfile.ZIP_DEFLATED
                )
            if cover_entry:
                filename, content, _ = cover_entry
                archive.writestr(
                    f"OEBPS/images/{filename}", content, zipfile.ZIP_DEFLATED
                )
        validate_epub(temporary)
        temporary.replace(output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return output


def validate_epub(path: Path) -> dict[str, object]:
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise EpubExportError("EPUB 包含重复路径")
            required = {
                "mimetype",
                "META-INF/container.xml",
                "OEBPS/package.opf",
                "OEBPS/nav.xhtml",
            }
            missing = sorted(required - set(names))
            if missing:
                raise EpubExportError(f"EPUB 缺少文件: {', '.join(missing)}")
            if (
                names[0] != "mimetype"
                or archive.getinfo("mimetype").compress_type != zipfile.ZIP_STORED
            ):
                raise EpubExportError("EPUB mimetype 必须是首个且不压缩")
            if archive.read("mimetype") != b"application/epub+zip":
                raise EpubExportError("EPUB mimetype 无效")
            for name in names:
                if not _safe_epub_path(name):
                    raise EpubExportError("EPUB 包含越界路径")
                if name.endswith((".xml", ".opf", ".xhtml")):
                    ElementTree.fromstring(archive.read(name))

            container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
            container_ns = {
                "container": "urn:oasis:names:tc:opendocument:xmlns:container"
            }
            rootfile = container.find("container:rootfiles/container:rootfile", container_ns)
            if rootfile is None or rootfile.get("full-path") != "OEBPS/package.opf":
                raise EpubExportError("EPUB container 未指向 package.opf")

            package = ElementTree.fromstring(archive.read("OEBPS/package.opf"))
            opf_ns = {"opf": "http://www.idpf.org/2007/opf"}
            if package.get("version") != "3.0":
                raise EpubExportError("EPUB package 不是 3.0")
            items = package.findall("opf:manifest/opf:item", opf_ns)
            manifest: dict[str, tuple[str, str, str]] = {}
            for item in items:
                item_id = str(item.get("id") or "")
                href = str(item.get("href") or "")
                media_type = str(item.get("media-type") or "")
                properties = str(item.get("properties") or "")
                if not item_id or item_id in manifest or not _safe_epub_path(href):
                    raise EpubExportError("EPUB manifest 条目无效")
                archive_path = (PurePosixPath("OEBPS") / href).as_posix()
                if archive_path not in names:
                    raise EpubExportError(f"EPUB manifest 文件不存在: {href}")
                manifest[item_id] = (href, media_type, properties)

            spine_ids = [
                str(item.get("idref") or "")
                for item in package.findall("opf:spine/opf:itemref", opf_ns)
            ]
            if not spine_ids:
                raise EpubExportError("EPUB spine 为空")
            try:
                spine_hrefs = [manifest[item_id][0] for item_id in spine_ids]
            except KeyError as exc:
                raise EpubExportError("EPUB spine 与 manifest 不一致") from exc
            if any(manifest[item_id][1] != "application/xhtml+xml" for item_id in spine_ids):
                raise EpubExportError("EPUB spine 包含非 XHTML 条目")

            nav_items = [
                item for item in manifest.values() if "nav" in item[2].split()
            ]
            if len(nav_items) != 1:
                raise EpubExportError("EPUB 必须包含一个导航文档")
            nav_path = (PurePosixPath("OEBPS") / nav_items[0][0]).as_posix()
            nav_root = ElementTree.fromstring(archive.read(nav_path))
            xhtml_ns = {"xhtml": "http://www.w3.org/1999/xhtml"}
            epub_type = "{http://www.idpf.org/2007/ops}type"
            toc = next(
                (
                    node
                    for node in nav_root.findall(".//xhtml:nav", xhtml_ns)
                    if node.get(epub_type) == "toc"
                ),
                None,
            )
            if toc is None:
                raise EpubExportError("EPUB 导航文档缺少 toc")
            nav_hrefs = [
                str(link.get("href") or "")
                for link in toc.findall(".//xhtml:a", xhtml_ns)
            ]
            if nav_hrefs != spine_hrefs:
                raise EpubExportError("EPUB 目录与 spine 章节顺序不一致")
            return {
                "valid": True,
                "chapters": len(spine_hrefs),
                "files": len(names),
            }
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise EpubExportError(f"EPUB 结构无效: {exc}") from exc


def _safe_epub_path(value: str) -> bool:
    if not value or "\\" in value or "#" in value or "?" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and "." not in path.parts


def _xhtml(title: str, body: str, *, language: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{escape(language)}" lang="{escape(language)}">
<head><title>{escape(title)}</title><meta charset="utf-8" />
<link rel="stylesheet" type="text/css" href="../styles/book.css" /></head>
<body>{body}</body></html>
"""


def _nav(
    title: str,
    chapters: list[tuple[str, str, str]],
    *,
    language: str,
) -> str:
    items = "".join(
        f'<li><a href="text/{escape(filename)}">{escape(chapter_title)}</a></li>'
        for filename, chapter_title, _ in chapters
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"
      xml:lang="{escape(language)}" lang="{escape(language)}">
<head><title>{escape(title)}</title><meta charset="utf-8" /></head>
<body><nav epub:type="toc" id="toc"><h1>{escape(title)}</h1><ol>{items}</ol></nav></body></html>
"""


def _package(
    title: str,
    author: str,
    language: str,
    identifier: str,
    modified: str,
    chapters: list[tuple[str, str, str]],
    cover: tuple[str, bytes, str] | None,
) -> str:
    manifest = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="css" href="styles/book.css" media-type="text/css"/>',
    ]
    spine = []
    for index, (filename, _, _) in enumerate(chapters, start=1):
        item_id = f"chapter-{index:04d}"
        manifest.append(
            f'<item id="{item_id}" href="text/{filename}" media-type="application/xhtml+xml"/>'
        )
        spine.append(f'<itemref idref="{item_id}"/>')
    cover_meta = ""
    if cover:
        filename, _, media_type = cover
        manifest.append(
            '<item id="cover-image" '
            f'href="images/{escape(filename)}" media-type="{media_type}" '
            'properties="cover-image"/>'
        )
        cover_meta = '<meta name="cover" content="cover-image"/>'
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="book-id">{escape(identifier)}</dc:identifier>
<dc:title>{escape(title)}</dc:title><dc:creator>{escape(author)}</dc:creator>
<dc:language>{escape(language)}</dc:language>
<meta property="dcterms:modified">{modified}</meta>{cover_meta}
</metadata><manifest>{''.join(manifest)}</manifest><spine>{''.join(spine)}</spine></package>
"""
