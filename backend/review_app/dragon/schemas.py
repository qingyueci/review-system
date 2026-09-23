"""首板布局模块的接口数据结构。

这些模型是独立模块的边界：行情字段、规则检查、用户确认的复盘快照和模型
结论都以结构化数据传递。它们不依赖既有复盘 RAG 的任何模型或数据表。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


RuleComparison = Literal[
    "<=", "<", ">=", ">", "=", "!=", "in", "not_in", "exists", "not_exists",
    "in_time_windows", "none_at_or_after",
]
RuleStatus = Literal["通过", "不通过", "数据缺失"]
MissingDataPolicy = Literal["保留", "淘汰"]
AnalysisConclusion = Literal["重点", "观察", "排除"]
JobStatus = Literal["pending", "running", "succeeded", "failed"]
CandidateBucket = Literal["qualified", "late_break_watch", "excluded"]
AttributeStatus = Literal["明确匹配", "没有提及", "特殊条件"]


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class DragonModel(BaseModel):
    """共享的 Pydantic 配置，避免前端传入未声明字段后被静默忽略。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RuleDefinitionInput(DragonModel):
    """一条由用户定义的基础标准，不包含自动权重或综合评分。"""

    name: str = Field(min_length=1, max_length=120)
    data_field: str = Field(min_length=1, max_length=160)
    calculation: str = Field(default="", max_length=2_000)
    comparison: RuleComparison
    threshold: Any = None
    hard_condition: bool = False
    missing_policy: MissingDataPolicy = "保留"
    enabled: bool = True

    @field_validator("comparison", mode="before")
    @classmethod
    def normalize_comparison(cls, value: Any) -> Any:
        aliases = {
            "≤": "<=", "小于等于": "<=", "lte": "<=",
            "<": "<", "小于": "<", "lt": "<",
            "≥": ">=", "大于等于": ">=", "gte": ">=",
            ">": ">", "大于": ">", "gt": ">",
            "==": "=", "等于": "=", "eq": "=",
            "不等于": "!=", "ne": "!=",
            "属于": "in", "包含于": "in",
            "不属于": "not_in",
            "存在": "exists", "有值": "exists",
            "不存在": "not_exists", "无值": "not_exists",
            "时间窗口内": "in_time_windows", "in_windows": "in_time_windows",
            "不存在晚于": "none_at_or_after", "none_after": "none_at_or_after",
        }
        return aliases.get(str(value).strip().lower(), value)


class RuleDefinition(RuleDefinitionInput):
    rule_id: str = Field(default_factory=lambda: _new_id("rule"), min_length=8, max_length=80)
    version_id: str = Field(default="", max_length=80)
    position: int = Field(default=0, ge=0)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RuleVersionCreateRequest(DragonModel):
    name: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=2_000)
    rules: list[RuleDefinitionInput] = Field(default_factory=list, max_length=200)
    activate: bool = True


class RuleVersion(DragonModel):
    version_id: str = Field(default_factory=lambda: _new_id("rulever"), min_length=8, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=2_000)
    is_active: bool = False
    created_at: datetime | None = None
    rules: list[RuleDefinition] = Field(default_factory=list)


class ReviewSnapshotInput(DragonModel):
    """只允许用户明确确认后的复盘结论进入分析上下文。"""

    trade_date: date
    period_stage: str = Field(default="", max_length=2_000)
    market_core: str = Field(default="", max_length=4_000)
    positive_surprises: list[str] = Field(default_factory=list, max_length=100)
    negative_feedback: list[str] = Field(default_factory=list, max_length=100)
    effective_directions: list[str] = Field(default_factory=list, max_length=100)
    layout_tasks: list[str] = Field(default_factory=list, max_length=100)
    failure_conditions: list[str] = Field(default_factory=list, max_length=100)
    user_notes: str = Field(default="", max_length=8_000)
    source_text: str = Field(default="", max_length=80_000)
    source_title: str = Field(default="", max_length=500)
    source_url: str = Field(default="", max_length=2_000)
    confirm_as_layout: bool = False


