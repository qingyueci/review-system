import hashlib
import html
import re


NOISE_LINE_PATTERNS = (
    r"下载.*APP",
    r"打开淘股吧APP",
    r"声明：.*远离非法证券活动",
    r"淘股吧中国大陆知名",
    r"投资有风险.*入市需谨慎",
)

GREETING_PATTERNS = (
    r"^(先赞后看[，,\s]*)?(刺大|老师|楼主)?(发大财|发财|好|您好|辛苦了|周末愉快)[！!。.\s]*$",
    r"^(谢谢|感谢)(刺大|老师|楼主)?[！!。.\s]*$",
    r"^[\W_]*(沙发|前排|打卡)[\W_]*$",
)


def normalize_text(value: str) -> str:
    """统一网页文本格式，保留段落语义。"""
    text = html.unescape(value or "")
    text = text.replace("\u200b", "").replace("\ufeff", "").replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\[淘股吧\]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    for pattern in NOISE_LINE_PATTERNS:
        text = re.sub(rf"^.*{pattern}.*$", "", text, flags=re.IGNORECASE | re.MULTILINE)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def is_greeting_or_noise(value: str) -> bool:
    text = normalize_text(value)
    if not text:
        return True
    compact = re.sub(r"\s+", "", text)
    if len(compact) <= 2:
        return True
    return any(re.fullmatch(pattern, compact, flags=re.IGNORECASE) for pattern in GREETING_PATTERNS)


def is_informative(value: str, *, minimum: int = 8) -> bool:
    text = normalize_text(value)
    compact = re.sub(r"\s+", "", text)
    if len(compact) < minimum or is_greeting_or_noise(text):
        return False
    meaningful = re.sub(r"[\W_，。！？、；：“”‘’（）【】《》]+", "", compact)
    return len(meaningful) >= minimum


def content_hash(*values: str) -> str:
    joined = "\x1f".join(normalize_text(value) for value in values)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def split_chunks(value: str, *, max_chars: int = 1200, overlap_chars: int = 120) -> list[str]:
    """按自然段切片，超长段落才使用字符窗口。"""
    text = normalize_text(value)
    if not text:
        return []
    paragraphs = [item.strip() for item in re.split(r"\n{2,}", text) if item.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            step = max(1, max_chars - overlap_chars)
            chunks.extend(paragraph[index:index + max_chars] for index in range(0, len(paragraph), step))
            continue
        candidate = f"{current}\n\n{paragraph}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks
