from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import os
from pathlib import Path
from typing import Any, Callable

from .analysis_parser import parse_analysis_sections, parse_task_table
from .artifact_store import save_artifact
from .docx_export import generate_analysis_docx
from .excel import generate_excel
from .knowledge import KnowledgeStore
from .preprocessing import preprocess_text
from .review_input import extract_review_text
from .schemas import AnalyzeRequest
from .validation import validate_data


ProgressCallback = Callable[[str, int, int], None]
BranchCallback = Callable[[str, dict], None]
ExcelParser = Callable[[str, str], dict]
WordAnalyzer = Callable[[str, str, list[dict]], str]


def _public_source(source: dict) -> dict:
    labels = {
        "qa": "刺大本人回复",
        "post": "历史原帖",
        "manual": "人工整理体系",
        "community": "社区精选观点",
    }
    return {
        "level": labels.get(source["source_type"], "公开资料"),
        "title": source["title"],
        "published_at": source["published_at"][:10],
        "source_url": source["source_url"],
        "excerpt": source["content"][:360],
        "source_type": source["source_type"],
    }


def _generate_excel_artifact(
    api_key: str,
    review_text: str,
    review_date: str,
    document_dir: Path,
    parse_excel: ExcelParser,
) -> dict:
    """沿用原 Excel 解析与排版链路，不改变既有工作簿格式。"""
    data = validate_data(parse_excel(api_key, review_text))
    if review_date:
        data["meta"]["date"] = review_date
    content, filename = generate_excel(data)
    return {
        "excel_base64": "",
        "excel_filename": save_artifact(document_dir, content, filename),
    }


def _generate_word_artifact(
    api_key: str,
    review_text: str,
    sources: list[dict],
    review_date: str,
    document_dir: Path,
    analyze_word: WordAnalyzer,
) -> dict:
    analysis = analyze_word(api_key, review_text, sources)
    document, filename = generate_analysis_docx(
        analysis,
        sources,
        review_date=review_date or date.today().isoformat(),
    )
    return {
        "analysis": analysis,
        "sections": parse_analysis_sections(analysis),
        "tasks": parse_task_table(analysis),
        "document_base64": "",
        "document_filename": save_artifact(document_dir, document, filename),
    }


def generate_review_outputs(
    payload: AnalyzeRequest,
    *,
    document_dir: Path,
    parse_excel: ExcelParser,
    analyze_word: WordAnalyzer,
    progress: ProgressCallback | None = None,
    branch_update: BranchCallback | None = None,
) -> dict:
    """清洗一次输入，并行生成 Excel 和 Word，单分支失败不丢另一份结果。"""
    if not payload.generate_excel and not payload.generate_word:
        raise ValueError("至少选择生成 Excel 或 Word 中的一项")

    review_text = preprocess_text(extract_review_text(payload))
    api_key = payload.api_key.strip() or os.getenv("KIMI_API_KEY", "").strip()
    sources: list[dict] = []
    if payload.generate_word:
        with KnowledgeStore() as store:
            sources = store.search(review_text, limit=12)

    runners: dict[str, Any] = {}
    branches = {
        "excel": {
            "status": "pending" if payload.generate_excel else "skipped",
            "message": "等待整理完整复盘" if payload.generate_excel else "本次未选择 Excel",
        },
        "word": {
            "status": "pending" if payload.generate_word else "skipped",
            "message": "等待生成核心布局分析" if payload.generate_word else "本次未选择 Word",
        },
    }

    is_excel_input = payload.input_is_excel or (
        Path(payload.filename).suffix.lower() == ".xlsx"
        and bool(payload.content_base64)
    )
    if payload.generate_excel and is_excel_input:
        branches["excel"] = {
            "status": "skipped",
            "message": "导入内容已经是 Excel，本次保留原文件并只生成 Word",
        }
    elif payload.generate_excel:
        runners["excel"] = lambda: _generate_excel_artifact(
            api_key,
            review_text,
            payload.review_date,
            document_dir,
            parse_excel,
        )
    if payload.generate_word:
        runners["word"] = lambda: _generate_word_artifact(
            api_key,
            review_text,
            sources,
            payload.review_date,
            document_dir,
            analyze_word,
        )

    total = max(1, len(runners) + 1)
    if progress:
        progress("每日复盘已清洗，正在启动并行生成", 1, total)

    result = {
        "analysis": "",
        "sections": {},
        "tasks": [],
        "sources": [_public_source(source) for source in sources],
        "document_base64": "",
        "document_filename": "",
        "excel_base64": "",
        "excel_filename": "",
        "branches": branches,
        "warnings": [],
    }
    if not runners:
        return result

    labels = {"excel": "Excel 整理", "word": "Word 布局分析"}

    def run_branch(name: str, runner):
        branches[name] = {
            "status": "running",
            "message": f"正在执行{labels[name]}",
        }
        if branch_update:
            branch_update(name, branches[name])
        return runner()

    completed_count = 0
    with ThreadPoolExecutor(max_workers=len(runners)) as executor:
        futures = {
            executor.submit(run_branch, name, runner): name
            for name, runner in runners.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            completed_count += 1
            try:
                result.update(future.result())
                branches[name] = {
                    "status": "succeeded",
                    "message": f"{labels[name]}已生成并保存",
                }
            except Exception as exc:
                message = str(exc) or f"{labels[name]}生成失败"
                branches[name] = {"status": "failed", "message": message}
                result["warnings"].append(f"{labels[name]}失败：{message}")
            if branch_update:
                branch_update(name, branches[name])
            if progress:
                outcome = (
                    "已完成"
                    if branches[name]["status"] == "succeeded"
                    else "未完成"
                )
                progress(
                    f"{labels[name]}{outcome}",
                    completed_count + 1,
                    total,
                )

    result["branches"] = branches
    succeeded = [
        name
        for name, state in branches.items()
        if state["status"] == "succeeded"
    ]
    if not succeeded and not any(
        state["status"] == "skipped" for state in branches.values()
    ):
        raise RuntimeError("；".join(result["warnings"]) or "本次生成没有成功输出")
    return result
