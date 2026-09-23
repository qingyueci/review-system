from copy import deepcopy
from datetime import date
from typing import Any


DEFAULT_DATA: dict[str, Any] = {
    "meta": {"date": "", "author": "", "title": ""},
    "first_boards": [], "first_board_summary": "", "ladders": [],
    "sentiment": {"high_sentiment": [], "mood_tag": "", "mood_score": 0},
    "observation_plan": [], "bidding_analysis": [],
    "temperament_stocks": [], "thinking_questions": [],
}


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def validate_data(raw: Any) -> dict[str, Any]:
    """补全缺失字段，并把异常类型降级为空值。"""
    if not isinstance(raw, dict):
        raise ValueError("模型返回的 JSON 顶层必须是对象")
    data = deepcopy(DEFAULT_DATA)
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    data["meta"] = {key: str(meta.get(key) or "") for key in ("date", "author", "title")}
    data["meta"]["date"] = data["meta"]["date"] or date.today().isoformat()
    for key in ("first_boards", "ladders", "observation_plan", "bidding_analysis", "temperament_stocks", "thinking_questions"):
        data[key] = _list(raw.get(key))
    data["first_board_summary"] = str(raw.get("first_board_summary") or "")
    sentiment = raw.get("sentiment") if isinstance(raw.get("sentiment"), dict) else {}
    try:
        score = max(0, min(10, int(sentiment.get("mood_score") or 0)))
    except (TypeError, ValueError):
        score = 0
    data["sentiment"] = {
        "high_sentiment": _list(sentiment.get("high_sentiment")),
        "mood_tag": str(sentiment.get("mood_tag") or ""),
        "mood_score": score,
    }
    return data
