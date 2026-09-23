"""首板布局业务编排：行情 → 属性 → 三态规则 → 独立 RAG → 分析上下文。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

from .analysis import DragonAnalysisService
from .attributes import apply_review_attributes, assign_same_attribute_orders, extract_review_attributes
from .context import build_analysis_context
from .knowledge import DragonKnowledgeStore
from .retrieval import DragonRetriever
from .market import DragonMarketProvider, normalize_candidate_metrics
from .rules import DragonRuleEngine
from .schemas import CandidateScreeningResult, DragonAnalysisContext, MarketSnapshot, ReviewSnapshot
from .store import DragonRuntimeStore


@dataclass(frozen=True)
class DragonPipelineOutput:
    market_snapshot: MarketSnapshot
    screening: list[CandidateScreeningResult]
    contexts: list[DragonAnalysisContext]
    rule_version_id: str

    @property
    def qualified(self) -> list[CandidateScreeningResult]:
        return [item for item in self.screening if item.candidate_bucket == "qualified"]

    @property
    def late_break_watch(self) -> list[CandidateScreeningResult]:
        return [item for item in self.screening if item.candidate_bucket == "late_break_watch"]

    @property
    def excluded(self) -> list[CandidateScreeningResult]:
        return [item for item in self.screening if item.candidate_bucket == "excluded"]


def _time_key(value: str | None) -> str:
    return value or "99:99:99"


def _candidate_sort_key(item: CandidateScreeningResult) -> tuple[str, int, str]:
    orders = list(item.candidate.same_attribute_orders.values())
    return (_time_key(item.candidate.first_seal_time), min(orders) if orders else 9999, item.candidate.stock_code)


class DragonPipeline:
    """每次运行只依赖 Dragon 两个数据库和注入的 Provider/分析器。"""

    def __init__(
        self,
        runtime: DragonRuntimeStore,
        knowledge: DragonKnowledgeStore,
        market_provider: DragonMarketProvider,
        analysis_service: DragonAnalysisService | None = None,
        alias_map: dict[str, str] | None = None,
    ) -> None:
        self.runtime = runtime
        self.knowledge = knowledge
        self.market_provider = market_provider
        self.analysis_service = analysis_service
        self.alias_map = dict(alias_map or {})

    def prepare(
        self,
        trade_date: date,
        *,
        stock_codes: Iterable[str] = (),
        rule_version_id: str = "",
    ) -> DragonPipelineOutput:
        snapshot = self.runtime.get_review_snapshot(trade_date, confirmed_only=True)
        if snapshot is None:
            raise ValueError("当日复盘结论尚未确认，不能开始首板布局")
        version = self.runtime.get_rule_version(rule_version_id) if rule_version_id else self.runtime.get_active_rule_version()
        if version is None:
            version = self.runtime.ensure_confirmed_default_rules()
        rules = [rule for rule in version.rules if rule.enabled]
        if not rules:
            raise ValueError("当前基础标准版本没有启用规则，请先启用规则后再分析")
        candidates = [normalize_candidate_metrics(item, trade_date=trade_date) for item in self.market_provider.fetch_first_board_candidates(trade_date)]
        if not candidates:
            raise ValueError("当日行情没有返回可筛选的首板候选")

        # 属性与同属性名次必须基于当日完整候选集计算；指定股票只缩小最终分析，
        # 不能把原本第二名在单股重跑时改写为第一名。
        candidates = self._attach_review_attributes(candidates, snapshot)
        market_snapshot = self.runtime.save_market_snapshot(MarketSnapshot(
            trade_date=trade_date,
            provider_name=self.market_provider.provider_name,
            candidates=candidates,
        ))
        screening = [DragonRuleEngine().evaluate(item, rules, rule_version_id=version.version_id) for item in candidates]
        screening.sort(key=_candidate_sort_key)
        self.runtime.save_screening_results(market_snapshot.market_snapshot_id, screening, rule_version_id=version.version_id)
        selected_codes = {str(code).strip().zfill(6) for code in stock_codes if str(code).strip()}
        selected_screening = (
            [item for item in screening if item.candidate.stock_code in selected_codes]
            if selected_codes else screening
        )
        if selected_codes and not selected_screening:
            raise ValueError("指定股票不在当日首板候选中")

        contexts: list[DragonAnalysisContext] = []
        retriever = DragonRetriever(self.knowledge)
        for item in selected_screening:
            evidence = []
            evidence_card = {}
            retrieval_trace = {}
            if item.basic_pass:
                candidate = item.candidate
                retrieved = retriever.retrieve(candidate, snapshot, limit=10)
                evidence = retrieved.evidence
                evidence_card = retrieved.evidence_card
                retrieval_trace = retrieved.trace
            contexts.append(build_analysis_context(
                snapshot=snapshot,
                screening=item,
                evidence=evidence,
                evidence_limit=10,
                evidence_card=evidence_card,
                retrieval_trace=retrieval_trace,
            ))
        return DragonPipelineOutput(market_snapshot, selected_screening, contexts, version.version_id)

    def _attach_review_attributes(self, candidates: list, snapshot: ReviewSnapshot) -> list:
        clean_candidates = [
            candidate.model_copy(update={
                "review_attribute_status": "没有提及",
                "review_attributes": [],
                "same_attribute_orders": {},
                "attribute_evidence": [],
                "same_attribute_board_order": None,
            })
            for candidate in candidates
        ]
        source_text = snapshot.source_text.strip()
        if not source_text:
            # 结构化复盘字段仍然进入模型 A 区，但不冒充股票—属性原文关系。
            return clean_candidates
        evidence = extract_review_attributes(
            source_text, clean_candidates, alias_map=self.alias_map,
            source_title=snapshot.source_title, source_url=snapshot.source_url,
        )
        return assign_same_attribute_orders(apply_review_attributes(clean_candidates, evidence))


__all__ = ["DragonPipeline", "DragonPipelineOutput"]
