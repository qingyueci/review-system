from datetime import date

from review_app.dragon.attributes import (
    apply_review_attributes,
    assign_same_attribute_orders,
    extract_review_attributes,
)
from review_app.dragon.field_registry import FIELD_REGISTRY, default_hard_rule_inputs
from review_app.dragon.market import normalize_market_record


def _candidate(code: str, name: str, first_seal_time: str):
    return normalize_market_record(
        {
            "trade_date": date(2026, 8, 28),
            "stock_code": code,
            "stock_name": name,
            "first_seal_time": first_seal_time,
        }
    )


def test_attribute_statuses_and_exact_aliases():
    candidates = [
        _candidate("000001", "甲", "09:20"),
        _candidate("000002", "乙", "09:20"),
        _candidate("000003", "丙", "09:25"),
        _candidate("000004", "丁", "09:30"),
    ]
    evidence = extract_review_attributes(
        "机器人板块：甲、乙。丙如果走机器人方向，观察为主。",
        candidates,
        alias_map={"机器人": "机器人"},
    )
    found = {item.stock_name: item for item in apply_review_attributes(candidates, evidence)}
    assert found["甲"].review_attribute_status == "明确匹配"
    assert found["甲"].review_attributes == ["机器人"]
    assert found["乙"].review_attribute_status == "明确匹配"
    assert found["丙"].review_attribute_status == "特殊条件"
    assert found["丁"].review_attribute_status == "没有提及"


def test_multiple_attributes_and_competition_rank():
    candidates = [
        _candidate("000001", "甲", "09:20"),
        _candidate("000002", "乙", "09:25"),
        _candidate("000003", "丙", "09:25:00"),
        _candidate("000004", "丁", "09:30"),
    ]
    evidence = extract_review_attributes("机器人板块：甲、乙、丙、丁。新能源板块：甲。", candidates)
    ranked = assign_same_attribute_orders(apply_review_attributes(candidates, evidence))
    by_name = {item.stock_name: item for item in ranked}
    assert by_name["甲"].same_attribute_orders == {"机器人": 1, "新能源": 1}
    assert by_name["乙"].same_attribute_orders["机器人"] == 2
    assert by_name["丙"].same_attribute_orders["机器人"] == 2
    assert by_name["丁"].same_attribute_orders["机器人"] == 4


def test_field_registry_and_default_rules():
    assert {"trade_date", "same_attribute_orders"} <= set(FIELD_REGISTRY)
    rules = default_hard_rule_inputs()
    assert len(rules) == 7
    assert rules[2].comparison == "in_time_windows"
    assert rules[-1].data_field == "public_late_break"
    assert rules[-1].comparison == "="


def test_review_task_table_uses_literal_first_board_origin():
    rows = [_candidate("000001", "甲股", "09:30"), _candidate("000002", "乙股", "09:40")]
    text = "| **甲股** | 国产替代/锗资源（首板） | 原始任务 |\n| `000002` | 算力硬件/PCB | 原始任务 |"
    evidence = extract_review_attributes(text, rows)
    enriched = apply_review_attributes(rows, evidence)
    assert enriched[0].review_attributes == ["国产替代", "锗资源"]
    assert enriched[1].review_attributes == ["算力硬件", "PCB"]


def test_review_task_table_does_not_match_stock_in_other_cells():
    rows = [_candidate("002949", "华阳国际", "09:30")]
    text = "| 其他个股 | 广东线 | 开板后换手承接 | 前排 | 压制华阳国际 | 完成信号 |"
    evidence = extract_review_attributes(text, rows)
    enriched = apply_review_attributes(rows, evidence)
    assert enriched[0].review_attributes == []
    assert enriched[0].review_attribute_status == "特殊条件"


def test_section_attribute_matches_name_without_internal_spaces():
    """行情简称偶发带空格时，仍应匹配复盘中的无空格名称。"""

    rows = [_candidate("002081", "金 螳 螂", "09:30")]
    text = "房地产\n梦天家居，金螳螂，名雕股份"
    enriched = apply_review_attributes(rows, extract_review_attributes(text, rows))
    assert enriched[0].review_attribute_status == "明确匹配"
    assert enriched[0].review_attributes == ["房地产"]


def test_market_normalization_cleans_internal_name_spaces():
    row = normalize_market_record({
        "trade_date": date(2026, 8, 28),
        "stock_code": "002081",
        "stock_name": "金 螳 螂",
        "first_seal_time": "09:30",
    })
    assert row.stock_name == "金螳螂"
