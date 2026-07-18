import base64
from threading import Event
import time

from fastapi.testclient import TestClient
import pytest

from review_app.api import (
    SERVICE_TOKEN,
    AnalyzeRequest,
    app,
    extract_review_text,
    parse_analysis_sections,
    parse_task_table,
)
from review_app.job_store import JobStore


@pytest.fixture(autouse=True)
def isolate_persisted_jobs(monkeypatch, tmp_path) -> None:
    import review_app.api as api_module

    store = JobStore(tmp_path / "review_jobs.db")
    monkeypatch.setattr(api_module, "JOB_STORE", store)
    monkeypatch.setattr(api_module.JOB_MANAGER, "store", store)
    with api_module.jobs_lock:
        api_module.jobs.clear()


def _structured_review() -> dict:
    return {
        "meta": {
            "date": "2026-07-18",
            "author": "测试作者",
            "title": "每日复盘",
        },
        "first_boards": [
            {
                "sector": "机器人",
                "stocks": ["甲股", "乙股"],
                "first_seal_time": "09:35",
                "analysis_points": ["甲股主动发起"],
                "expectation": "观察承接",
            }
        ],
        "first_board_summary": "首板负责验证新增量",
        "ladders": [],
        "sentiment": {
            "high_sentiment": ["高标分歧"],
            "mood_tag": "分歧",
            "mood_score": 5,
        },
        "observation_plan": [],
        "bidding_analysis": [],
        "temperament_stocks": [],
        "thinking_questions": [],
    }


def test_extract_text_file() -> None:
    payload = AnalyzeRequest(
        filename="复盘.txt",
        content_base64=base64.b64encode("首板出身：主动发酵".encode()).decode(),
    )
    assert extract_review_text(payload) == "首板出身：主动发酵"


def test_parse_analysis_sections() -> None:
    result = parse_analysis_sections("# 今日核心判断\n先看任务\n# 判断失效条件\n失去主动")
    assert result["今日核心判断"] == "先看任务"
    assert result["判断失效条件"] == "失去主动"


def test_parse_task_table() -> None:
    analysis = """## 个股任务表
| 个股 | 首板出身 | 原始任务 | 当前地位 | 协同/压制对象 | 完成信号 | 失败信号 |
|---|---|---|---|---|---|---|
| 甲股 | 主动首板 | 打开空间 | 前排 | 带动乙股 | 主动回封 | 被后排反卡 |
"""
    tasks = parse_task_table(analysis)
    assert tasks[0]["stock"] == "甲股"
    assert tasks[0]["original_task"] == "打开空间"


def test_status_requires_token() -> None:
    client = TestClient(app, base_url="http://127.0.0.1")
    assert client.get("/api/status").status_code == 401
    response = client.get(
        "/api/status",
        headers={"X-Review-Token": SERVICE_TOKEN},
    )
    assert response.status_code == 200
    assert response.json()["service_version"] == "1.3.0"
    assert response.json()["stats"]["chunks"] > 0


