"""PDF 简历文本抽取。

只支持 PDF(Word 推后)。返回纯文本,不做结构化(技术栈/年限/项目抽取推后)。
异常情况返回空字符串 + 警告信息,主应用据此决定是否继续。
"""
from __future__ import annotations

import io
import logging

from pypdf import PdfReader
from pypdf.errors import PdfReadError, EmptyFileError


logger = logging.getLogger(__name__)


class ResumeParseError(Exception):
    """简历解析失败(可识别的、已分类的错误)。"""


def parse_pdf_resume(file_bytes: bytes) -> str:
    """从 PDF 字节流抽取纯文本。

    Args:
        file_bytes: PDF 文件的原始字节(通常来自 Streamlit file_uploader.read())

    Returns:
        抽取出的纯文本(多页用换行拼接);失败时返回空字符串。

    Raises:
        ResumeParseError: 文件非 PDF / 加密 / 完全无法解析
    """
    if not file_bytes:
        raise ResumeParseError("文件为空")

    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except (PdfReadError, EmptyFileError) as e:
        raise ResumeParseError(f"无法识别为 PDF:{e}") from e

    if reader.is_encrypted:
        # 尝试空密码解密;失败则告知用户
        try:
            result = reader.decrypt("")
            if result == 0:
                raise ResumeParseError("PDF 已加密且无法用空密码解锁,请提供明文 PDF")
        except (PdfReadError, NotImplementedError) as e:
            raise ResumeParseError(f"PDF 解密失败:{e}") from e

    pages_text: list[str] = []
    for idx, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception as e:  # pypdf 偶尔对个别页抛异常
            logger.warning("第 %d 页抽取失败:%s", idx + 1, e)
            text = ""
        if text:
            pages_text.append(text)

    if not pages_text:
        raise ResumeParseError("PDF 中未抽取出任何文本(可能为扫描件或纯图片)")

    return "\n\n".join(pages_text)
