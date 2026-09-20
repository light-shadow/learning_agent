"""面向 AI Agent 学习资料的 PDF 读取器。"""

from __future__ import annotations

import hashlib
import logging
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from .errors import StudyError
from .models import SourceChunk, SourceType

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_CHUNK_CHARS = 3000
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractedSource:
    """读取器输出的受控资料内容。"""

    source_type: SourceType
    locator: str
    title: str
    content_hash: str
    normalized_text: str
    chunks: list[SourceChunk]


def read_local_source(raw_path: str, display_title: str | None = None) -> ExtractedSource:
    """读取本地 PDF，并优先使用调用方传入的安全展示文件名。"""
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        raise StudyError("SOURCE_NOT_FOUND", f"资料不存在：{path}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise StudyError("SOURCE_TOO_LARGE", "本地资料超过 20 MB 限制")
    LOGGER.info("pdf_import_started file_name=%s size_bytes=%d", path.name, path.stat().st_size)
    suffix = path.suffix.lower()
    if suffix != ".pdf":
        raise StudyError("UNSUPPORTED_SOURCE_TYPE", "当前版本仅支持 PDF 格式的 AI Agent 学习资料")
    title, text = _extract_pdf(path)
    if display_title:
        title = _clean_text(Path(display_title).name) or title
    extracted = _build_extracted(SourceType.PDF, str(path), title, text)
    LOGGER.info(
        "pdf_import_completed file_name=%s chunk_count=%d text_chars=%d",
        path.name,
        len(extracted.chunks),
        len(extracted.normalized_text),
    )
    return extracted


def _extract_pdf(path: Path) -> tuple[str, str]:
    """提取 PDF 各页文本，并把纯扫描件标记为不支持。"""
    try:
        reader = PdfReader(path)
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        title = str(reader.metadata.title) if reader.metadata and reader.metadata.title else path.stem
    except Exception as exc:
        raise StudyError("PDF_EXTRACTION_FAILED", "PDF 文本提取失败") from exc
    if not _clean_text(text):
        raise StudyError("SCANNED_PDF_UNSUPPORTED", "未提取到文本，扫描 PDF 需 OCR 支持")
    return title, text


def _build_extracted(source_type: SourceType, locator: str, title: str, text: str) -> ExtractedSource:
    """清洗资料文本、计算来源哈希并切分为可追溯片段。"""
    normalized = _clean_text(text)
    if not normalized:
        raise StudyError("EMPTY_SOURCE", "资料中没有可用于学习的文本")
    chunks = _chunk_text(normalized)
    return ExtractedSource(
        source_type=source_type,
        locator=locator,
        title=_clean_text(title)[:160] or "未命名资料",
        content_hash=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        normalized_text=normalized,
        chunks=chunks,
    )


def _chunk_text(text: str) -> list[SourceChunk]:
    """按段落优先切分文本，避免截断单个知识段。"""
    chunks: list[SourceChunk] = []
    buffer = ""
    for paragraph in text.split("\n"):
        candidate = f"{buffer}\n{paragraph}".strip()
        if buffer and len(candidate) > MAX_CHUNK_CHARS:
            chunks.append(SourceChunk(chunk_index=len(chunks), text=buffer))
            buffer = paragraph
        else:
            buffer = candidate
    if buffer:
        chunks.append(SourceChunk(chunk_index=len(chunks), text=buffer))
    return chunks


def _clean_text(text: str) -> str:
    """移除不可见控制字符并统一空白，保留段落边界以便后续生成引用。"""
    sanitized = "".join(
        character if character in {"\n", "\r", "\t"} or not unicodedata.category(character).startswith("C") else " "
        for character in text
    )
    return "\n".join(" ".join(line.split()) for line in sanitized.splitlines() if line.strip())
