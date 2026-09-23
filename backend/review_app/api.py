from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
from threading import Thread
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .analysis import analyze_with_rag
from .analysis_parser import parse_analysis_sections, parse_task_table
from .artifact_store import list_artifacts, resolve_artifact
from .config import AVAILABLE_MODELS, DATA_DIR, MODEL_NAME, PROJECT_DIR
from .crawler import TgbCrawler
from .dragon.router import create_dragon_router
from .generation_service import generate_review_outputs
from .job_store import JobStore
from .knowledge import KnowledgeStore, sync_knowledge_incremental
from .llm import parse_with_deepseek
from .preprocessing import preprocess_text
from .review_input import extract_review_text
from .schemas import AnalyzeRequest, FetchReviewRequest, RetryGenerationRequest
from .task_manager import TaskManager


SITE_URL = os.getenv(
    "REVIEW_SITE_URL",
    "https://fupan-review-cockpit.netlify.app",
).rstrip("/")
SERVICE_VERSION = "1.9.2"
TOKEN_PATH = DATA_DIR / "service_token.txt"
DOCUMENT_DIR = PROJECT_DIR / "output"


def get_service_token() -> str:
    """读取或创建仅供本机站点调用的随机令牌。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if TOKEN_PATH.is_file():
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if len(token) >= 32:
            return token
    token = secrets.token_urlsafe(32)
    TOKEN_PATH.write_text(token, encoding="utf-8")
    return token


SERVICE_TOKEN = get_service_token()
JOB_STORE = JobStore()
JOB_STORE.mark_interrupted()
JOB_MANAGER = TaskManager(JOB_STORE)
# 兼容现有本机调试和测试入口，实际读写统一由 TaskManager 完成。
jobs = JOB_MANAGER.jobs
jobs_lock = JOB_MANAGER.lock


def _normalize_analysis_request(payload: AnalyzeRequest) -> AnalyzeRequest:
    review_text = preprocess_text(extract_review_text(payload))
    is_excel = payload.input_is_excel or (
        Path(payload.filename).suffix.lower() == ".xlsx"
        and bool(payload.content_base64)
    )
    return payload.model_copy(
        update={
            "text": review_text,
            "content_base64": "",
            "input_is_excel": is_excel,
        }
    )


def _persistable_request(payload: AnalyzeRequest) -> dict[str, Any]:
    return payload.model_dump(exclude={"content_base64"})


def _analysis_fingerprint(payload: AnalyzeRequest) -> str:
    """对会影响模型输出的输入生成摘要，不保存密钥和原始文件。"""
    value = {
        "review_date": payload.review_date,
        "text": payload.text,
        "generate_excel": payload.generate_excel,
        "generate_word": payload.generate_word,
        "input_is_excel": payload.input_is_excel,
        "model": payload.model or MODEL_NAME,
        "thinking_enabled": payload.thinking_enabled,
    }
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


app = FastAPI(title="复盘驾驶舱本地服务", version=SERVICE_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        SITE_URL,
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Review-Token"],
)


@app.middleware("http")
async def protect_local_api(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    host = request.headers.get("host", "").split(":", 1)[0].lower()
    if host not in {"127.0.0.1", "localhost"}:
        return JSONResponse(
            status_code=403,
            content={"detail": "本地服务只接受本机访问"},
        )
    return await call_next(request)


def _verify_token(value: str | None) -> None:
    if not value or not secrets.compare_digest(value, SERVICE_TOKEN):
        raise HTTPException(status_code=401, detail="请从“启动复盘驾驶舱”打开站点")


app.include_router(create_dragon_router(_verify_token))


@app.get("/api/status")
def status(x_review_token: str | None = Header(default=None)) -> dict:
    _verify_token(x_review_token)
    with KnowledgeStore() as store:
        stats = store.stats()
    return {
        "ok": True,
        "service_version": SERVICE_VERSION,
        "stats": stats,
        "api_key_configured": bool(os.getenv("DEEPSEEK_API_KEY", "").strip()),
        "available_models": list(AVAILABLE_MODELS),
        "default_model": MODEL_NAME,
    }


@app.post("/api/fetch-review")
def fetch_review(
    payload: FetchReviewRequest,
    x_review_token: str | None = Header(default=None),
) -> dict:
    _verify_token(x_review_token)
    try:
        return _fetch_review_result(payload.review_date)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _fetch_review_result(review_date: str) -> dict:
    target_date = date.fromisoformat(review_date)
    with TgbCrawler() as crawler:
        post = crawler.fetch_latest_review(target_date)
    return {
        "title": post["title"],
        "review_date": post["published_at"][:10],
        "source_url": post["url"],
        "text": post["body"],
    }


def _analysis_result(payload: AnalyzeRequest, progress=None, branch_update=None) -> dict:
    return generate_review_outputs(
        payload,
        document_dir=DOCUMENT_DIR,
        parse_excel=parse_with_deepseek,
        analyze_word=analyze_with_rag,
        progress=progress,
        branch_update=branch_update,
    )


@app.post("/api/analyze")
def analyze(
    payload: AnalyzeRequest,
    x_review_token: str | None = Header(default=None),
) -> dict:
    _verify_token(x_review_token)
    try:
        return _analysis_result(payload)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/posts")
def list_posts(x_review_token: str | None = Header(default=None)) -> dict:
    _verify_token(x_review_token)
    with KnowledgeStore() as store:
        posts = store.list_posts()
    return {
        "posts": [
            {
                "title": post["title"],
                "published_at": post["published_at"][:10],
                "views": post["views"],
                "reply_count": post["reply_count"],
                "likes": post["likes"],
                "scope": post["scope"],
                "body_truncated": bool(post["body_truncated"]),
                "capture_mode": post["capture_mode"],
                "url": post["url"],
            }
            for post in posts
        ]
    }


@app.get("/api/documents")
def list_documents(x_review_token: str | None = Header(default=None)) -> dict:
    _verify_token(x_review_token)
    return {"documents": list_artifacts(DOCUMENT_DIR)}


@app.get("/api/documents/{filename}")
def download_document(
    filename: str,
    x_review_token: str | None = Header(default=None),
):
    _verify_token(x_review_token)
    try:
        target, media_type = resolve_artifact(DOCUMENT_DIR, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path=target,
        filename=target.name,
        media_type=media_type,
    )


def _run_sync(job_id: str) -> None:
    def progress(message: str, current: int, total: int) -> None:
        JOB_MANAGER.update(
            job_id,
            status="running",
            message=message,
            current=current,
            total=total,
        )

    try:
        result = sync_knowledge_incremental(progress)
        with KnowledgeStore() as store:
            stats = store.stats()
        JOB_MANAGER.update(
            job_id,
            status="succeeded",
            message="昨日新增检查与知识库更新完成",
            result=result,
            stats=stats,
        )
    except Exception as exc:
        JOB_MANAGER.update(job_id, status="failed", message=str(exc))


def _run_fetch_review(job_id: str, review_date: str) -> None:
    try:
        JOB_MANAGER.update(
            job_id,
            status="running",
            message="正在连接公开复盘页面",
            current=1,
            total=2,
        )
        result = _fetch_review_result(review_date)
        JOB_MANAGER.update(
            job_id,
            status="succeeded",
            message="公开复盘正文已载入",
            current=2,
            total=2,
            result=result,
        )
    except Exception as exc:
        JOB_MANAGER.update(job_id, status="failed", message=str(exc))


def _run_analysis(job_id: str, payload: AnalyzeRequest) -> None:
    def finish_updates() -> dict:
        current = JOB_MANAGER.snapshot(job_id) or {}
        started_at = current.get("started_at", "")
        try:
            started = datetime.fromisoformat(started_at)
            duration_ms = round((datetime.now() - started).total_seconds() * 1000)
        except (TypeError, ValueError):
            duration_ms = 0
        return {
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "duration_ms": duration_ms,
        }

    def progress(message: str, current: int, total: int) -> None:
        JOB_MANAGER.update(
            job_id,
            status="running",
            message=message,
            current=current,
            total=total,
        )

    def branch_update(name: str, state: dict) -> None:
        current = JOB_MANAGER.snapshot(job_id) or {}
        branches = dict(current.get("branches") or {})
        branches[name] = dict(state)
        JOB_MANAGER.update(job_id, branches=branches)

    try:
        result = _analysis_result(payload, progress, branch_update)
        excel_done = bool(result["excel_filename"])
        word_done = bool(result["document_filename"])
        if excel_done and word_done:
            message = "Excel 整理与 Word 布局分析均已完成"
        elif excel_done:
            message = "Excel 已完成；Word 未生成，可在额度恢复后重试"
        elif word_done:
            message = "Word 已完成；Excel 未生成，可在额度恢复后重试"
        else:
            message = "输入文件已保留，无需重复生成 Excel"
        current = JOB_MANAGER.snapshot(job_id) or {}
        JOB_MANAGER.update(
            job_id,
            status="succeeded",
            message=message,
            current=current.get("total", 1),
            result=result,
            **finish_updates(),
        )
    except Exception as exc:
        JOB_MANAGER.update(
            job_id,
            status="failed",
            message=str(exc),
            **finish_updates(),
        )


@app.post("/api/fetch-review-async")
def start_fetch_review(
    payload: FetchReviewRequest,
    x_review_token: str | None = Header(default=None),
) -> dict:
    _verify_token(x_review_token)
    job_id = secrets.token_urlsafe(12)
    JOB_MANAGER.register(
        job_id,
        {
            "kind": "fetch_review",
            "status": "pending",
            "message": "准备自爬取公开复盘",
            "current": 0,
            "total": 2,
        },
    )
    Thread(
        target=_run_fetch_review,
        args=(job_id, payload.review_date),
        daemon=True,
    ).start()
    return {"job_id": job_id, "status": "pending"}


@app.post("/api/analyze-async")
def start_analysis(
    payload: AnalyzeRequest,
    x_review_token: str | None = Header(default=None),
) -> dict:
    _verify_token(x_review_token)
    if not payload.generate_excel and not payload.generate_word:
        raise HTTPException(status_code=400, detail="至少选择生成 Excel 或 Word 中的一项")
    try:
        normalized = _normalize_analysis_request(payload)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _start_analysis_job(normalized)


def _start_analysis_job(
    payload: AnalyzeRequest,
    *,
    retry_of: str = "",
) -> dict:
    job_id = secrets.token_urlsafe(12)
    selected = [
        label
        for enabled, label in (
            (payload.generate_excel, "Excel"),
            (payload.generate_word, "Word"),
        )
        if enabled
    ]
    job = {
        "kind": "analysis",
        "status": "pending",
        "message": f"准备生成{' + '.join(selected)}",
        "current": 0,
        "total": 1 + len(selected),
        "retry_of": retry_of,
        "review_date": payload.review_date,
        "filename": payload.filename,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "request_fingerprint": _analysis_fingerprint(payload),
        "branches": {
            "excel": {
                "status": "pending" if payload.generate_excel else "skipped",
                "message": (
                    "等待整理完整复盘"
                    if payload.generate_excel
                    else "本次未选择 Excel"
                ),
            },
            "word": {
                "status": "pending" if payload.generate_word else "skipped",
                "message": (
                    "等待生成核心布局分析"
                    if payload.generate_word
                    else "本次未选择 Word"
                ),
            },
        },
    }
    registered_id = JOB_MANAGER.register(
        job_id,
        job,
        request_payload=_persistable_request(payload),
    )
    if registered_id != job_id:
        return {
            "job_id": registered_id,
            "status": "running",
            "reused": True,
        }
    Thread(target=_run_analysis, args=(job_id, payload), daemon=True).start()
    return {"job_id": job_id, "status": "pending", "reused": False}


@app.post("/api/jobs/{job_id}/retry")
def retry_generation(
    job_id: str,
    payload: RetryGenerationRequest,
    x_review_token: str | None = Header(default=None),
) -> dict:
    _verify_token(x_review_token)
    previous = JOB_MANAGER.snapshot(job_id)
    request_payload = JOB_MANAGER.store.get_request(job_id)
    if not previous or not request_payload:
        raise HTTPException(status_code=404, detail="没有找到可重试的生成任务")
    branch_state = (previous.get("branches") or {}).get(payload.branch) or {}
    if branch_state.get("status") != "failed":
        raise HTTPException(status_code=400, detail="只能单独重试失败的生成项")
    request_payload.update(
        model=payload.model or request_payload.get("model", MODEL_NAME),
        thinking_enabled=payload.thinking_enabled,
        generate_excel=payload.branch == "excel",
        generate_word=payload.branch == "word",
    )
    normalized = AnalyzeRequest.model_validate(request_payload)
    return _start_analysis_job(normalized, retry_of=job_id)


@app.get("/api/jobs/recent")
def recent_generation_jobs(
    limit: int = 10,
    x_review_token: str | None = Header(default=None),
) -> dict:
    _verify_token(x_review_token)
    return {"jobs": JOB_MANAGER.store.recent(limit)}


@app.get("/api/runs")
def recent_run_records(
    limit: int = 20,
    x_review_token: str | None = Header(default=None),
) -> dict:
    _verify_token(x_review_token)
    records = []
    for item in JOB_MANAGER.store.recent(50):
        if item.get("kind") != "analysis":
            continue
        result = item.get("result") or {}
        records.append(
            {
                "job_id": item["job_id"],
                "status": item.get("status", ""),
                "message": item.get("message", ""),
                "review_date": item.get("review_date", ""),
                "filename": item.get("filename", ""),
                "started_at": item.get("started_at", item.get("created_at", "")),
                "finished_at": item.get("finished_at", ""),
                "duration_ms": item.get("duration_ms", 0),
                "retry_of": item.get("retry_of", ""),
                "branches": item.get("branches") or {},
                "sources": [
                    {
                        "title": source.get("title", ""),
                        "source_type": source.get("source_type", ""),
                        "source_url": source.get("source_url", ""),
                        "retrieval_score": source.get("retrieval_score", 0),
                    }
                    for source in result.get("sources", [])
                ],
                "excel_filename": result.get("excel_filename", ""),
                "document_filename": result.get("document_filename", ""),
            }
        )
        if len(records) >= max(1, min(limit, 50)):
            break
    return {"runs": records}


@app.post("/api/sync")
def start_sync(x_review_token: str | None = Header(default=None)) -> dict:
    _verify_token(x_review_token)
    running = JOB_MANAGER.find_running("sync")
    if running:
        job_id, job = running
        return {"job_id": job_id, "status": job["status"]}
    job_id = secrets.token_urlsafe(12)
    JOB_MANAGER.register(
        job_id,
        {
            "kind": "sync",
            "status": "pending",
            "message": "准备检查昨日新增帖子",
            "current": 0,
            "total": 1,
        },
    )
    Thread(target=_run_sync, args=(job_id,), daemon=True).start()
    return {"job_id": job_id, "status": "pending"}


@app.get("/api/jobs/{job_id}")
def get_job(
    job_id: str,
    x_review_token: str | None = Header(default=None),
) -> dict:
    _verify_token(x_review_token)
    job = JOB_MANAGER.snapshot(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="没有找到这次更新任务")
    return job
