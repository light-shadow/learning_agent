"""PDF 资料读取器测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from study_agent.errors import StudyError
from study_agent.readers import _clean_text, read_local_source


def test_control_characters_are_removed_from_extracted_text() -> None:
    """验证 PDF 文本层中的控制分隔符不会进入知识点和题目。"""
    assert _clean_text("工具\x01运行时\n安全") == "工具 运行时\n安全"


def test_extracts_text_pdf(tmp_path: Path) -> None:
    """验证带文本层的 PDF 能被 pypdf 提取。"""
    path = tmp_path / "lesson.pdf"
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 72 720 Td (Tool Runtime validates input before handlers) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as output:
        writer.write(output)

    extracted = read_local_source(str(path))

    assert extracted.source_type.value == "pdf"
    assert "Tool Runtime" in extracted.normalized_text

    named_extracted = read_local_source(str(path), "AI Agent Tool Runtime.pdf")
    assert named_extracted.title == "AI Agent Tool Runtime.pdf"


def test_rejects_scanned_pdf_and_non_pdf_source(tmp_path: Path) -> None:
    """验证无文本扫描 PDF 与非 PDF 文件均得到稳定错误码。"""
    scanned = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with scanned.open("wb") as output:
        writer.write(output)
    with pytest.raises(StudyError, match="扫描 PDF") as error:
        read_local_source(str(scanned))
    assert error.value.code == "SCANNED_PDF_UNSUPPORTED"

    non_pdf = tmp_path / "lesson.docx"
    non_pdf.write_text("unsupported", encoding="utf-8")
    with pytest.raises(StudyError, match="仅支持 PDF") as error:
        read_local_source(str(non_pdf))
    assert error.value.code == "UNSUPPORTED_SOURCE_TYPE"