class ReviewSnapshot(ReviewSnapshotInput):
    snapshot_id: str = Field(default_factory=lambda: _new_id("snapshot"), min_length=8, max_length=80)
    is_confirmed: bool = False
    confirmed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CandidateMetrics(DragonModel):
    """行情提供方无关的首板候选标准字段。

    金额与比率不擅自换算单位；`raw_fields` 保留来源原值，后续数据提供方可在
    其适配器内明确完成单位换算。
    """

    trade_date: date
    stock_code: str = Field(min_length=1, max_length=32)
    stock_name: str = Field(min_length=1, max_length=80)
    first_seal_time: str | None = Field(default=None, max_length=24)
    last_seal_time: str | None = Field(default=None, max_length=24)
    break_times: list[str] | None = Field(default=None, max_length=500)
    break_time_granularity: str = Field(default="", max_length=40)
    board_break_count: int | None = Field(default=None, ge=0)
    public_late_break: bool | None = None
    break_suspected: bool = False
    break_suspicion_reasons: list[str] = Field(default_factory=list, max_length=20)
    peak_order_amount: float | None = None
    final_order_amount: float | None = None
    order_decay: float | None = None
    order_to_float_market_cap: float | None = None
    order_to_turnover: float | None = None
    turnover_amount: float | None = None
    turnover_rate: float | None = None
    float_market_cap: float | None = None
    limit_price: float | None = None
    pool_board_count: int | None = Field(default=None, ge=0)
    previous_trade_date: date | None = None
    previous_day_limit_up: bool | None = None
    is_confirmed_first_board: bool | None = None
    is_main_board_10cm_ordinary: bool | None = None
    close_limit_up: bool | None = None
    sector: str = Field(default="", max_length=160)
    concepts: list[str] = Field(default_factory=list, max_length=100)
    market_sector: str = Field(default="", max_length=160)
    market_concepts: list[str] = Field(default_factory=list, max_length=100)
    review_attribute_status: AttributeStatus = "没有提及"
    review_attributes: list[str] = Field(default_factory=list, max_length=100)
    same_attribute_orders: dict[str, int] = Field(default_factory=dict)
    attribute_evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    same_attribute_board_order: int | None = Field(default=None, ge=1)
    data_source: str = Field(default="", max_length=120)
    raw_fields: dict[str, Any] = Field(default_factory=dict)

    @field_validator("stock_code", mode="before")
    @classmethod
    def preserve_stock_code(cls, value: Any) -> str:
        value = str(value).strip()
        if value.endswith(".0") and value[:-2].isdigit():
            value = value[:-2]
        return value.zfill(6) if value.isdigit() and len(value) < 6 else value

    @model_validator(mode="after")
    def keep_market_aliases_in_sync(self) -> "CandidateMetrics":
        """兼容旧字段名，同时把公开行情属性明确放在 market_* 命名空间。"""

        if not self.market_sector and self.sector:
            self.market_sector = self.sector
        if not self.sector and self.market_sector:
            self.sector = self.market_sector
        if not self.market_concepts and self.concepts:
            self.market_concepts = list(self.concepts)
        if not self.concepts and self.market_concepts:
            self.concepts = list(self.market_concepts)
        if self.same_attribute_orders and self.same_attribute_board_order is None:
            self.same_attribute_board_order = min(self.same_attribute_orders.values())
        return self


class MarketSnapshot(DragonModel):
    market_snapshot_id: str = Field(default_factory=lambda: _new_id("market"), min_length=8, max_length=80)
    trade_date: date
    provider_name: str = Field(default="", max_length=120)
    candidates: list[CandidateMetrics] = Field(default_factory=list, max_length=2_000)
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class RuleCheckResult(DragonModel):
    rule_id: str = Field(min_length=1, max_length=80)
    rule_name: str = Field(min_length=1, max_length=120)
    data_field: str = Field(min_length=1, max_length=160)
    actual_value: Any = None
    comparison: RuleComparison
    threshold: Any = None
    status: RuleStatus
    hard_condition: bool
    missing_policy: MissingDataPolicy
    is_disqualifying: bool = False
    message: str = Field(default="", max_length=2_000)


class CandidateScreeningResult(DragonModel):
    candidate: CandidateMetrics
    rule_version_id: str = Field(default="", max_length=80)
    checks: list[RuleCheckResult] = Field(default_factory=list, max_length=300)
    basic_pass: bool
    candidate_bucket: CandidateBucket = "qualified"
    disqualifying_rule_ids: list[str] = Field(default_factory=list, max_length=300)
    evaluated_at: datetime | None = None


class DragonEvidence(DragonModel):
    """独立历史模型库的一条可引用证据。"""

    source_id: str = Field(min_length=1, max_length=160)
    chunk_id: str = Field(default="", max_length=160)
    title: str = Field(default="", max_length=500)
    source_path: str = Field(default="", max_length=2_000)
    content: str = Field(default="", max_length=12_000)
    score: float = 0.0
    tags: list[str] = Field(default_factory=list, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)
    exact_score: float | None = None
    fts_score: float | None = None
    semantic_score: float | None = None
    retrieval_mode: str = Field(default="", max_length=200)
    retrieval_channel: str = Field(default="", max_length=80)
    parent_case_id: str = Field(default="", max_length=160)
    chunk_role: str = Field(default="正文", max_length=80)
    evidence_date: str = Field(default="", max_length=80)

    @property
    def reference(self) -> str:
        return self.chunk_id or self.source_id


