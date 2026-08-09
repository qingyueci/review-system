from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
import inspect
import os
from pathlib import Path
from time import perf_counter
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
ExcelParser = Callable[..., dict]
WordAnalyzer = Callable[..., str]


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
        "retrieval_score": source.get("retrieval_score", 0),
        "retrieval_mode": source.get("retrieval_mode", ""),
    }


def _call_with_metrics(function: Callable, *args, metrics: dict) -> Any:
    parameters = inspect.signature(function).parameters.values()
    accepts_metrics = any(
        parameter.name == "metrics"
        or parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )
    if accepts_metrics:
        return function(*args, metrics=metrics)
    return function(*args)


def _error_type(message: str) -> str:
    if "额度不足" in message or "限流" in message or "HTTP 429" in message or "HTTP 499" in message:
        return "quota_or_rate_limit"
    if "超时" in message or "没有返回完整" in message:
        return "timeout"
    if "密钥无效" in message or "没有模型权限" in message:
        return "authentication"
    if "无法连接" in message or "网络" in message:
        return "network"
    return "generation_error"


def _generate_excel_artifact(
    api_key: str,
    review_text: str,
    review_date: str,
    document_dir: Path,
    parse_excel: ExcelParser,
    metrics: dict,
) -> dict:
    """沿用原 Excel 解析与排版链路，不改变既有工作簿格式。"""
    data = validate_data(
        _call_with_metrics(parse_excel, api_key, review_text, metrics=metrics)
    )
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
    metrics: dict,
) -> dict:
    analysis = _call_with_metrics(
        analyze_word,
        api_key,
        review_text,
        sources,
        metrics=metrics,
    )
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
            api_key, review_text, payload.review_date, document_dir, parse_excel,
            branch_runtime["excel"]["metrics"],
        )
    if payload.generate_word:
        runners["word"] = lambda: _generate_word_artifact(
            api_key, review_text, sources, payload.review_date, document_dir,
            analyze_word, branch_runtime["word"]["metrics"],
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
    branch_runtime: dict[str, dict[str, Any]] = {}

    def run_branch(name: str, runner):
        branch_runtime[name] = {
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "started_clock": perf_counter(),
            "metrics": {},
        }
        branches[name] = {
            "status": "running",
            "message": f"正在执行{labels[name]}",
            "started_at": branch_runtime[name]["started_at"],
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
            runtime = branch_runtime[name]
            finished_at = datetime.now().isoformat(timespec="seconds")
            duration_ms = round(
                (perf_counter() - runtime["started_clock"]) * 1000
            )
            details = {
                "started_at": runtime["started_at"],
                "finished_at": finished_at,
                "duration_ms": duration_ms,
                "model": runtime["metrics"].get("model", ""),
                "usage": runtime["metrics"].get(
                    "usage",
                    {"available": False},
                ),
                "source_count": len(sources) if name == "word" else 0,
                "source_refs": (
                    [
                        {
                            "title": source["title"],
                            "source_type": source["source_type"],
                            "source_url": source["source_url"],
                            "retrieval_score": source.get("retrieval_score", 0),
                        }
                        for source in sources
                    ]
                    if name == "word"
                    else []
                ),
            }
            try:
                result.update(future.result())
                branches[name] = {
                    "status": "succeeded",
                    "message": f"{labels[name]}已生成并保存",
                    **details,
                }
            except Exception as exc:
                message = str(exc) or f"{labels[name]}生成失败"
                branches[name] = {
                    "status": "failed",
                    "message": message,
                    "error_type": _error_type(message),
                    **details,
                }
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
