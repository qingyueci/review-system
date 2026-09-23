from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from review_app.dragon.analysis import (
    DeepSeekCompletionAdapter,
    DragonAnalysisJobRunner,
    DragonAnalysisService,
    DragonCompletionRequest,
)
from review_app.dragon.context import build_analysis_context, context_payload
from review_app.dragon.market import normalize_market_record
from review_app.dragon.rules import evaluate_rules
from review_app.dragon.schemas import (
    DragonEvidence,
    MarketSnapshot,
    ReviewSnapshotInput,
    RuleDefinitionInput,
    RuleVersionCreateRequest,
)
from review_app.dragon.store import DragonRuntimeStore


def _candidate():
    return normalize_market_record(
        {
            "交易日期": "2026-08-29",
            "股票代码": "1",
            "股票名称": "测试股",
            "首封时间": "09:43",
            "峰值封单": "2.00",
            "最终封单": "1.82",
            "成交额": "10",
            "流通市值": "100",
            "炸板次数": "2",
            "概念": "机器人,AI",
        }
    )


def _rule_inputs():
    return [
        RuleDefinitionInput(
            name="首封时间", data_field="first_seal_time", comparison="<=",
            threshold="10:00", hard_condition=True,
        ),
        RuleDefinitionInput(
            name="炸板次数", data_field="board_break_count", comparison="<=",
            threshold=1, hard_condition=True,
        ),
        RuleDefinitionInput(
            name="封单质量", data_field="seal_quality", comparison=">=",
            threshold=1.5, hard_condition=False,
        ),
    ]


def test_market_normalization_and_three_state_hard_gate(tmp_path):
    candidate = _candidate()
    assert candidate.stock_code == "000001"
    assert candidate.order_decay == pytest.approx(0.09)
    assert candidate.order_to_float_market_cap == pytest.approx(0.0182)

    store = DragonRuntimeStore(tmp_path / "dragon_runtime.db")
    version = store.save_rule_version(
        RuleVersionCreateRequest(name="测试规则", rules=_rule_inputs(), activate=True)
    )
    result = evaluate_rules(candidate, version.rules, rule_version_id=version.version_id)

    assert [item.status for item in result.checks] == ["通过", "不通过", "数据缺失"]
    assert result.basic_pass is False
    assert result.disqualifying_rule_ids == [version.rules[1].rule_id]
    assert store.get_active_rule_version().version_id == version.version_id
    with pytest.raises(ValueError, match="dragon_runtime.db"):
        DragonRuntimeStore(tmp_path / "review_knowledge.db")


def test_boolean_string_threshold_matches_boolean_actual(tmp_path):
    store = DragonRuntimeStore(tmp_path / "dragon_runtime.db")
    version = store.save_rule_version(
        [
            RuleDefinitionInput(
                name="收盘封板",
                data_field="close_limit_up",
                comparison="=",
                threshold="true",
                hard_condition=True,
                missing_policy="淘汰",
            )
        ],
        name="布尔字符串阈值",
    )
    candidate = _candidate().model_copy(update={"close_limit_up": True})
    result = evaluate_rules(candidate, version.rules)
    assert result.checks[0].actual_value is True
    assert result.checks[0].status == "通过"
    assert result.basic_pass is True


def test_rule_version_delete_only_allows_inactive_unreferenced(tmp_path):
    store = DragonRuntimeStore(tmp_path / "dragon_runtime.db")
    old = store.save_rule_version(_rule_inputs(), name="旧版本")
    current = store.save_rule_version(_rule_inputs(), name="当前版本")
    store.delete_rule_version(old.version_id)
    assert store.get_rule_version(old.version_id) is None
    with pytest.raises(ValueError, match="当前启用"):
        store.delete_rule_version(current.version_id)


def test_runtime_store_keeps_snapshot_market_screening_and_analysis_history(tmp_path):
    store = DragonRuntimeStore(tmp_path / "dragon_runtime.db")
    candidate = _candidate()
    version = store.save_rule_version(_rule_inputs(), name="测试规则")
    screening = evaluate_rules(candidate, version.rules, rule_version_id=version.version_id)
    snapshot = store.save_review_snapshot(
        ReviewSnapshotInput(
            trade_date=date(2026, 8, 29),
            period_stage="试错期",
            market_core="测试核心",
            confirm_as_layout=True,
        )
    )
    assert store.get_review_snapshot(date(2026, 8, 29), confirmed_only=True) == snapshot

    market = store.save_market_snapshot(
        MarketSnapshot(
            trade_date=date(2026, 8, 29), provider_name="fixture", candidates=[candidate]
        )
    )
    screening_id = store.save_screening_results(market.market_snapshot_id, [screening])
    latest = store.latest_screening_results(date(2026, 8, 29))
    assert latest is not None and latest[0] == screening_id
    assert latest[1][0].candidate.stock_code == candidate.stock_code

    context = build_analysis_context(snapshot=snapshot, screening=screening)
    job = store.create_job(trade_date=date(2026, 8, 29), total=1)
    records = DragonAnalysisJobRunner(store).run(job.job_id, [context], model="fixture")
    assert records[0].result.conclusion == "排除"
    assert store.get_job(job.job_id).status == "succeeded"
    assert store.list_analyses()[0].context.review_snapshot.snapshot_id == snapshot.snapshot_id


