"""首板行情数据提供方抽象和字段标准化。

当前阶段不绑定任何外部行情服务。接入 API 或每日 CSV/XLSX 时，只需实现
``DragonMarketProvider``，规则与历史模型检索无需改动。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
import math
import re
from typing import Any, Iterable, Mapping

import httpx

from .schemas import CandidateMetrics


class MarketProviderNotConfiguredError(RuntimeError):
    """调用方尚未接入用户提供的行情数据源。"""


class DragonMarketProvider(ABC):
    """首板行情来源的稳定接口。"""

    provider_name = "unknown"

    @abstractmethod
    def fetch_first_board_candidates(self, trade_date: date) -> list[CandidateMetrics]:
        """返回指定交易日的首板候选，且必须完成字段标准化。"""

    @abstractmethod
    def fetch_candidate_metrics(
        self, stock_code: str, trade_date: date
    ) -> CandidateMetrics:
        """返回单只候选的完整标准字段。"""


class UnconfiguredDragonMarketProvider(DragonMarketProvider):
    """默认 Provider，显式阻止在没有数据源时伪造行情数据。"""

    provider_name = "unconfigured"

    def _raise(self) -> None:
        raise MarketProviderNotConfiguredError(
            "尚未配置首板行情数据源；请先提供行情 API 文档和示例响应，或每日 CSV/XLSX 样例"
        )

    def fetch_first_board_candidates(self, trade_date: date) -> list[CandidateMetrics]:
        self._raise()

    def fetch_candidate_metrics(
        self, stock_code: str, trade_date: date
    ) -> CandidateMetrics:
        self._raise()


class StaticDragonMarketProvider(DragonMarketProvider):
    """仅用于本地测试和导入样例，不产生网络请求。"""

    provider_name = "static"

    def __init__(self, records: Iterable[CandidateMetrics | Mapping[str, Any]]) -> None:
        normalized = [normalize_candidate_metrics(item) for item in records]
        self._by_date: dict[date, dict[str, CandidateMetrics]] = {}
        for candidate in normalized:
            self._by_date.setdefault(candidate.trade_date, {})[candidate.stock_code] = candidate

    def fetch_first_board_candidates(self, trade_date: date) -> list[CandidateMetrics]:
        return list(self._by_date.get(trade_date, {}).values())

    def fetch_candidate_metrics(
        self, stock_code: str, trade_date: date
    ) -> CandidateMetrics:
        try:
            return self._by_date[trade_date][str(stock_code).zfill(6)]
        except KeyError as exc:
            raise KeyError(f"{trade_date} 没有 {stock_code} 的首板标准字段") from exc


class EastmoneyDragonMarketProvider(DragonMarketProvider):
    """盘后使用东方财富公开接口的首板 Provider。

    涨停池给出首封、最终封板、公开炸板次数、封单、流通市值等字段。硬规则
    只使用公开炸板次数和最终封板时间；腾讯/东方财富分钟 OHLC 仅作为疑似异常
    标记，不覆盖公开炸板口径。
    """

    provider_name = "eastmoney_public"
    _pool_endpoint = "https://push2ex.eastmoney.com/getTopicZTPool"
    _trend_endpoint = "https://push2his.eastmoney.com/api/qt/stock/trends2/get"
    _tencent_kline_endpoint = "https://ifzq.gtimg.cn/appstock/app/kline/mkline"
    _ut = "7eea3edcaed734bea9cbfc24409ed989"

    def __init__(self, *, timeout: float = 20.0, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (DragonReview/1.0)", "Referer": "https://quote.eastmoney.com/"},
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "EastmoneyDragonMarketProvider":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _get_json(self, endpoint: str, params: Mapping[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self._client.get(endpoint, params=params)
                response.raise_for_status()
                payload = response.json()
                break
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                # 东方财富偶尔主动断开长连接；使用一次性连接重试，避免把本次
                # 盘后任务直接降级为全部“数据缺失”。
                if attempt == 0:
                    try:
                        # requests 在部分 Windows 网络栈上比复用的 httpx 长连接
                        # 更稳定；它是可选回退，不影响测试注入的 httpx Client。
                        import requests  # type: ignore
                        response = requests.get(
                            endpoint, params=params, timeout=20.0,
                            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
                        )
                        response.raise_for_status()
                        payload = response.json()
                        break
                    except Exception as fallback_exc:
                        # requests 的异常类型不作为硬依赖暴露，统一进入下一轮。
                        last_error = fallback_exc
                if attempt == 2:
                    raise RuntimeError(f"公开行情接口请求失败：{endpoint}") from exc
        else:  # pragma: no cover
            raise RuntimeError(f"公开行情接口请求失败：{endpoint}") from last_error
        if not isinstance(payload, dict):
            raise RuntimeError("公开行情接口返回格式不是对象")
        return payload

    def _pool(self, trade_date: date) -> list[dict[str, Any]]:
        payload = self._get_json(
            self._pool_endpoint,
            {
                "ut": self._ut, "dpt": "wz.ztzt", "Pageindex": 0,
                "pagesize": 10000, "sort": "fbt:asc", "date": trade_date.strftime("%Y%m%d"),
            },
        )
        rows = ((payload.get("data") or {}).get("pool") or [])
        return [dict(row) for row in rows if isinstance(row, Mapping)]

    @staticmethod
    def _is_main_board_10cm(code: str, name: str) -> bool:
        code = str(code).zfill(6)
        # 沪深主板普通10cm：排除创业板、科创板、北交所及名称特殊状态。
        main = code.startswith(("000", "001", "002", "003", "600", "601", "603", "605"))
        upper_name = str(name).strip().upper()
        special = (
            any(token in upper_name for token in ("ST", "*ST", "退"))
            or upper_name.startswith(("N", "C", "U"))
        )
        return main and not special

    @staticmethod
    def _format_hhmmss(value: Any) -> str | None:
        number = _to_int(value)
        if number is None:
            return None
        text = f"{number:06d}"
        return f"{text[:2]}:{text[2:4]}:{text[4:]}"

    def _previous_trade_date(self, trade_date: date) -> date | None:
        # 公开池按日查询；向前找最近一个有数据的交易日，最多回溯两周覆盖节假日。
        for offset in range(1, 15):
            previous = trade_date - timedelta(days=offset)
            if self._pool(previous):
                return previous
        return None

    @staticmethod
    def _clock_from_stamp(value: Any) -> str | None:
        """兼容 ``YYYY-MM-DD HH:MM[:SS]`` 与 ``YYYYMMDDHHMM[SS]``。"""

        text = str(value or "").strip()
        separated = re.search(r"(?:\s|T)(\d{2}):(\d{2})(?::(\d{2}))?$", text)
        if separated:
            hour, minute, second = separated.group(1), separated.group(2), separated.group(3) or "00"
            return f"{hour}:{minute}:{second}"
        if re.fullmatch(r"\d{12}(?:\d{2})?", text):
            clock = text[8:]
            return f"{clock[:2]}:{clock[2:4]}:{clock[4:6] if len(clock) >= 6 else '00'}"
        return _normalise_time(text)

    @staticmethod
    def _clock_seconds(value: str | None) -> int | None:
        normalized = _normalise_time(value)
        if normalized is None or not re.fullmatch(r"\d{2}:\d{2}:\d{2}", normalized):
            return None
        hour, minute, second = (int(part) for part in normalized.split(":"))
        return hour * 3600 + minute * 60 + second

    def _detect_break_times(
        self,
        rows: Iterable[tuple[str, float, float, float, float]],
        *,
        limit_price: float,
        first_seal_time: str | None,
    ) -> list[str]:
        """从分钟 OHLC 识别封板后的首次离板分钟，每次离板只记录一次。"""

        tolerance = max(0.01, limit_price * 0.0005)
        first_seal_seconds = self._clock_seconds(first_seal_time)
        had_seal = False
        in_break = False
        breaks: list[str] = []
        for stamp, open_price, close, high, low in rows:
            clock = self._clock_from_stamp(stamp)
            clock_seconds = self._clock_seconds(clock)
            if clock is None or clock_seconds is None:
                continue
            # 首封发生分钟内的高低价先后顺序未知；从下一分钟开始可确定此前已封。
            if first_seal_seconds is not None and clock_seconds > first_seal_seconds:
                had_seal = True
            open_at_limit = abs(open_price - limit_price) <= tolerance
            close_at_limit = abs(close - limit_price) <= tolerance
            touched_limit = high >= limit_price - tolerance
            sealed_before_move = had_seal or open_at_limit
            if sealed_before_move and low < limit_price - tolerance and not in_break:
                breaks.append(clock)
                in_break = True
            if touched_limit:
                had_seal = True
            if close_at_limit:
                in_break = False
            elif open_at_limit and low < limit_price - tolerance:
                in_break = True
        return list(dict.fromkeys(breaks))

    def _tencent_break_times(
        self,
        code: str,
        trade_date: date,
        limit_price: float,
        first_seal_time: str | None,
    ) -> tuple[list[str] | None, str]:
        symbol = ("sh" if str(code).zfill(6).startswith("6") else "sz") + str(code).zfill(6)
        payload = self._get_json(
            self._tencent_kline_endpoint,
            {"param": f"{symbol},m1,,640"},
        )
        node = ((payload.get("data") or {}).get(symbol) or {})
        raw_rows = node.get("m1") or []
        target = trade_date.strftime("%Y%m%d")
        parsed: list[tuple[str, float, float, float, float]] = []
        for row in raw_rows:
            if not isinstance(row, (list, tuple)) or len(row) < 5:
                continue
            stamp = str(row[0]).strip()
            if not stamp.startswith(target):
                continue
            try:
                parsed.append((stamp, float(row[1]), float(row[2]), float(row[3]), float(row[4])))
            except (TypeError, ValueError):
                continue
        if not parsed:
            return None, ""
        return self._detect_break_times(
            parsed,
            limit_price=limit_price,
            first_seal_time=first_seal_time,
        ), "1m:tencent_ohlc"

    def _eastmoney_break_times(
        self,
        code: str,
        trade_date: date,
        limit_price: float,
        first_seal_time: str | None,
    ) -> tuple[list[str] | None, str]:
        if limit_price is None:
            return None, ""
        market = "1" if str(code).zfill(6).startswith("6") else "0"
        payload = self._get_json(
            self._trend_endpoint,
            {
                "ut": self._ut, "fields1": "f1,f2,f3",
                "fields2": "f51,f52,f53,f54,f55", "ndays": 1, "iscr": 0,
                "secid": f"{market}.{str(code).zfill(6)}",
            },
        )
        rows = ((payload.get("data") or {}).get("trends") or [])
        if not rows:
            return None, ""
        target = trade_date.isoformat()
        parsed: list[tuple[str, float, float, float, float]] = []
        for row in rows:
            parts = str(row).split(",") if isinstance(row, str) else list(row)
            if len(parts) < 5:
                continue
            stamp = str(parts[0]).strip()
            if not stamp.startswith(target):
                continue
            try:
                open_price, close, high, low = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
            except (TypeError, ValueError):
                continue
            parsed.append((stamp, open_price, close, high, low))
        if not parsed:
            return None, ""
        return self._detect_break_times(
            parsed,
            limit_price=limit_price,
            first_seal_time=first_seal_time,
        ), "1m:eastmoney_ohlc"

    def _trend_break_times(
        self,
        code: str,
        trade_date: date,
        limit_price: float | None,
        first_seal_time: str | None = None,
    ) -> tuple[list[str] | None, str]:
        if limit_price is None:
            return None, ""
        for loader in (self._tencent_break_times, self._eastmoney_break_times):
            try:
                breaks, granularity = loader(code, trade_date, limit_price, first_seal_time)
            except (httpx.HTTPError, RuntimeError, ValueError):
                continue
            if breaks is not None:
                return breaks, granularity
        return None, ""

    def fetch_first_board_candidates(self, trade_date: date) -> list[CandidateMetrics]:
        pool = self._pool(trade_date)
        previous_date = self._previous_trade_date(trade_date)
        previous_codes = {str(row.get("c") or "").zfill(6) for row in self._pool(previous_date)} if previous_date else set()
        candidates: list[CandidateMetrics] = []
        for row in pool:
            code = str(row.get("c") or "").zfill(6)
            name = str(row.get("n") or "").strip()
            if not self._is_main_board_10cm(code, name):
                continue
            pool_count = _to_int(row.get("lbc"))
            # 公开池中的连板股不属于本次首板布局候选；缺失连板数的记录保留，
            # 由首板双重确认硬规则输出“数据缺失”。
            if pool_count not in (None, 1):
                continue
            previous_limit = code in previous_codes if previous_date else None
            confirmed = None if pool_count is None or previous_limit is None else (pool_count == 1 and not previous_limit)
            limit_price = (_to_float(row.get("p")) or 0.0) / 1000 if row.get("p") is not None else None
            first_seal_time = self._format_hhmmss(row.get("fbt"))
            board_break_count = _to_int(row.get("zbc"))
            try:
                breaks, granularity = self._trend_break_times(
                    code, trade_date, limit_price, first_seal_time,
                )
            except (httpx.HTTPError, RuntimeError, ValueError):
                breaks, granularity = None, ""
            last_seal_time = self._format_hhmmss(row.get("lbt"))
            public_late_break = _derive_public_late_break(
                board_break_count,
                break_times=breaks,
            )
            suspicion_reasons: list[str] = []
            if (
                board_break_count is not None
                and board_break_count >= 2
                and (breaks is None or len(breaks) != board_break_count)
            ):
                suspicion_reasons.append(
                    "公开炸板次数达到2次，但分钟行情未完整还原全部炸板时间"
                )
            break_data_complete = (
                breaks is not None
                and board_break_count is not None
                and len(breaks) == board_break_count
            )
            raw = dict(row)
            raw.update({
                "provider": self.provider_name,
                "previous_trade_date": previous_date.isoformat() if previous_date else None,
                "break_event_source": granularity,
                "break_data_complete": break_data_complete,
                "break_suspected": bool(suspicion_reasons),
                "break_suspicion_reasons": suspicion_reasons,
            })
            candidates.append(normalize_market_record({
                "trade_date": trade_date,
                "stock_code": code,
                "stock_name": name,
                "first_seal_time": first_seal_time,
                "last_seal_time": last_seal_time,
                "break_times": breaks,
                "board_break_count": board_break_count,
                "public_late_break": public_late_break,
                "break_suspected": bool(suspicion_reasons),
                "break_suspicion_reasons": suspicion_reasons,
                "peak_order_amount": row.get("fund"),
                "final_order_amount": row.get("fund"),
                "turnover_amount": row.get("amount"),
                "turnover_rate": row.get("hs"),
                "float_market_cap": row.get("ltsz"),
                "limit_price": limit_price,
                "pool_board_count": pool_count,
                "previous_trade_date": previous_date,
                "previous_day_limit_up": previous_limit,
                "is_confirmed_first_board": confirmed,
                "is_main_board_10cm_ordinary": True,
                "close_limit_up": True,
                "sector": row.get("hybk") or "",
                "raw_fields": raw,
                "break_time_granularity": granularity,
                "data_source": self.provider_name,
            }, trade_date=trade_date))
        return candidates

    def fetch_candidate_metrics(self, stock_code: str, trade_date: date) -> CandidateMetrics:
        for candidate in self.fetch_first_board_candidates(trade_date):
            if candidate.stock_code == str(stock_code).zfill(6):
                return candidate
        raise KeyError(f"{trade_date} 没有 {stock_code} 的首板标准字段")


_ALIASES: dict[str, tuple[str, ...]] = {
    "trade_date": ("trade_date", "交易日期", "日期", "date"),
    "stock_code": ("stock_code", "股票代码", "证券代码", "代码", "code", "symbol"),
    "stock_name": ("stock_name", "股票名称", "证券简称", "名称", "name"),
    "first_seal_time": ("first_seal_time", "首封时间", "首次封板时间", "首次涨停时间"),
    "last_seal_time": ("last_seal_time", "最后封板时间", "最终封板时间", "最后涨停时间"),
    "board_break_count": ("board_break_count", "炸板次数", "开板次数"),
    "public_late_break": ("public_late_break", "公开口径13:00后炸板", "公开午后炸板"),
    "break_suspected": ("break_suspected", "炸板疑似异常", "炸板嫌疑"),
    "break_suspicion_reasons": ("break_suspicion_reasons", "炸板疑似原因"),
    "peak_order_amount": ("peak_order_amount", "峰值封单", "最大封单", "最高封单额"),
    "final_order_amount": ("final_order_amount", "最终封单", "收盘封单", "最终封单额"),
    "order_decay": ("order_decay", "封单衰减", "封单衰减率"),
    "order_to_float_market_cap": (
        "order_to_float_market_cap", "封单额/流通市值", "封单流通市值比",
    ),
    "order_to_turnover": ("order_to_turnover", "封单额/成交额", "封单成交额比"),
    "turnover_amount": ("turnover_amount", "成交额", "amount"),
    "turnover_rate": ("turnover_rate", "换手率", "turnover"),
    "float_market_cap": ("float_market_cap", "流通市值", "流通值"),
    "sector": ("sector", "板块", "所属板块", "industry"),
    "concepts": ("concepts", "概念", "概念题材", "题材", "themes"),
    "same_attribute_board_order": (
        "same_attribute_board_order", "同属性上板顺序", "同题材上板顺序", "板块上板顺序",
    ),
    "break_times": ("break_times", "炸板时间线", "炸板时间", "break_time_list"),
    "break_time_granularity": ("break_time_granularity", "炸板时间粒度"),
    "limit_price": ("limit_price", "涨停价"),
    "pool_board_count": ("pool_board_count", "连板数", "公开池连板数"),
    "previous_trade_date": ("previous_trade_date", "前一交易日"),
    "previous_day_limit_up": ("previous_day_limit_up", "前一交易日涨停"),
    "is_confirmed_first_board": ("is_confirmed_first_board", "首板双重确认", "是否首板"),
    "is_main_board_10cm_ordinary": ("is_main_board_10cm_ordinary", "主板普通10cm"),
    "close_limit_up": ("close_limit_up", "收盘封住涨停", "收盘状态"),
    "market_sector": ("market_sector", "公开板块"),
    "market_concepts": ("market_concepts", "公开概念"),
    "data_source": ("data_source", "数据来源"),
}


def _lookup(record: Mapping[str, Any], field: str) -> Any:
    for name in _ALIASES[field]:
        if name in record and record[name] not in (None, ""):
            return record[name]
    # 英文字段大小写不一致时也能读取，但不改写原始数据。
    lower_names = {str(key).casefold(): key for key in record}
    for name in _ALIASES[field]:
        key = lower_names.get(name.casefold())
        if key is not None and record[key] not in (None, ""):
            return record[key]
    return None


def _to_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        raise ValueError("行情记录缺少交易日期")
    text = str(value).strip().replace("/", "-")
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ValueError(f"无法识别交易日期：{value!s}") from exc


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return None if math.isnan(number) else number
    text = str(value).strip().replace(",", "")
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value: Any) -> int | None:
    number = _to_float(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _normalise_time(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.strftime("%H:%M:%S")
    text = str(value).strip()
    if re.fullmatch(r"\d{3,4}", text):
        text = f"{text[:-2]}:{text[-2:]}"
    match = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", text)
    if not match:
        return text
    hour, minute, second = (int(group or 0) for group in match.groups())
    if hour > 23 or minute > 59 or second > 59:
        return text
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def _normalise_stock_name(value: Any) -> str:
    """统一行情源中的证券简称，去除偶发的内部空白。"""

    return re.sub(r"\s+", "", str(value or "")).strip()


def _derive_public_late_break(
    board_break_count: int | None,
    last_seal_time: str | None = None,
    *,
    break_times: Iterable[Any] | None = None,
) -> bool:
    """仅当全天第一次炸板发生在13:00后时标记为午后炸板。

    分钟行情能给出炸板时刻时以第一次炸板为准；缺少分钟明细时不使用
    “最终封板时间”反推第一次炸板。公开炸板次数少于2次直接按放宽口径
    通过，达到2次但明细不完整只由上游添加疑似标记，不触发硬性淘汰。
    ``last_seal_time`` 仅为兼容旧调用保留。
    """

    del last_seal_time
    if board_break_count is None or board_break_count < 2:
        return False
    normalized_breaks = [
        normalized
        for item in (break_times or [])
        if (normalized := _normalise_time(item))
        and re.fullmatch(r"\d{2}:\d{2}:\d{2}", normalized)
    ]
    if not normalized_breaks:
        return False
    return min(normalized_breaks) >= "13:00:00"


def _normalise_concepts(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = re.split(r"[,，;；|/]", value)
    elif isinstance(value, Iterable) and not isinstance(value, Mapping):
        values = value
    else:
        values = [value]
    seen: set[str] = set()
    result: list[str] = []
    for item in values:
        text = str(item).strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _derive_metrics(values: dict[str, Any]) -> None:
    """只推导有明确算式的基础字段，不生成用户未提供口径的封单质量。"""

    peak = values.get("peak_order_amount")
    final = values.get("final_order_amount")
    if values.get("order_decay") is None and peak not in (None, 0) and final is not None:
        # 标准化字段约定：封单衰减 = (峰值封单 - 最终封单) / 峰值封单。
        values["order_decay"] = (peak - final) / peak

    order_amount = final if final is not None else peak
    float_market_cap = values.get("float_market_cap")
    turnover_amount = values.get("turnover_amount")
    if values.get("order_to_float_market_cap") is None and order_amount is not None and float_market_cap not in (None, 0):
        values["order_to_float_market_cap"] = order_amount / float_market_cap
    if values.get("order_to_turnover") is None and order_amount is not None and turnover_amount not in (None, 0):
        values["order_to_turnover"] = order_amount / turnover_amount


def normalize_market_record(
    record: Mapping[str, Any], *, trade_date: date | None = None
) -> CandidateMetrics:
    """将 CSV/XLSX 行或 API 响应的一条记录映射为统一候选字段。"""

    if not isinstance(record, Mapping):
        raise TypeError("行情记录必须是字典型数据")
    raw = dict(record)
    values: dict[str, Any] = {
        "trade_date": trade_date or _to_date(_lookup(raw, "trade_date")),
        "stock_code": _lookup(raw, "stock_code"),
        "stock_name": _normalise_stock_name(_lookup(raw, "stock_name")),
        "first_seal_time": _normalise_time(_lookup(raw, "first_seal_time")),
        "last_seal_time": _normalise_time(_lookup(raw, "last_seal_time")),
        "break_times": (
            [_normalise_time(item) for item in _normalise_concepts(_lookup(raw, "break_times"))]
            if _lookup(raw, "break_times") is not None else None
        ),
        "break_time_granularity": str(_lookup(raw, "break_time_granularity") or "").strip(),
        "board_break_count": _to_int(_lookup(raw, "board_break_count")),
        "public_late_break": _lookup(raw, "public_late_break"),
        "break_suspected": bool(_lookup(raw, "break_suspected") or False),
        "break_suspicion_reasons": _normalise_concepts(_lookup(raw, "break_suspicion_reasons")),
        "peak_order_amount": _to_float(_lookup(raw, "peak_order_amount")),
        "final_order_amount": _to_float(_lookup(raw, "final_order_amount")),
        "order_decay": _to_float(_lookup(raw, "order_decay")),
        "order_to_float_market_cap": _to_float(_lookup(raw, "order_to_float_market_cap")),
        "order_to_turnover": _to_float(_lookup(raw, "order_to_turnover")),
        "turnover_amount": _to_float(_lookup(raw, "turnover_amount")),
        "turnover_rate": _to_float(_lookup(raw, "turnover_rate")),
        "float_market_cap": _to_float(_lookup(raw, "float_market_cap")),
        "limit_price": _to_float(_lookup(raw, "limit_price")),
        "pool_board_count": _to_int(_lookup(raw, "pool_board_count")),
        "previous_trade_date": (_to_date(_lookup(raw, "previous_trade_date")) if _lookup(raw, "previous_trade_date") else None),
        "previous_day_limit_up": _lookup(raw, "previous_day_limit_up"),
        "is_confirmed_first_board": _lookup(raw, "is_confirmed_first_board"),
        "is_main_board_10cm_ordinary": _lookup(raw, "is_main_board_10cm_ordinary"),
        "close_limit_up": _lookup(raw, "close_limit_up"),
        "sector": str(_lookup(raw, "sector") or "").strip(),
        "concepts": _normalise_concepts(_lookup(raw, "concepts")),
        "market_sector": str(_lookup(raw, "market_sector") or _lookup(raw, "sector") or "").strip(),
        "market_concepts": _normalise_concepts(_lookup(raw, "market_concepts") or _lookup(raw, "concepts")),
        "same_attribute_board_order": _to_int(_lookup(raw, "same_attribute_board_order")),
        "raw_fields": raw,
        "data_source": str(_lookup(raw, "data_source") or "").strip(),
    }
    if values["public_late_break"] is None:
        values["public_late_break"] = _derive_public_late_break(
            values["board_break_count"],
            values["last_seal_time"],
            break_times=values["break_times"],
        )
    _derive_metrics(values)
    return CandidateMetrics.model_validate(values)


def normalize_candidate_metrics(
    record: CandidateMetrics | Mapping[str, Any], *, trade_date: date | None = None
) -> CandidateMetrics:
    if isinstance(record, CandidateMetrics):
        normalized_name = _normalise_stock_name(record.stock_name)
        return record if normalized_name == record.stock_name else record.model_copy(update={"stock_name": normalized_name})
    return normalize_market_record(record, trade_date=trade_date)
