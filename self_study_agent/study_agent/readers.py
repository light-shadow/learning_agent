"""PDF、DOCX 与静态网页读取器。"""

from __future__ import annotations

import hashlib
import ipaddress
import socket
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from docx import Document
from pypdf import PdfReader

from .errors import StudyError
from .models import SourceChunk, SourceType

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_WEB_BYTES = 2 * 1024 * 1024
MAX_CHUNK_CHARS = 3000


@dataclass(frozen=True)
class ExtractedSource:
    """读取器输出的受控资料内容。"""

    source_type: SourceType
    locator: str
    title: str
    content_hash: str
    normalized_text: str
    chunks: list[SourceChunk]


def read_local_source(raw_path: str) -> ExtractedSource:
    """读取本地 PDF 或 DOCX，并在进入后续链路前限制文件大小。"""
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        raise StudyError("SOURCE_NOT_FOUND", f"资料不存在：{path}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise StudyError("SOURCE_TOO_LARGE", "本地资料超过 20 MB 限制")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        title, text = _extract_pdf(path)
        source_type = SourceType.PDF
    elif suffix == ".docx":
        title, text = _extract_docx(path)
        source_type = SourceType.DOCX
    elif suffix == ".doc":
        raise StudyError("UNSUPPORTED_SOURCE_TYPE", "第一版仅支持 DOCX，不支持旧版 DOC")
    else:
        raise StudyError("UNSUPPORTED_SOURCE_TYPE", "仅支持 PDF、DOCX 或公开静态网页")
    return _build_extracted(source_type, str(path), title, text)


def fetch_web_source(url: str) -> ExtractedSource:
    """抓取公开静态网页正文，并在请求前后校验 URL 安全边界。"""
    _validate_public_url(url)
    try:
        with httpx.Client(follow_redirects=True, timeout=10.0, max_redirects=3) as client:
            with client.stream("GET", url, headers={"User-Agent": "SelfStudyAgent/1.0"}) as response:
                response.raise_for_status()
                _validate_public_url(str(response.url))
                content_type = response.headers.get("content-type", "")
                if "html" not in content_type.lower():
                    raise StudyError("UNSUPPORTED_WEB_CONTENT", "网页响应不是 HTML")
                chunks: list[bytes] = []
                received_bytes = 0
                for chunk in response.iter_bytes(chunk_size=65536):
                    received_bytes += len(chunk)
                    if received_bytes > MAX_WEB_BYTES:
                        raise StudyError("SOURCE_TOO_LARGE", "网页正文超过 2 MB 限制")
                    chunks.append(chunk)
                payload = b"".join(chunks)
    except StudyError:
        raise
    except httpx.TimeoutException as exc:
        raise StudyError("SOURCE_FETCH_TIMEOUT", "网页请求超时") from exc
    except httpx.HTTPError as exc:
        raise StudyError("SOURCE_FETCH_FAILED", "网页抓取失败") from exc
    html = payload.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript", "svg", "iframe"]):
        node.decompose()
    title = _clean_text(soup.title.get_text(" ", strip=True) if soup.title else "网页资料")
    root = soup.find("article") or soup.find("main") or soup.body or soup
    text = _clean_text(root.get_text("\n", strip=True))
    return _build_extracted(SourceType.WEB, str(response.url), title or "网页资料", text)


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


def _extract_docx(path: Path) -> tuple[str, str]:
    """提取 DOCX 段落和表格单元格文本。"""
    try:
        document = Document(path)
        paragraphs = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
        cells = [cell.text for table in document.tables for row in table.rows for cell in row.cells]
    except Exception as exc:
        raise StudyError("DOCX_EXTRACTION_FAILED", "DOCX 文本提取失败") from exc
    text = "\n".join(paragraphs + cells)
    if not _clean_text(text):
        raise StudyError("EMPTY_SOURCE", "DOCX 中没有可用于学习的文本")
    return (paragraphs[0][:120] if paragraphs else path.stem), text


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


def _validate_public_url(url: str) -> None:
    """拒绝非 Web 协议、本机和私有网络地址，降低 SSRF 风险。"""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise StudyError("UNSAFE_URL", "仅支持带公开主机名的 HTTP(S) 地址")
    host = parsed.hostname.rstrip(".")
    if host.lower() in {"localhost", "localhost.localdomain"}:
        raise StudyError("UNSAFE_URL", "不允许访问本机地址")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443)}
    except socket.gaierror as exc:
        raise StudyError("SOURCE_FETCH_FAILED", "无法解析网页主机名") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise StudyError("UNSAFE_URL", "不允许访问私有或保留网络地址")