def test_confirmed_context_limits_rag_and_accepts_only_real_citations(tmp_path):
    store = DragonRuntimeStore(tmp_path / "dragon_runtime.db")
    candidate = _candidate()
    version = store.save_rule_version(
        [
            RuleDefinitionInput(
                name="首封时间", data_field="first_seal_time", comparison="<=",
                threshold="10:00", hard_condition=True,
            )
        ],
        name="通过规则",
    )
    screening = evaluate_rules(candidate, version.rules, rule_version_id=version.version_id)
    snapshot = store.save_review_snapshot(
        ReviewSnapshotInput(trade_date=date(2026, 8, 29), market_core="用户确认", confirm_as_layout=True)
    )
    evidence = [
        DragonEvidence(source_id="source-1", chunk_id="chunk-1", title="测试案例", content="资料" * 2_000, score=0.8),
        DragonEvidence(source_id="source-2", chunk_id="chunk-2", title="另一个案例", content="资料", score=0.7),
    ]
    context = build_analysis_context(snapshot=snapshot, screening=screening, evidence=evidence)
    payload = context_payload(context)
    assert len(payload["C_历史证据_独立RAG"][0]["content"]) == 2_400

    def fake_completion(_request):
        return {
            "stock_code": "错误代码",
            "stock_name": "错误名称",
            "basic_pass": False,
            "conclusion": "观察",
            "historical_models": ["测试模型"],
            "historical_recognition": "匹配到测试模型",
            "current_review_fit": "符合用户确认结论",
            "layout_task": "观察确认",
            "expectation_point": "超预期",
            "guided_point": "指引",
            "confirmation_conditions": ["确认"],
            "failure_conditions": ["失效"],
            "risks": ["风险"],
            "evidence_refs": ["伪造引用", "chunk-2"],
        }

    result = DragonAnalysisService(fake_completion).analyze(context, model="fixture")
    assert result.stock_code == candidate.stock_code
    assert result.basic_pass is True
    assert result.evidence_refs == ["chunk-2"]


def test_context_keeps_candidate_review_section(tmp_path):
    store = DragonRuntimeStore(tmp_path / "dragon_runtime.db")
    candidate = _candidate()
    version = store.save_rule_version(
        [RuleDefinitionInput(name="首封时间", data_field="first_seal_time", comparison="<=", threshold="10:00", hard_condition=True)],
        name="通过规则",
    )
    screening = evaluate_rules(candidate, version.rules, rule_version_id=version.version_id)
    snapshot = store.save_review_snapshot(ReviewSnapshotInput(
        trade_date=date(2026, 8, 29),
        source_text="——\n消费\n测试股，乙股\n首封时间\n1贸易战模型刺激发酵。\n2实际板块一点响应也没有。\n——\n机器人\n丙股",
        confirm_as_layout=True,
    ))
    context = build_analysis_context(snapshot=snapshot, screening=screening)
    excerpt = context_payload(context)["A_当日复盘_用户确认"]["source_text_evidence"]
    assert "消费" in excerpt
    assert "实际板块一点响应也没有" in excerpt


def test_empty_thinking_response_retries_then_falls_back_without_thinking():
    calls = []
    responses = [None, "  ", '{"conclusion":"观察"}']

    class FakeCompletions:
        def create(self, **options):
            calls.append(options)
            content = responses[len(calls) - 1]
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    result = DeepSeekCompletionAdapter(client)(DragonCompletionRequest(
        system_prompt="system", user_prompt="user", model="fixture", thinking_enabled=True
    ))

    assert result == '{"conclusion":"观察"}'
    assert len(calls) == 3
    assert [call["extra_body"]["thinking"]["type"] for call in calls] == [
        "enabled", "enabled", "disabled",
    ]
    assert "reasoning_effort" in calls[0] and "reasoning_effort" in calls[1]
    assert "reasoning_effort" not in calls[2]
    assert calls[2]["temperature"] == 1.0


def test_single_candidate_failure_does_not_stop_batch(tmp_path):
    store = DragonRuntimeStore(tmp_path / "dragon_runtime.db")
    version = store.save_rule_version(
        [RuleDefinitionInput(
            name="首封时间", data_field="first_seal_time", comparison="<=",
            threshold="10:00", hard_condition=True,
        )],
        name="通过规则",
    )
    snapshot = store.save_review_snapshot(ReviewSnapshotInput(
        trade_date=date(2026, 8, 29), market_core="用户确认", confirm_as_layout=True,
    ))
    first = _candidate()
    second = first.model_copy(update={"stock_code": "000002", "stock_name": "第二股"})
    contexts = [
        build_analysis_context(
            snapshot=snapshot,
            screening=evaluate_rules(item, version.rules, rule_version_id=version.version_id),
        )
        for item in (first, second)
    ]

    def completion(request):
        if "000001" in request.user_prompt:
            raise RuntimeError("fixture empty")
        return {
            "conclusion": "观察", "historical_models": [],
            "historical_recognition": "辨识度不足", "current_review_fit": "观察",
            "layout_task": "等待", "expectation_point": "", "guided_point": "",
            "confirmation_conditions": [], "failure_conditions": [], "risks": [],
            "evidence_refs": [],
        }

    job = store.create_job(trade_date=date(2026, 8, 29), total=2)
    records = DragonAnalysisJobRunner(store, DragonAnalysisService(completion)).run(
        job.job_id, contexts, model="fixture",
        result_builder=lambda completed: {"count": len(completed)},
    )

    saved_job = store.get_job(job.job_id)
    assert [record.stock_code for record in records] == ["000002"]
    assert saved_job.status == "succeeded"
    assert saved_job.current == 2
    assert saved_job.result["count"] == 1
    assert saved_job.result["errors"][0]["stock_code"] == "000001"
