"""Dragon 统一字段字典与已确认的基础硬规则。

字段注册表只描述来源、单位和缺失要求；它不计算评分，也不把公开概念
自动转换成复盘属性。规则模板由路由或一次性初始化脚本显式写入独立运行库。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .schemas import RuleDefinitionInput


@dataclass(frozen=True)
class FieldDefinition:
    name: str
    label: str
    source: str
    value_type: str
    unit: str = ""
    required: bool = False
    derived: bool = False
    description: str = ""


FIELD_REGISTRY: dict[str, FieldDefinition] = {
    "trade_date": FieldDefinition("trade_date", "交易日期", "行情", "date", required=True),
    "stock_code": FieldDefinition("stock_code", "股票代码", "行情", "string", required=True),
    "stock_name": FieldDefinition("stock_name", "股票名称", "行情", "string", required=True),
    "first_seal_time": FieldDefinition("first_seal_time", "首封时间", "行情", "time", required=True),
    "last_seal_time": FieldDefinition("last_seal_time", "最终封板时间", "行情", "time"),
    "break_times": FieldDefinition("break_times", "分钟炸板线索", "分钟行情", "list[time]"),
    "board_break_count": FieldDefinition("board_break_count", "炸板次数", "行情", "integer"),
    "public_late_break": FieldDefinition("public_late_break", "上午首封后第一次炸板发生在13:00后", "分钟行情", "boolean", required=True, derived=True, description="炸板次数达到2次且上午已经首封时，按全天第一次炸板时间是否不早于13:00判断；下午首封后再炸不计入；少于2次通过"),
    "break_suspected": FieldDefinition("break_suspected", "炸板疑似异常", "派生标记", "boolean", derived=True),
    "peak_order_amount": FieldDefinition("peak_order_amount", "峰值封单", "行情", "number", "元"),
    "final_order_amount": FieldDefinition("final_order_amount", "最终封单", "行情", "number", "元", required=True),
    "order_decay": FieldDefinition("order_decay", "封单衰减", "派生", "number", derived=True),
    "order_to_float_market_cap": FieldDefinition("order_to_float_market_cap", "封单额/流通市值", "派生", "number", derived=True),
    "order_to_turnover": FieldDefinition("order_to_turnover", "封单额/成交额", "派生", "number", derived=True),
    "turnover_amount": FieldDefinition("turnover_amount", "成交额", "行情", "number", "元"),
    "turnover_rate": FieldDefinition("turnover_rate", "换手率", "行情", "number", "%"),
    "float_market_cap": FieldDefinition("float_market_cap", "流通市值", "行情", "number", "元", required=True),
    "limit_price": FieldDefinition("limit_price", "涨停价", "行情", "number", "元"),
    "pool_board_count": FieldDefinition("pool_board_count", "公开池连板数", "行情", "integer", required=True),
    "previous_trade_date": FieldDefinition("previous_trade_date", "前一交易日", "行情", "date"),
    "previous_day_limit_up": FieldDefinition("previous_day_limit_up", "前一交易日涨停", "行情", "boolean", required=True),
    "is_confirmed_first_board": FieldDefinition("is_confirmed_first_board", "首板双重确认", "派生", "boolean", required=True, derived=True),
    "is_main_board_10cm_ordinary": FieldDefinition("is_main_board_10cm_ordinary", "主板普通10cm", "派生", "boolean", required=True, derived=True),
    "close_limit_up": FieldDefinition("close_limit_up", "收盘封住涨停", "行情", "boolean", required=True),
    "market_sector": FieldDefinition("market_sector", "公开板块", "行情", "string"),
    "market_concepts": FieldDefinition("market_concepts", "公开概念", "行情", "list[string]"),
    "review_attribute_status": FieldDefinition("review_attribute_status", "复盘属性状态", "刺大复盘原文", "enum", required=True),
    "review_attributes": FieldDefinition("review_attributes", "复盘属性", "刺大复盘原文", "list[string]"),
    "same_attribute_orders": FieldDefinition("same_attribute_orders", "同属性上板顺序", "派生", "map[string,integer]", derived=True),
}


def get_field(name: str) -> FieldDefinition | None:
    return FIELD_REGISTRY.get(str(name).strip())


def public_field_registry() -> list[dict[str, Any]]:
    return [asdict(item) for item in FIELD_REGISTRY.values()]


def default_hard_rule_inputs() -> list[RuleDefinitionInput]:
    """返回用户已确认的 v1 硬规则；调用方负责保存为规则版本。"""

    common = {"hard_condition": True, "missing_policy": "淘汰", "enabled": True}
    return [
        RuleDefinitionInput(name="主板普通10cm", data_field="is_main_board_10cm_ordinary", calculation="沪深主板普通股，排除ST、退市及特殊交易状态", comparison="=", threshold=True, **common),
        RuleDefinitionInput(name="首板双重确认", data_field="is_confirmed_first_board", calculation="公开涨停池连板数=1且前一交易日未涨停", comparison="=", threshold=True, **common),
        RuleDefinitionInput(name="首封时间窗口", data_field="first_seal_time", calculation="首次封板时间落在任一允许窗口；最终回封时间不设窗口", comparison="in_time_windows", threshold=["09:15-10:00", "13:00-13:10"], **common),
        RuleDefinitionInput(name="收盘封住涨停", data_field="close_limit_up", calculation="收盘状态仍封住涨停", comparison="=", threshold=True, **common),
        RuleDefinitionInput(name="最终封单额", data_field="final_order_amount", calculation="收盘最终封单额，单位元", comparison=">", threshold=100_000_000, **common),
        RuleDefinitionInput(name="流通市值", data_field="float_market_cap", calculation="流通市值，单位元", comparison="<", threshold=3_000_000_000, **common),
        RuleDefinitionInput(name="午后首次炸板", data_field="public_late_break", calculation="炸板次数少于2次通过；达到2次且上午已经首封时，全天第一次炸板发生在13:00后才不通过；下午首封后再炸不计入", comparison="=", threshold=False, **common),
    ]


__all__ = ["FIELD_REGISTRY", "FieldDefinition", "default_hard_rule_inputs", "get_field", "public_field_registry"]
