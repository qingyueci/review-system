from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from threading import Lock, Thread
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .analysis import analyze_with_rag
from .analysis_parser import parse_analysis_sections, parse_task_table
from .config import DATA_DIR, PROJECT_DIR
from .crawler import TgbCrawler
from .docx_export import generate_analysis_docx
from .excel import generate_excel
from .job_store import JobStore
from .knowledge import KnowledgeStore, sync_top_year
from .llm import parse_with_kimi
from .preprocessing import preprocess_text
from .review_input import extract_review_text
from .schemas import AnalyzeRequest, FetchReviewRequest, RetryGenerationRequest
from .validation import validate_data


SITE_URL = os.getenv(
    "REVIEW_SITE_URL",
    "https://fupan-cockpit.junxicai1.chatgpt.site",
).rstrip("/")
SERVICE_VERSION = "1.3.0"
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
jobs: dict[str, dict[str, Any]] = {}
jobs_lock = Lock()
JOB_STORE = JobStore()
JOB_STORE.mark_interrupted()


def _register_job(
    job_id: str,
    job: dict[str, Any],
    request_payload: dict[str, Any] | None = None,
) -> str:
    with jobs_lock:
        fingerprint = job.get("request_fingerprint")
        if fingerprint:
            for existing_id, existing in jobs.items():
                if (
                    existing.get("kind") == "analysis"
                    and existing.get("status") in {"pending", "running"}
                    and existing.get("request_fingerprint") == fingerprint
                ):
                    return existing_id
        jobs[job_id] = dict(job)
        snapshot = dict(jobs[job_id])
    if job.get("kind") == "analysis":
        JOB_STORE.save(job_id, snapshot, request_payload)
        JOB_STORE.prune()
    return job_id


def _update_job(job_id: str, **updates: Any) -> dict[str, Any]:
    with jobs_lock:
        if job_id not in jobs:
            stored = JOB_STORE.get(job_id)
            if not stored:
                raise KeyError(job_id)
            jobs[job_id] = stored
        jobs[job_id].update(updates)
        snapshot = dict(jobs[job_id])
    if snapshot.get("kind") == "analysis":
        JOB_STORE.save(job_id, snapshot)
    return snapshot


def _job_snapshot(job_id: str) -> dict[str, Any] | None:
    with jobs_lock:
        current = jobs.get(job_id)
        if current:
            return dict(current)
    stored = JOB_STORE.get(job_id)
    if stored:
        with jobs_lock:
            jobs[job_id] = dict(stored)
        return stored
    return None


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
    return payload.model_dump(exclude={"api_key", "content_base64"})


def _analysis_fingerprint(payload: AnalyzeRequest) -> str:
    """对会影响模型输出的输入生成摘要，不保存密钥和原始文件。"""
    value = {
        "review_date": payload.review_date,
        "text": payload.text,
        "generate_excel": payload.generate_excel,
        "generate_word": payload.generate_word,
        "input_is_excel": payload.input_is_excel,
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


def _save_artifact(content: bytes, filename: str) -> str:
    DOCUMENT_DIR.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r'[<>:"/\\|?*]', "_", Path(filename).stem)
    suffix = Path(filename).suffix.lower()
    if suffix not in {".docx", ".xlsx"}:
        raise ValueError("生成文件格式无效")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    saved_name = f"{stem}_{timestamp}{suffix}"
    (DOCUMENT_DIR / saved_name).write_bytes(content)
    return saved_name


