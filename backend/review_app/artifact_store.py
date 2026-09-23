from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re


ALLOWED_SUFFIXES = {".docx", ".xlsx"}
MEDIA_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def save_artifact(directory: Path, content: bytes, filename: str) -> str:
    """保存生成文件并避免覆盖同名历史结果。"""
    directory.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r'[<>:"/\\|?*]', "_", Path(filename).stem)
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError("生成文件格式无效")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    saved_name = f"{stem}_{timestamp}{suffix}"
    (directory / saved_name).write_bytes(content)
    return saved_name


def list_artifacts(directory: Path, limit: int = 50) -> list[dict]:
    directory.mkdir(parents=True, exist_ok=True)
    files = sorted(
        (
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in ALLOWED_SUFFIXES
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return [
        {
            "filename": path.name,
            "modified_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(
                timespec="seconds"
            ),
            "size": path.stat().st_size,
            "kind": "word" if path.suffix.lower() == ".docx" else "excel",
        }
        for path in files[: max(1, limit)]
    ]


def resolve_artifact(directory: Path, filename: str) -> tuple[Path, str]:
    """校验历史文件名，避免读取输出目录之外的文件。"""
    safe_name = Path(filename).name
    suffix = Path(safe_name).suffix.lower()
    if safe_name != filename or suffix not in ALLOWED_SUFFIXES:
        raise ValueError("文档名称无效")
    target = directory / safe_name
    if not target.is_file():
        raise FileNotFoundError("没有找到这个历史文档")
    return target, MEDIA_TYPES[suffix]
