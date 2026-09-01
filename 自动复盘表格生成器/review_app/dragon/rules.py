"""用户定义的首板基础标准三态检查引擎。"""

from __future__ import annotations

from datetime import datetime, time
import math
import re
from typing import Any, Mapping, Sequence

from .schemas import (
    CandidateMetrics,
    CandidateScreeningResult,
    RuleCheckResult,
    RuleDefinition,
)


_TIME_PATTERN = re.compile(r"^(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$")
_NUMBER_PATTERN = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)%?$")


def is_missing(value: Any) -> bool:
    """判断数据是否缺失，0、False 和空列表均是可用的客观值。"""

    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, float):
        return math.isnan(value)
    return False


def _as_mapping(candidate: CandidateMetrics | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(candidate, CandidateMetrics):
        return candidate.model_dump(mode="python")
    return candidate


def get_candidate_field(
    candidate: CandidateMetrics | Mapping[str, Any], data_field: str
) -> Any:
    """读取标准字段或来源适配器保留在 ``raw_fields`` 中的字段。

    支持 ``raw_fields.字段名`` 与普通点路径。规则配置仍由用户确定，本函数不
    推断字段含义或创建任何评分。
    """

    values: Any = _as_mapping(candidate)
    path = [part for part in data_field.strip().split(".") if part]
    if not path:
        return None

    for part in path:
        if isinstance(values, Mapping) and part in values:
            values = values[part]
        else:
            values = None
            break
    if values is not None:
        return values

    # 允许规则直接指向行情适配器的原字段，例如 ``封单质量``。
    root = _as_mapping(candidate)
    raw_fields = root.get("raw_fields") if isinstance(root, Mapping) else None
    if isinstance(raw_fields, Mapping):
        if data_field in raw_fields:
            return raw_fields[data_field]
        nested: Any = raw_fields
        for part in path:
            if isinstance(nested, Mapping) and part in nested:
                nested = nested[part]
            else:
                nested = None
                break
        return nested
    return None


def _as_time(value: Any) -> int | None:
    if isinstance(value, time):
        return value.hour * 3600 + value.minute * 60 + value.second
    if isinstance(value, datetime):
        value = value.time()
        return value.hour * 3600 + value.minute * 60 + value.second
    text = str(value).strip()
    if not _TIME_PATTERN.fullmatch(text):
        return None
    parts = [int(part) for part in text.split(":")]
    return parts[0] * 3600 + parts[1] * 60 + (parts[2] if len(parts) == 3 else 0)


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    text = str(value).strip().replace(",", "")
    if not _NUMBER_PATTERN.fullmatch(text):
        return None
    try:
        return float(text.rstrip("%"))
    except ValueError:
        return None


def _normalise_scalar(value: Any) -> Any:
    """让时间、数字和普通文本按照可解释的同类方式比较。"""

    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, str) and value.strip().casefold() in {"true", "false"}:
        return ("boolean", value.strip().casefold() == "true")
    time_value = _as_time(value)
    if time_value is not None:
        return ("time", time_value)
    number_value = _as_number(value)
    if number_value is not None:
        return ("number", number_value)
    if isinstance(value, str):
        return ("text", value.strip().casefold())
    return ("other", value)


