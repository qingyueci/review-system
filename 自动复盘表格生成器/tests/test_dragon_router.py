from __future__ import annotations

import base64
from datetime import date
import json
import re
import time

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from docx import Document

from review_app.dragon.analysis import DragonAnalysisService
from review_app.dragon.knowledge import DragonKnowledgeStore
from review_app.dragon.market import StaticDragonMarketProvider
from review_app.dragon.router import create_dragon_router
from review_app.dragon.store import DragonRuntimeStore


def _client(tmp_path, *, completion=None):
    runtime_path = tmp_path / "dragon_runtime.db"
    knowledge_path = tmp_path / "dragon_knowledge.db"
    trade_date = date(2026, 8, 28)
    provider = StaticDragonMarketProvider(
        [
            {
                "trade_date": trade_date,
                "stock_code": "1",
                "stock_name": "甲股",
                "first_seal_time": "09:50",
            },
            {
                "trade_date": trade_date,
                "stock_code": "2",
                "stock_name": "乙股",
                "first_seal_time": "09:43",
                "sector": "机器人",
                "concepts": ["人形机器人"],
            },
        ]
    )

    def verify(token: str | None) -> None:
        if token != "test-token":
            raise HTTPException(status_code=401, detail="bad token")

    app = FastAPI()
    app.include_router(
        create_dragon_router(
            verify,
            runtime_store_factory=lambda: DragonRuntimeStore(runtime_path),
            knowledge_store_factory=lambda: DragonKnowledgeStore(knowledge_path),
            market_provider_factory=lambda: provider,
            analysis_service_factory=(
                (lambda: DragonAnalysisService(completion)) if completion else None
            ),
            output_dir=tmp_path / "output",
        )
    )
    return TestClient(app), runtime_path, knowledge_path


def _headers():
    return {"X-Review-Token": "test-token"}


def _wait_for_job(client: TestClient, job_id: str) -> dict:
    for _ in range(100):
        payload = client.get(f"/api/dragon/jobs/{job_id}", headers=_headers()).json()
        if payload["status"] in {"succeeded", "failed"}:
            return payload
        time.sleep(0.01)
    raise AssertionError("首板布局后台任务未在预期时间内结束")


def test_dragon_routes_create_only_isolated_databases(tmp_path) -> None:
    client, runtime_path, knowledge_path = _client(tmp_path)

    assert client.get("/api/dragon/status").status_code == 401
    status = client.get("/api/dragon/status", headers=_headers())
    assert status.status_code == 200
    payload = status.json()
    assert payload["knowledge"]["database_name"] == "dragon_knowledge.db"
    assert payload["runtime"]["database_name"] == "dragon_runtime.db"
    assert runtime_path.is_file()
    assert knowledge_path.is_file()
    assert not (tmp_path / "review_knowledge.db").exists()
    assert not (tmp_path / "review_jobs.db").exists()


def test_snapshot_rules_document_search_and_analysis_respect_boundaries(tmp_path) -> None:
    calls: list[str] = []

    def completion(request):
        calls.append(request.user_prompt)
        return {
            "batch_summary": "横向比较后保留乙股为重点",
            "results": [{
                "stock_code": "000002",
                "stock_name": "乙股",
                "basic_pass": True,
                "conclusion": "重点",
                "review_conflict": False,
                "exclusion_reason": "",
                "history_dates": ["2026-01-05—2026-01-09"],
                "analysis": {"判断": "题材内相对主动", "确认": ["次日保持主动性"]},
            }],
        }

    client, runtime_path, knowledge_path = _client(tmp_path, completion=completion)
    headers = _headers()

    snapshot = client.post(
        "/api/dragon/snapshot",
        headers=headers,
        json={
            "trade_date": "2026-08-28",
            "period_stage": "修复初期",
            "market_core": "机器人方向",
            "expectation_point": "前排主动性",
            "effective_directions": "机器人",
            "tomorrow_tasks": "观察首板主动性",
            "failure_conditions": "方向无承接",
            "confirmed": True,
        },
    )
    assert snapshot.status_code == 200
    assert snapshot.json()["snapshot"]["is_confirmed"] is True

    rules = client.post(
        "/api/dragon/rules",
        headers=headers,
        json={
            "name": "首板基础标准 v1",
            "field": "first_seal_time",
            "calculation": "直接采用标准化首封时间字段",
            "comparison": "≤",
            "threshold": "09:45",
            "is_hard": True,
            "missing_behavior": "淘汰",
            "enabled": True,
        },
    )
    assert rules.status_code == 200
    assert rules.json()["rules"][0]["calculation"]

    document = client.post(
        "/api/dragon/documents",
        headers=headers,
        json={
            "filename": "机器人首板案例.md",
            "tags": ["案例", "机器人"],
            "content_base64": base64.b64encode(
                "股票代码：000002\n股票名称：乙股\n模型名称：机器人首板案例\n"
                "起始日期：2026-01-05\n结束日期：2026-01-09\n"
                "历史辨识度：题材内前排主动首板。"
                .encode("utf-8")
            ).decode("ascii"),
        },
    )
    assert document.status_code == 200
    document_id = document.json()["document"]["id"]
    assert document.json()["document"]["chunk_count"] >= 1

    search = client.get("/api/dragon/search?q=000002+乙股", headers=headers)
    assert search.status_code == 200
    assert search.json()["results"][0]["source_id"] == document_id

    started = client.post(
        "/api/dragon/analyze-async",
        headers=headers,
        json={"trade_date": "2026-08-28", "model": "test-model"},
    )
    assert started.status_code == 200
    job = _wait_for_job(client, started.json()["job_id"])
    assert job["status"] == "succeeded"
    candidates = job["result"]["candidates"]
    by_code = {item["stock_code"]: item for item in candidates}
    assert by_code["000001"]["conclusion"] == "排除"
    assert by_code["000001"]["basic_pass"] is False
    assert by_code["000002"]["conclusion"] == "重点"
    assert by_code["000002"]["basic_pass"] is True
    assert by_code["000002"]["evidence_refs"] == []
    assert by_code["000002"]["history_dates"] == ["2026-01-05—2026-01-09"]
    assert by_code["000002"]["analysis"]["判断"] == "题材内相对主动"
    assert len(calls) == 1
    assert '"stock_code": "000002"' in calls[0]
    assert '"stock_name": "乙股"' in calls[0]
    assert "000001 甲股" not in calls[0]

    records = client.get("/api/dragon/analyses?limit=10", headers=headers)
    assert records.status_code == 200
    assert len(records.json()["analyses"]) == 2
    exported = client.post(
        "/api/dragon/analyses/export",
        headers=headers,
        json={"trade_date": "2026-08-28", "job_id": started.json()["job_id"]},
    )
    assert exported.status_code == 200
    exported_path = tmp_path / "output" / exported.json()["filename"]
    assert exported_path.is_file()
    exported_text = "\n".join(
        paragraph.text for paragraph in Document(exported_path).paragraphs
    )
    assert "乙股（000002）· 重点" in exported_text
    assert "题材内相对主动" in exported_text
    assert runtime_path.is_file() and knowledge_path.is_file()
    assert not (tmp_path / "review_knowledge.db").exists()
