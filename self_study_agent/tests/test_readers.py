"""资料读取器测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject

from study_agent.errors import StudyError
from study_agent import readers
from study_agent.readers import _clean_text, read_local_source


def test_reads_docx_and_rejects_duplicate_content(tmp_path: Path) -> None:
    """验证 DOCX 正文会被切分为可追溯文本块。"""
    path = tmp_path / "lesson.docx"
    document = Document()
    document.add_paragraph("Agent Loop 是模型、工具结果和下一轮决策组成的闭环。")
    document.add_paragraph("Tool Runtime 在副作用发生前校验参数与权限。")
    document.save(path)

    extracted = read_local_source(str(path))

    assert extracted.source_type.value == "docx"
    assert "Agent Loop" in extracted.normalized_text
    assert extracted.chunks[0].chunk_index == 0


def test_control_characters_are_removed_from_extracted_text() -> None:
    """验证 PDF 文本层中的控制分隔符不会进入知识点和题目。"""
    assert _clean_text("工具\x01运行时\n安全") == "工具 运行时\n安全"


def test_extracts_text_pdf(tmp_path: Path) -> None:
    """验证带文本层的 PDF 能被 pypdf 提取。"""
    path = tmp_path / "lesson.pdf"
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = writer._add_object(DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")}))
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 720 Td (Tool Runtime validates input before handlers) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as output:
        writer.write(output)

    extracted = read_local_source(str(path))

    assert extracted.source_type.value == "pdf"
    assert "Tool Runtime" in extracted.normalized_text


def test_rejects_scanned_pdf_and_legacy_doc(tmp_path: Path) -> None:
    """验证无文本扫描 PDF 与旧 DOC 均得到稳定错误码。"""
    scanned = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with scanned.open("wb") as output:
        writer.write(output)
    with pytest.raises(StudyError, match="扫描 PDF") as error:
        read_local_source(str(scanned))
    assert error.value.code == "SCANNED_PDF_UNSUPPORTED"

    legacy = tmp_path / "old.doc"
    legacy.write_text("legacy", encoding="utf-8")
    with pytest.raises(StudyError, match="DOCX") as error:
        read_local_source(str(legacy))
    assert error.value.code == "UNSUPPORTED_SOURCE_TYPE"


def test_fetches_static_html_and_rejects_private_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证网页正文提取与私网地址拒绝边界。"""
    with pytest.raises(StudyError) as error:
        readers._validate_public_url("http://127.0.0.1/internal")
    assert error.value.code == "UNSAFE_URL"

    class Response:
        """模拟受控的公开 HTML 响应。"""

        url = "https://example.com/article"
        headers = {"content-type": "text/html; charset=utf-8"}

        def raise_for_status(self) -> None:
            """模拟成功 HTTP 响应。"""

        def iter_bytes(self, chunk_size: int):
            """按块返回网页正文。"""
            yield b"<html><head><title>Agent Course</title></head><body><main><p>Tool Runtime validates inputs.</p></main></body></html>"

        def __enter__(self):
            """进入响应上下文。"""
            return self

        def __exit__(self, *args):
            """退出响应上下文。"""
            return False

    class Client:
        """模拟 httpx Client，避免测试访问真实网络。"""

        def __init__(self, **kwargs):
            """接收客户端配置。"""

        def stream(self, *args, **kwargs):
            """返回固定响应。"""
            return Response()

        def __enter__(self):
            """进入客户端上下文。"""
            return self

        def __exit__(self, *args):
            """退出客户端上下文。"""
            return False

    monkeypatch.setattr(readers, "_validate_public_url", lambda url: None)
    monkeypatch.setattr(readers.httpx, "Client", Client)
    extracted = readers.fetch_web_source("https://example.com/article")
    assert extracted.title == "Agent Course"
    assert "Tool Runtime" in extracted.normalized_text
