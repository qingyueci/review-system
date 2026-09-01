from datetime import date

from review_app.dragon.analysis import DragonAnalysisService
from review_app.dragon.attributes import (
    apply_review_attributes,
    assign_same_attribute_orders,
    extract_review_attributes,
)
from review_app.dragon.field_registry import default_hard_rule_inputs
from review_app.dragon.knowledge import DragonKnowledgeStore
from review_app.dragon.market import StaticDragonMarketProvider, normalize_market_record
from review_app.dragon.pipeline import DragonPipeline
from review_app.dragon.rules import evaluate_rules
from review_app.dragon.schemas import ReviewSnapshotInput
from review_app.dragon.store import DragonRuntimeStore


TRADE_DATE = date(2026, 8, 28)


def candidate(code: str, name: str, first: str, **extra):
    return normalize_market_record({
        "trade_date": TRADE_DATE,
        "stock_code": code,
        "stock_name": name,
        "first_seal_time": first,
        "last_seal_time": "14:30",
        "break_times": [],
        "board_break_count": 0,
        "final_order_amount": 120_000_000,
        "float_market_cap": 2_000_000_000,
        "pool_board_count": 1,
        "previous_day_limit_up": False,
        "is_confirmed_first_board": True,
        "is_main_board_10cm_ordinary": True,
        "close_limit_up": True,
        **extra,
    })


def test_confirmed_rules_boundary_and_late_break_bucket(tmp_path):
    store = DragonRuntimeStore(tmp_path / "dragon_runtime.db")
    version = store.save_rule_version(default_hard_rule_inputs(), name="v1")
    passed = evaluate_rules(candidate("000001", "甲股", "10:00"), version.rules)
    assert passed.basic_pass is True
    assert passed.candidate_bucket == "qualified"

    late = evaluate_rules(
        candidate(
            "000002",
            "乙股",
            "13:10",
            board_break_count=2,
            break_times=["13:05:00", "13:08:00"],
        ),
        version.rules,
    )
    assert late.basic_pass is False
    assert late.candidate_bucket == "late_break_watch"

    too_small = evaluate_rules(
        candidate("000003", "丙股", "09:14", float_market_cap=3_000_000_000), version.rules
    )
    assert too_small.candidate_bucket == "excluded"
    assert [item.status for item in too_small.checks if item.rule_name in {"首封时间窗口", "流通市值"}] == ["不通过", "不通过"]


def test_attributes_are_literal_and_competition_ranked():
    rows = [candidate("000001", "甲股", "09:30"), candidate("000002", "乙股", "09:30"), candidate("000003", "丙股", "09:45")]
    text = "机器人板块：甲股、乙股。若叠加芯片概念，丙股可能受益。"
    evidence = extract_review_attributes(text, rows, alias_map={"机器人": "机器人主线"})
    enriched = assign_same_attribute_orders(apply_review_attributes(rows, evidence))
    assert enriched[0].review_attribute_status == "明确匹配"
    assert enriched[0].review_attributes == ["机器人主线"]
    assert enriched[0].same_attribute_orders == {"机器人主线": 1}
    assert enriched[1].same_attribute_orders == {"机器人主线": 1}
    assert enriched[2].review_attribute_status == "特殊条件"
    assert enriched[2].review_attributes == []


def test_attributes_support_section_heading_stock_list():
    rows = [candidate("601086", "国芳集团", "09:30"), candidate("603016", "新宏泰", "09:31")]
    text = "消费\n国芳集团，国光连锁\n首封时间\n1实际板块一点响应也没有\n\n电网\n新宏泰，风范股份\n首封时间"
    evidence = extract_review_attributes(text, rows, source_url="https://example.com/review")
    enriched = apply_review_attributes(rows, evidence)
    assert enriched[0].review_attribute_status == "明确匹配"
    assert enriched[0].review_attributes == ["消费"]
    assert enriched[0].attribute_evidence[0]["source_url"] == "https://example.com/review"
    assert enriched[1].review_attributes == ["电网"]


def test_inline_attribute_does_not_inherit_long_section_heading():
    rows = [candidate("601086", "国芳集团", "09:30")]
    text = (
        "题材之间的任务关系\n"
        "- **贸易战模型：农业 + 化工 + 外贸 + 消费。** "
        "农业有身位；化工首板多但无身位；消费国芳集团“板块一点响应也没有”。"
    )
    enriched = apply_review_attributes(rows, extract_review_attributes(text, rows))
    assert enriched[0].review_attributes == ["消费"]
    assert enriched[0].attribute_evidence[0]["evidence_text"].startswith("消费国芳集团")


def test_pipeline_persists_attributes_and_only_calls_qualified(tmp_path):
    runtime = DragonRuntimeStore(tmp_path / "dragon_runtime.db")
    runtime.save_rule_version(default_hard_rule_inputs(), name="v1")
    runtime.save_review_snapshot(ReviewSnapshotInput(
        trade_date=TRADE_DATE,
        market_core="机器人主线",
        source_text="机器人板块：甲股。",
        confirm_as_layout=True,
    ))
    provider = StaticDragonMarketProvider([
        candidate("000001", "甲股", "09:30"),
        candidate(
            "000002",
            "乙股",
            "09:40",
            board_break_count=2,
            break_times=["13:05:00", "13:08:00"],
        ),
    ])
    calls = []

    def completion(request):
        calls.append(request.user_prompt)
        return {"conclusion": "重点", "historical_recognition": "未匹配"}

    with DragonKnowledgeStore(tmp_path / "dragon_knowledge.db") as knowledge:
        output = DragonPipeline(
            runtime, knowledge, provider, alias_map={"机器人": "机器人主线"}
        ).prepare(TRADE_DATE)
    assert [item.candidate.stock_code for item in output.qualified] == ["000001"]
    assert [item.candidate.stock_code for item in output.late_break_watch] == ["000002"]
    assert output.contexts[0].screening.candidate.review_attributes == ["机器人主线"]
    assert len(calls) == 0  # prepare 阶段只构建上下文，不调用模型
    assert DragonAnalysisService(completion).analyze(output.contexts[0], model="fixture").conclusion == "重点"
    assert len(calls) == 1