def _list_documents() -> list[dict]:
    DOCUMENT_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(
        (
            path
            for path in DOCUMENT_DIR.iterdir()
            if path.is_file() and path.suffix.lower() in {".docx", ".xlsx"}
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
        for path in files[:50]
    ]


@app.get("/api/status")
def status(x_review_token: str | None = Header(default=None)) -> dict:
    _verify_token(x_review_token)
    with KnowledgeStore() as store:
        stats = store.stats()
    return {
        "ok": True,
        "service_version": SERVICE_VERSION,
        "stats": stats,
        "api_key_configured": bool(os.getenv("KIMI_API_KEY", "").strip()),
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


def _generate_excel_artifact(
    api_key: str,
    review_text: str,
    review_date: str,
) -> dict:
    """沿用原 Excel 解析与排版链路，不改变既有工作簿格式。"""
    data = validate_data(parse_with_kimi(api_key, review_text))
    if review_date:
        data["meta"]["date"] = review_date
    content, filename = generate_excel(data)
    saved_filename = _save_artifact(content, filename)
    return {
        "excel_base64": "",
        "excel_filename": saved_filename,
    }


def _generate_word_artifact(
    api_key: str,
    review_text: str,
    sources: list[dict],
    review_date: str,
) -> dict:
    analysis = analyze_with_rag(api_key, review_text, sources)
    document, filename = generate_analysis_docx(
        analysis,
        sources,
        review_date=review_date or date.today().isoformat(),
    )
    saved_filename = _save_artifact(document, filename)
    return {
        "analysis": analysis,
        "sections": parse_analysis_sections(analysis),
        "tasks": parse_task_table(analysis),
        "document_base64": "",
        "document_filename": saved_filename,
    }


def _analysis_result(payload: AnalyzeRequest, progress=None, branch_update=None) -> dict:
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

    is_excel_input = (
        payload.input_is_excel
        or (
            Path(payload.filename).suffix.lower() == ".xlsx"
            and bool(payload.content_base64)
        )
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
        )
    if payload.generate_word:
        runners["word"] = lambda: _generate_word_artifact(
            api_key,
            review_text,
            sources,
            payload.review_date,
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
                branch_result = future.result()
                result.update(branch_result)
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
                progress(
                    f"{labels[name]}{('已完成' if branches[name]['status'] == 'succeeded' else '未完成')}",
                    completed_count + 1,
                    total,
                )

    result["branches"] = branches
    succeeded = [
        name for name, state in branches.items() if state["status"] == "succeeded"
    ]
    if not succeeded and not any(
        state["status"] == "skipped" for state in branches.values()
    ):
        raise RuntimeError("；".join(result["warnings"]) or "本次生成没有成功输出")
    return result


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
    return {"documents": _list_documents()}


@app.get("/api/documents/{filename}")
def download_document(
    filename: str,
    x_review_token: str | None = Header(default=None),
):
    _verify_token(x_review_token)
    safe_name = Path(filename).name
    suffix = Path(safe_name).suffix.lower()
    if safe_name != filename or suffix not in {".docx", ".xlsx"}:
        raise HTTPException(status_code=400, detail="文档名称无效")
    target = DOCUMENT_DIR / safe_name
    if not target.is_file():
        raise HTTPException(status_code=404, detail="没有找到这个历史文档")
    media_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if suffix == ".docx"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return FileResponse(
        path=target,
        filename=safe_name,
        media_type=media_type,
    )


def _run_sync(job_id: str) -> None:
    def progress(message: str, current: int, total: int) -> None:
        with jobs_lock:
            jobs[job_id].update(
                status="running",
                message=message,
                current=current,
                total=total,
            )

    try:
        result = sync_top_year(progress)
        with KnowledgeStore() as store:
            stats = store.stats()
        with jobs_lock:
            jobs[job_id].update(
                status="succeeded",
                message="知识库更新完成",
                result=result,
                stats=stats,
            )
    except Exception as exc:
        with jobs_lock:
            jobs[job_id].update(
                status="failed",
                message=str(exc),
            )


def _run_fetch_review(job_id: str, review_date: str) -> None:
    try:
        with jobs_lock:
            jobs[job_id].update(
                status="running",
                message="正在连接公开复盘页面",
                current=1,
                total=2,
            )
        result = _fetch_review_result(review_date)
        with jobs_lock:
            jobs[job_id].update(
                status="succeeded",
                message="公开复盘正文已载入",
                current=2,
                total=2,
                result=result,
            )
    except Exception as exc:
        with jobs_lock:
            jobs[job_id].update(status="failed", message=str(exc))


def _run_analysis(job_id: str, payload: AnalyzeRequest) -> None:
    def progress(message: str, current: int, total: int) -> None:
        _update_job(
            job_id,
            status="running",
            message=message,
            current=current,
            total=total,
        )

    def branch_update(name: str, state: dict) -> None:
        current = _job_snapshot(job_id) or {}
        branches = dict(current.get("branches") or {})
        branches[name] = dict(state)
        _update_job(job_id, branches=branches)

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
        current = _job_snapshot(job_id) or {}
        _update_job(
            job_id,
            status="succeeded",
            message=message,
            current=current.get("total", 1),
            result=result,
        )
    except Exception as exc:
        _update_job(job_id, status="failed", message=str(exc))


@app.post("/api/fetch-review-async")
def start_fetch_review(
    payload: FetchReviewRequest,
    x_review_token: str | None = Header(default=None),
) -> dict:
    _verify_token(x_review_token)
    job_id = secrets.token_urlsafe(12)
    with jobs_lock:
        jobs[job_id] = {
            "kind": "fetch_review",
            "status": "pending",
            "message": "准备自爬取公开复盘",
            "current": 0,
            "total": 2,
        }
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
    registered_id = _register_job(
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
    previous = _job_snapshot(job_id)
    request_payload = JOB_STORE.get_request(job_id)
    if not previous or not request_payload:
        raise HTTPException(status_code=404, detail="没有找到可重试的生成任务")
    branch_state = (previous.get("branches") or {}).get(payload.branch) or {}
    if branch_state.get("status") != "failed":
        raise HTTPException(status_code=400, detail="只能单独重试失败的生成项")
    request_payload.update(
        api_key=payload.api_key,
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
    return {"jobs": JOB_STORE.recent(limit)}


@app.post("/api/sync")
def start_sync(x_review_token: str | None = Header(default=None)) -> dict:
    _verify_token(x_review_token)
    with jobs_lock:
        running = next(
            (
                job_id
                for job_id, job in jobs.items()
                if job.get("kind") == "sync"
                and job["status"] in {"pending", "running"}
            ),
            None,
        )
        if running:
            return {"job_id": running, "status": jobs[running]["status"]}
        job_id = secrets.token_urlsafe(12)
        jobs[job_id] = {
            "kind": "sync",
            "status": "pending",
            "message": "准备更新知识库",
            "current": 0,
            "total": 1,
        }
    Thread(target=_run_sync, args=(job_id,), daemon=True).start()
    return {"job_id": job_id, "status": "pending"}


@app.get("/api/jobs/{job_id}")
def get_job(
    job_id: str,
    x_review_token: str | None = Header(default=None),
) -> dict:
    _verify_token(x_review_token)
    job = _job_snapshot(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="没有找到这次更新任务")
    return job