class DragonAnalysisContext(DragonModel):
    """严格分离后发送给模型的四类上下文。"""

    trade_date: date
    review_snapshot: ReviewSnapshot
    screening: CandidateScreeningResult
    historical_evidence: list[DragonEvidence] = Field(default_factory=list, max_length=10)
    evidence_card: dict[str, Any] = Field(default_factory=dict)
    retrieval_trace: dict[str, Any] = Field(default_factory=dict)
    output_requirements: list[str] = Field(default_factory=list, max_length=20)


class DragonAnalysisResult(DragonModel):
    stock_code: str = Field(min_length=1, max_length=32)
    stock_name: str = Field(min_length=1, max_length=80)
    basic_pass: bool
    conclusion: AnalysisConclusion
    historical_models: list[str] = Field(default_factory=list, max_length=30)
    historical_recognition: str = Field(default="", max_length=8_000)
    current_review_fit: str = Field(default="", max_length=8_000)
    layout_task: str = Field(default="", max_length=8_000)
    expectation_point: str = Field(default="", max_length=8_000)
    guided_point: str = Field(default="", max_length=8_000)
    confirmation_conditions: list[str] = Field(default_factory=list, max_length=100)
    failure_conditions: list[str] = Field(default_factory=list, max_length=100)
    risks: list[str] = Field(default_factory=list, max_length=100)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)
    # 对外历史引用只显示具体日期。chunk/source 引用仍留在内部审计上下文中。
    history_dates: list[str] = Field(default_factory=list, max_length=20)
    # 大模型可以自行决定结果的内容层级和表达结构；固定字段仅用于兼容现有页面。
    analysis: dict[str, Any] = Field(default_factory=dict)
    model_output: dict[str, Any] = Field(default_factory=dict)


class DragonSelectionPolicy(DragonModel):
    """用户确认的批量选择边界，不包含自动评分或模型自定义门槛。"""

    focus_mode: Literal["relative"] = "relative"
    max_focus: int = Field(default=5, ge=1, le=20)
    allow_zero_focus: bool = True
    zero_focus_only_when_all_review_conflict: bool = True
    allow_qualified_exclusion: bool = True
    qualified_exclusion_reasons: list[str] = Field(
        default_factory=lambda: ["与用户确认复盘方向冲突"], max_length=20
    )
    insufficient_history_default: AnalysisConclusion = "观察"
    insufficient_history_is_sole_standard: bool = False
    auto_old_dragon: bool = False
    history_height_layers: list[dict[str, Any]] = Field(
        default_factory=lambda: [
            {"min_board": 5, "max_board": 5, "label": "历史5板高标"},
            {"min_board": 6, "max_board": 6, "label": "历史6板高辨识度高标"},
            {"min_board": 7, "max_board": None, "label": "历史7板及以上高辨识度高标"},
        ],
        max_length=20,
    )
    sector_no_response_behavior: Literal["confirmation_or_failure_condition"] = (
        "confirmation_or_failure_condition"
    )
    output_style: Literal["model_decides"] = "model_decides"


class DragonAnalysisRequest(DragonModel):
    trade_date: date
    stock_codes: list[str] = Field(default_factory=list, max_length=100)
    rule_version_id: str = Field(default="", max_length=80)
    model: str = Field(default="", max_length=100)
    thinking_enabled: bool = True
    selection_policy: DragonSelectionPolicy = Field(default_factory=DragonSelectionPolicy)


class DragonAnalysisRecord(DragonModel):
    analysis_id: str = Field(default_factory=lambda: _new_id("analysis"), min_length=8, max_length=80)
    job_id: str = Field(default="", max_length=80)
    trade_date: date
    stock_code: str = Field(min_length=1, max_length=32)
    stock_name: str = Field(min_length=1, max_length=80)
    basic_pass: bool
    result: DragonAnalysisResult
    context: DragonAnalysisContext
    rule_version_id: str = Field(default="", max_length=80)
    snapshot_id: str = Field(default="", max_length=80)
    created_at: datetime | None = None


class DragonJob(DragonModel):
    job_id: str = Field(default_factory=lambda: _new_id("dragonjob"), min_length=8, max_length=80)
    kind: str = Field(default="analysis", max_length=80)
    status: JobStatus = "pending"
    trade_date: date | None = None
    message: str = Field(default="", max_length=2_000)
    current: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AttributeAliasInput(DragonModel):
    original_attribute: str = Field(min_length=1, max_length=160)
    normalized_attribute: str = Field(min_length=1, max_length=160)


class AttributeAliasVersionCreateRequest(DragonModel):
    name: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=2_000)
    aliases: list[AttributeAliasInput] = Field(default_factory=list, max_length=1_000)
    activate: bool = True


class AttributeAliasVersion(DragonModel):
    version_id: str = Field(default_factory=lambda: _new_id("aliasver"), min_length=8, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=2_000)
    aliases: list[AttributeAliasInput] = Field(default_factory=list, max_length=1_000)
    is_active: bool = False
    created_at: datetime | None = None
