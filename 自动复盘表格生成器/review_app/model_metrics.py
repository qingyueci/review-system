from __future__ import annotations

from typing import Any


def capture_model_metrics(response: Any, metrics: dict[str, Any] | None) -> None:
    """记录模型返回的可用用量；供应商不返回时明确标记未知。"""
    if metrics is None:
        return
    usage = getattr(response, "usage", None)
    values = {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }
    metrics["model"] = getattr(response, "model", "") or ""
    metrics["usage"] = {
        "available": any(value is not None for value in values.values()),
        **{key: value for key, value in values.items() if value is not None},
    }