def _iter_values(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if isinstance(value, str) and "," in value:
        return [item.strip() for item in value.split(",") if item.strip()]
    return [value]


def _time_windows(threshold: Any) -> list[tuple[int, int]]:
    """解析 ``09:15-10:00`` 形式的时间窗口。"""

    values = _iter_values(threshold)
    windows: list[tuple[int, int]] = []
    for item in values:
        text = str(item).strip().replace("—", "-").replace("至", "-")
        left, separator, right = text.partition("-")
        if not separator:
            continue
        start, end = _as_time(left.strip()), _as_time(right.strip())
        if start is not None and end is not None:
            windows.append((start, end))
    return windows


def _has_time_at_or_after(value: Any, threshold: Any) -> bool | None:
    if value is None:
        return None
    limit = _as_time(threshold)
    if limit is None:
        return None
    values = _iter_values(value)
    parsed: list[int] = []
    for item in values:
        parsed_value = _as_time(item)
        if parsed_value is None:
            return None
        parsed.append(parsed_value)
    return any(item >= limit for item in parsed)


def _compare(actual: Any, comparison: str, threshold: Any) -> bool:
    if comparison == "exists":
        return not is_missing(actual)
    if comparison == "not_exists":
        return is_missing(actual)

    if comparison in {"in", "not_in"}:
        expected = {_normalise_scalar(item) for item in _iter_values(threshold)}
        actual_values = {_normalise_scalar(item) for item in _iter_values(actual)}
        contained = bool(actual_values & expected)
        return contained if comparison == "in" else not contained

    if comparison == "in_time_windows":
        actual_time = _as_time(actual)
        windows = _time_windows(threshold)
        return actual_time is not None and any(start <= actual_time <= end for start, end in windows)

    if comparison == "none_at_or_after":
        has_late = _has_time_at_or_after(actual, threshold)
        return has_late is False

    normal_actual = _normalise_scalar(actual)
    normal_threshold = _normalise_scalar(threshold)
    if normal_actual[0] == normal_threshold[0] and normal_actual[0] in {"boolean", "time", "number", "text"}:
        left, right = normal_actual[1], normal_threshold[1]
    else:
        # 字段与阈值类型不一致时按文本精确比较；数值范围操作则直接视为未通过。
        if comparison in {"<", "<=", ">", ">="}:
            return False
        left, right = str(actual).strip(), str(threshold).strip()

    if comparison == "<":
        return left < right
    if comparison == "<=":
        return left <= right
    if comparison == ">":
        return left > right
    if comparison == ">=":
        return left >= right
    if comparison == "=":
        return left == right
    if comparison == "!=":
        return left != right
    raise ValueError(f"不支持的规则比较方式：{comparison}")


def _message(status: str, rule: RuleDefinition, actual: Any) -> str:
    if status == "数据缺失":
        suffix = "淘汰" if rule.missing_policy == "淘汰" else "保留"
        return f"{rule.data_field} 数据缺失，按规则设置：{suffix}"
    return (
        f"实际 {actual!s}；标准 {rule.comparison} {rule.threshold!s}；{status}"
    )


def evaluate_rule(
    candidate: CandidateMetrics | Mapping[str, Any], rule: RuleDefinition
) -> RuleCheckResult:
    """执行一条规则并返回固定的通过/不通过/数据缺失三态结果。"""

    actual = get_candidate_field(candidate, rule.data_field)
    requires_threshold = rule.comparison not in {"exists", "not_exists"}
    missing = is_missing(actual) or (requires_threshold and is_missing(rule.threshold))
    if not missing and rule.comparison in {"in_time_windows", "none_at_or_after"}:
        # 结构化时间字段解析失败属于数据缺失，而非普通不通过。
        if rule.comparison == "in_time_windows":
            missing = _as_time(actual) is None or not _time_windows(rule.threshold)
        else:
            missing = _has_time_at_or_after(actual, rule.threshold) is None
    if missing:
        status = "数据缺失"
        disqualifying = rule.hard_condition and rule.missing_policy == "淘汰"
    else:
        passed = _compare(actual, rule.comparison, rule.threshold)
        status = "通过" if passed else "不通过"
        disqualifying = rule.hard_condition and not passed
    return RuleCheckResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        data_field=rule.data_field,
        actual_value=actual,
        comparison=rule.comparison,
        threshold=rule.threshold,
        status=status,
        hard_condition=rule.hard_condition,
        missing_policy=rule.missing_policy,
        is_disqualifying=disqualifying,
        message=_message(status, rule, actual),
    )


def evaluate_rules(
    candidate: CandidateMetrics | Mapping[str, Any],
    rules: Sequence[RuleDefinition],
    *,
    rule_version_id: str = "",
) -> CandidateScreeningResult:
    """执行启用规则；只有硬性条件失败才排除候选，绝不生成综合分。"""

    candidate_model = (
        candidate
        if isinstance(candidate, CandidateMetrics)
        else CandidateMetrics.model_validate(candidate)
    )
    active_rules = sorted(
        (rule for rule in rules if rule.enabled),
        key=lambda item: (item.position, item.rule_id),
    )
    checks = [evaluate_rule(candidate_model, rule) for rule in active_rules]
    disqualifying = [check.rule_id for check in checks if check.is_disqualifying]
    late_break_checks = [
        check for check in checks
        if check.is_disqualifying
        and check.status == "不通过"
        and (
            check.data_field in {"break_times", "late_break_times", "public_late_break"}
            or "午后炸板" in check.rule_name
            or "13:00" in check.rule_name
        )
    ]
    candidate_bucket = "qualified"
    if disqualifying:
        # 午后炸板是独立观察清单：即使同时触发封单/市值等其他硬失败，
        # 仍保留在 late_break_watch；basic_pass 始终为 False，模型仍会跳过。
        candidate_bucket = "late_break_watch" if late_break_checks else "excluded"
    return CandidateScreeningResult(
        candidate=candidate_model,
        rule_version_id=rule_version_id or (active_rules[0].version_id if active_rules else ""),
        checks=checks,
        basic_pass=not disqualifying,
        candidate_bucket=candidate_bucket,
        disqualifying_rule_ids=disqualifying,
        evaluated_at=datetime.now(),
    )


class DragonRuleEngine:
    """给路由/后台任务使用的无状态规则服务。"""

    def evaluate(
        self,
        candidate: CandidateMetrics | Mapping[str, Any],
        rules: Sequence[RuleDefinition],
        *,
        rule_version_id: str = "",
    ) -> CandidateScreeningResult:
        return evaluate_rules(candidate, rules, rule_version_id=rule_version_id)
