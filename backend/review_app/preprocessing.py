import re

from .cleaning import normalize_text
from .config import MAX_INPUT_CHARS


def preprocess_text(raw_text: str) -> str:
    """清理网页复制文本，保留原始语义。"""
    text = normalize_text(raw_text)
    text = re.sub(r"^.*下载.*APP.*$", "", text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r"^[ \t]+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise ValueError("复盘原文不能为空")
    if len(text) > MAX_INPUT_CHARS:
        raise ValueError(f"原文过长，最多允许 {MAX_INPUT_CHARS} 个字符")
    return text
