import json
import re
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from .config import API_BASE_URL, API_MAX_RETRIES, API_TIMEOUT_SECONDS, MODEL_NAME
from .model_metrics import capture_model_metrics

SYSTEM_PROMPT = """你是专业的 A 股短线复盘结构化助手。只依据原文提取信息，不得补充、猜测或合并不同板块。输出一个 JSON 对象，禁止 Markdown。
JSON 字段：
{"meta":{"date":"YYYY-MM-DD","author":"","title":""},"first_boards":[{"sector":"","stocks":[""],"first_seal_time":null,"analysis_points":[""],"expectation":""}],"first_board_summary":"","ladders":[{"level":2,"level_name":"二板晋级","stocks":[{"name":"","analysis":""}],"ladder_thought":""}],"sentiment":{"high_sentiment":[""],"mood_tag":"","mood_score":0},"observation_plan":[""],"bidding_analysis":[""],"temperament_stocks":[{"name":"","logic":"","risk":""}],"thinking_questions":[""]}
缺失信息使用空字符串、空数组或 null。不得遗漏原文出现的股票名。无法可靠确定日期时留空。"""


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Kimi Code 未返回可识别的 JSON") from None
        try:
            value = json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"Kimi Code 返回的 JSON 无法解析：第 {exc.lineno} 行第 {exc.colno} 列") from exc
    if not isinstance(value, dict):
        raise ValueError("Kimi Code 返回的 JSON 顶层不是对象")
    return value


def parse_with_kimi(
    api_key: str,
    text: str,
    *,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not api_key.strip():
        raise ValueError("请填写 Kimi Code API Key，或设置 KIMI_API_KEY 环境变量")
    client = OpenAI(
        api_key=api_key.strip(),
        base_url=API_BASE_URL,
        timeout=API_TIMEOUT_SECONDS,
        max_retries=API_MAX_RETRIES,
    )
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": text}],
            # kimi-for-coding 只接受 temperature=1。
            temperature=1.0,
            response_format={"type": "json_object"},
        )
    except APITimeoutError as exc:
        minutes = max(1, round(API_TIMEOUT_SECONDS / 60))
        raise RuntimeError(
            f"Kimi Code 在 {minutes} 分钟内没有返回完整内容，本次任务已停止，请稍后重试"
        ) from exc
    except APIConnectionError as exc:
        raise RuntimeError("无法连接 Kimi Code API，请检查网络或 KIMI_BASE_URL") from exc
    except APIStatusError as exc:
        detail = getattr(exc, "message", str(exc))
        if exc.status_code in {429, 499}:
            raise RuntimeError(
                f"Kimi Code 当前额度不足或服务限流（HTTP {exc.status_code}），请等待额度恢复后重试"
            ) from exc
        if exc.status_code in {401, 403}:
            raise RuntimeError(
                f"Kimi Code 密钥无效或没有模型权限（HTTP {exc.status_code}）"
            ) from exc
        raise RuntimeError(f"Kimi Code API 返回错误（HTTP {exc.status_code}）：{detail}") from exc
    content = response.choices[0].message.content if response.choices else None
    if not content:
        raise RuntimeError("Kimi Code 返回了空内容")
    capture_model_metrics(response, metrics)
    return _extract_json(content)