def test_full_analysis_and_document_history(monkeypatch, tmp_path) -> None:
    import review_app.api as api_module

    analysis = """# 今日核心判断
先看任务
## 个股任务表
| 个股 | 首板出身 | 原始任务 | 当前地位 | 协同/压制对象 | 完成信号 | 失败信号 |
|---|---|---|---|---|---|---|
| 甲股 | 主动首板 | 打开空间 | 前排 | 带动乙股 | 主动回封 | 被后排反卡 |
# 明日竞价确认条件
竞价保持主动
# 判断失效条件
失去带动性
    """
    monkeypatch.setattr(api_module, "DOCUMENT_DIR", tmp_path)
    monkeypatch.setattr(api_module, "analyze_with_rag", lambda *_args, **_kwargs: analysis)
    monkeypatch.setattr(api_module, "parse_with_kimi", lambda *_args, **_kwargs: _structured_review())
    client = TestClient(app, base_url="http://127.0.0.1")
    headers = {"X-Review-Token": SERVICE_TOKEN}
    response = client.post(
        "/api/analyze",
        headers=headers,
        json={
            "filename": "复盘.txt",
            "text": "首板出身与板块布局",
            "review_date": "2026-07-18",
            "api_key": "test-key",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["tasks"][0]["stock"] == "甲股"
    assert payload["document_filename"].endswith(".docx")
    assert payload["excel_filename"].endswith(".xlsx")
    assert payload["branches"]["word"]["status"] == "succeeded"
    assert payload["branches"]["excel"]["status"] == "succeeded"
    assert all(isinstance(source, dict) for source in payload["sources"])
    history = client.get("/api/documents", headers=headers).json()["documents"]
    assert len(history) == 2
    word_file = next(item for item in history if item["kind"] == "word")
    excel_file = next(item for item in history if item["kind"] == "excel")
    download = client.get(
        f"/api/documents/{word_file['filename']}",
        headers=headers,
    )
    assert download.status_code == 200
    assert download.content.startswith(b"PK")
    excel_download = client.get(
        f"/api/documents/{excel_file['filename']}",
        headers=headers,
    )
    assert excel_download.status_code == 200
    assert excel_download.content.startswith(b"PK")


def _wait_for_job(client: TestClient, headers: dict, job_id: str) -> dict:
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}", headers=headers).json()
        if job["status"] in {"succeeded", "failed"}:
            return job
        time.sleep(0.01)
    raise AssertionError("后台任务没有按时结束")


def test_async_analysis_returns_job_and_result(monkeypatch, tmp_path) -> None:
    import review_app.api as api_module

    analysis = """# 今日核心判断
先看个股任务
## 个股任务表
| 个股 | 首板出身 | 原始任务 | 当前地位 | 协同/压制对象 | 完成信号 | 失败信号 |
|---|---|---|---|---|---|---|
| 甲股 | 主动首板 | 打开空间 | 前排 | 带动乙股 | 主动回封 | 被后排反卡 |
    """
    monkeypatch.setattr(api_module, "DOCUMENT_DIR", tmp_path)
    monkeypatch.setattr(api_module, "analyze_with_rag", lambda *_args, **_kwargs: analysis)
    monkeypatch.setattr(api_module, "parse_with_kimi", lambda *_args, **_kwargs: _structured_review())
    client = TestClient(app, base_url="http://127.0.0.1")
    headers = {"X-Review-Token": SERVICE_TOKEN}

    started = client.post(
        "/api/analyze-async",
        headers=headers,
        json={
            "filename": "复盘.txt",
            "text": "首板出身与板块布局",
            "review_date": "2026-07-18",
            "api_key": "test-key",
        },
    )

    assert started.status_code == 200
    job = _wait_for_job(client, headers, started.json()["job_id"])
    assert job["status"] == "succeeded"
    assert job["result"]["tasks"][0]["stock"] == "甲股"
    assert job["result"]["excel_filename"].endswith(".xlsx")
    assert job["current"] == job["total"] == 3


def test_duplicate_running_analysis_reuses_same_job(monkeypatch) -> None:
    import review_app.api as api_module

    release = Event()

    def hold_job(*_args, **_kwargs) -> None:
        release.wait(timeout=2)

    monkeypatch.setattr(api_module, "_run_analysis", hold_job)
    client = TestClient(app, base_url="http://127.0.0.1")
    headers = {"X-Review-Token": SERVICE_TOKEN}
    request = {
        "filename": "复盘.txt",
        "text": "首板出身与板块布局",
        "review_date": "2026-07-18",
        "api_key": "test-key",
    }

    first = client.post("/api/analyze-async", headers=headers, json=request)
    second = client.post("/api/analyze-async", headers=headers, json=request)
    release.set()

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["job_id"] == first.json()["job_id"]
    assert second.json()["reused"] is True


def test_parallel_generation_keeps_excel_when_word_fails(monkeypatch, tmp_path) -> None:
    import review_app.api as api_module

    monkeypatch.setattr(api_module, "DOCUMENT_DIR", tmp_path)
    monkeypatch.setattr(
        api_module,
        "parse_with_kimi",
        lambda *_args, **_kwargs: _structured_review(),
    )

    def fail_word(*_args, **_kwargs):
        raise RuntimeError("Kimi Code 当前额度不足")

    monkeypatch.setattr(api_module, "analyze_with_rag", fail_word)
    client = TestClient(app, base_url="http://127.0.0.1")
    headers = {"X-Review-Token": SERVICE_TOKEN}

    response = client.post(
        "/api/analyze",
        headers=headers,
        json={
            "filename": "复盘.txt",
            "text": "首板出身与板块布局",
            "review_date": "2026-07-18",
            "api_key": "test-key",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["excel_filename"].endswith(".xlsx")
    assert payload["document_filename"] == ""
    assert payload["branches"]["excel"]["status"] == "succeeded"
    assert payload["branches"]["word"]["status"] == "failed"
    assert "额度不足" in payload["warnings"][0]
    assert len(list(tmp_path.glob("*.xlsx"))) == 1
    assert not list(tmp_path.glob("*.docx"))


def test_generation_job_survives_memory_clear_and_retries_failed_word(
    monkeypatch,
    tmp_path,
) -> None:
    import review_app.api as api_module

    analysis = "# 今日核心判断\n只保留核心任务"
    monkeypatch.setattr(api_module, "DOCUMENT_DIR", tmp_path)
    monkeypatch.setattr(
        api_module,
        "parse_with_kimi",
        lambda *_args, **_kwargs: _structured_review(),
    )
    monkeypatch.setattr(
        api_module,
        "analyze_with_rag",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("Kimi Code 当前额度不足")
        ),
    )
    client = TestClient(app, base_url="http://127.0.0.1")
    headers = {"X-Review-Token": SERVICE_TOKEN}
    started = client.post(
        "/api/analyze-async",
        headers=headers,
        json={
            "filename": "复盘.txt",
            "text": "首板出身与板块布局",
            "review_date": "2026-07-18",
            "api_key": "test-key",
        },
    )
    first_job_id = started.json()["job_id"]
    first_job = _wait_for_job(client, headers, first_job_id)
    assert first_job["branches"]["word"]["status"] == "failed"
    assert first_job["result"]["excel_filename"].endswith(".xlsx")

    with api_module.jobs_lock:
        api_module.jobs.clear()
    restored = client.get(
        f"/api/jobs/{first_job_id}",
        headers=headers,
    )
    assert restored.status_code == 200
    assert restored.json()["result"]["excel_filename"].endswith(".xlsx")

    monkeypatch.setattr(
        api_module,
        "analyze_with_rag",
        lambda *_args, **_kwargs: analysis,
    )
    retried = client.post(
        f"/api/jobs/{first_job_id}/retry",
        headers=headers,
        json={"branch": "word", "api_key": "test-key"},
    )
    assert retried.status_code == 200
    retry_job = _wait_for_job(client, headers, retried.json()["job_id"])
    assert retry_job["result"]["document_filename"].endswith(".docx")
    assert retry_job["branches"]["excel"]["status"] == "skipped"
    assert retry_job["branches"]["word"]["status"] == "succeeded"

    recent = client.get("/api/jobs/recent?limit=2", headers=headers)
    assert recent.status_code == 200
    assert recent.json()["jobs"][0]["job_id"] == retried.json()["job_id"]


def test_async_fetch_review_returns_job(monkeypatch) -> None:
    import review_app.api as api_module

    monkeypatch.setattr(
        api_module,
        "_fetch_review_result",
        lambda review_date: {
            "title": "测试复盘",
            "review_date": review_date,
            "source_url": "https://example.com/review",
            "text": "首板出身决定原始任务",
        },
    )
    client = TestClient(app, base_url="http://127.0.0.1")
    headers = {"X-Review-Token": SERVICE_TOKEN}

    started = client.post(
        "/api/fetch-review-async",
        headers=headers,
        json={"review_date": "2026-07-18"},
    )

    assert started.status_code == 200
    job = _wait_for_job(client, headers, started.json()["job_id"])
    assert job["status"] == "succeeded"
    assert job["result"]["text"] == "首板出身决定原始任务"
