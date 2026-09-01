"""首板布局的独立 FastAPI 路由。

路由只接触 ``dragon_runtime.db`` 与 ``dragon_knowledge.db``。旧复盘 API、
旧 RAG 和原有任务记录都不会被读取或写入。
"""

from __future__ import annotations

import base64
import binascii
from datetime import date
import json
import os
from pathlib import Path
from threading import Thread
from typing import Any, Callable, Mapping

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from ..artifact_store import save_artifact
from ..config import API_BASE_URL, API_MAX_RETRIES, API_TIMEOUT_SECONDS, MODEL_NAME, PROJECT_DIR
from .analysis import (
    DeepSeekCompletionAdapter,
    DragonAnalysisJobRunner,
    DragonAnalysisService,
)
from .context import build_analysis_context, build_rag_query
from .field_registry import public_field_registry
from .export import build_dragon_analysis_docx
from .knowledge import DragonKnowledgeStore
from .market import (
    DragonMarketProvider,
    EastmoneyDragonMarketProvider,
    MarketProviderNotConfiguredError,
    UnconfiguredDragonMarketProvider,
)
from .pipeline import DragonPipeline
from .rules import DragonRuleEngine
from .schemas import (
    AttributeAliasVersionCreateRequest,
    DragonAnalysisRecord,
    DragonAnalysisRequest,
    MarketSnapshot,
    ReviewSnapshot,
    ReviewSnapshotInput,
    RuleDefinition,
    RuleDefinitionInput,
    RuleVersionCreateRequest,
)
from .store import DragonRuntimeStore


MAX_UPLOAD_BYTES = 30 * 1024 * 1024
TokenVerifier = Callable[[str | None], None]
RuntimeStoreFactory = Callable[[], DragonRuntimeStore]
KnowledgeStoreFactory = Callable[[], DragonKnowledgeStore]
MarketProviderFactory = Callable[[], DragonMarketProvider]
AnalysisServiceFactory = Callable[[], DragonAnalysisService]


def _as_list(value: Any) -> list[str]:
    """保留用户输入的列表边界；字符串按换行或中文常用分隔符拆分。"""

    if value is None:
        return []
    if isinstance(value, str):
        values = value.replace("\r", "").replace("、", "\n").replace("；", "\n").split("\n")
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = [value]
    result: list[str] = []
    for item in values:
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result


def _first(payload: Mapping[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return default


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _public_snapshot(snapshot: ReviewSnapshot | None) -> dict[str, Any] | None:
    """兼容页面的便捷字符串字段，同时保留模型使用的原始列表。"""

    if snapshot is None:
        return None
    payload = snapshot.model_dump(mode="json")
    payload.update(
        {
            "confirmed": snapshot.is_confirmed,
            "expectation_point": "\n".join(snapshot.positive_surprises),
            "negative_feedback": "\n".join(snapshot.negative_feedback),
            "effective_directions": "\n".join(snapshot.effective_directions),
            "tomorrow_tasks": "\n".join(snapshot.layout_tasks),
            "failure_conditions": "\n".join(snapshot.failure_conditions),
        }
    )
    return payload


def _snapshot_from_payload(payload: Mapping[str, Any]) -> ReviewSnapshotInput:
    try:
        return ReviewSnapshotInput(
            trade_date=_first(payload, "trade_date"),
            period_stage=str(_first(payload, "period_stage")),
            market_core=str(_first(payload, "market_core")),
            positive_surprises=_as_list(
                _first(payload, "positive_surprises", "expectation_point", default=[])
            ),
            negative_feedback=_as_list(_first(payload, "negative_feedback", default=[])),
            effective_directions=_as_list(
                _first(payload, "effective_directions", default=[])
            ),
            layout_tasks=_as_list(_first(payload, "layout_tasks", "tomorrow_tasks", default=[])),
            failure_conditions=_as_list(_first(payload, "failure_conditions", default=[])),
            user_notes=str(_first(payload, "user_notes")),
            source_text=str(_first(payload, "source_text", "review_text", default="")),
            source_title=str(_first(payload, "source_title", default="")),
            source_url=str(_first(payload, "source_url", default="")),
            confirm_as_layout=bool(
                _first(payload, "confirm_as_layout", "confirmed", default=False)
            ),
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"当日复盘快照字段无效：{exc}") from exc


def _rule_input_from_payload(payload: Mapping[str, Any]) -> RuleDefinitionInput:
    missing_policy = str(
        _first(payload, "missing_policy", "missing_behavior", default="保留")
    ).strip()
    if missing_policy in {"标记数据缺失", "保留", "keep"}:
        missing_policy = "保留"
    elif missing_policy in {"淘汰", "eliminate"}:
        missing_policy = "淘汰"
    try:
        return RuleDefinitionInput(
            name=str(_first(payload, "name", "rule_name")).strip(),
            data_field=str(_first(payload, "data_field", "field")).strip(),
            calculation=str(_first(payload, "calculation", default="")).strip(),
            comparison=_first(payload, "comparison", "operator"),
            threshold=_first(payload, "threshold", default=None),
            hard_condition=bool(_first(payload, "hard_condition", "is_hard", default=False)),
            missing_policy=missing_policy,
            enabled=bool(_first(payload, "enabled", default=True)),
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"基础标准字段无效：{exc}") from exc


def _rule_input_from_stored(rule: RuleDefinition) -> RuleDefinitionInput:
    return RuleDefinitionInput(
        name=rule.name,
        data_field=rule.data_field,
        calculation=rule.calculation,
        comparison=rule.comparison,
        threshold=rule.threshold,
        hard_condition=rule.hard_condition,
        missing_policy=rule.missing_policy,
        enabled=rule.enabled,
    )


def _threshold_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False)


def _public_rule(rule: RuleDefinition, *, version_name: str = "") -> dict[str, Any]:
    return {
        "id": rule.rule_id,
        "rule_id": rule.rule_id,
        "name": rule.name,
        "data_field": rule.data_field,
        "field": rule.data_field,
        "calculation": rule.calculation,
        "comparison": rule.comparison,
        "threshold": _threshold_text(rule.threshold),
        "hard_condition": rule.hard_condition,
        "is_hard": rule.hard_condition,
        "missing_policy": rule.missing_policy,
        "missing_behavior": "淘汰" if rule.missing_policy == "淘汰" else "标记数据缺失",
        "enabled": rule.enabled,
        "version_id": rule.version_id,
        "version": version_name or rule.version_id,
        "position": rule.position,
    }


def _public_document(document: Mapping[str, Any]) -> dict[str, Any]:
    source_path = str(document.get("source_path", ""))
    filename = Path(source_path.replace("upload://", "").rstrip("/")).name
    return {
        **dict(document),
        "id": document.get("id") or document.get("document_id"),
        "filename": filename or document.get("title", "未命名资料"),
        "file_type": document.get("source_type", ""),
        "chunk_count": document.get("chunks", document.get("chunk_count", 0)),
        "imported_at": document.get("updated_at", document.get("created_at", "")),
    }


def _public_evidence(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **dict(item),
        "id": item.get("chunk_id") or item.get("source_id"),
        "source_name": item.get("title", "未命名来源"),
        "excerpt": item.get("content", ""),
    }


def _public_candidate(record: DragonAnalysisRecord) -> dict[str, Any]:
    result = record.result.model_dump(mode="json")
    screening = record.context.screening
    result["checks"] = [item.model_dump(mode="json") for item in screening.checks]
    result["rule_checks"] = result["checks"]
    # 对外只给历史案例日期；原文、文件名、切片编号保留在内部审计记录。
    result["history_dates"] = list(record.result.history_dates)
    result["evidence_ref_ids"] = []
    result["evidence_refs"] = []
    candidate = screening.candidate
    result["candidate_bucket"] = screening.candidate_bucket
    result["metrics"] = candidate.model_dump(mode="json")
    result["market_sector"] = candidate.market_sector or candidate.sector
    result["market_concepts"] = candidate.market_concepts or candidate.concepts
    result["review_attribute_status"] = candidate.review_attribute_status
    result["review_attributes"] = candidate.review_attributes
    result["same_attribute_orders"] = candidate.same_attribute_orders
    result["attribute_evidence"] = candidate.attribute_evidence
    return result


def _public_analysis_record(record: DragonAnalysisRecord) -> dict[str, Any]:
    candidate = _public_candidate(record)
    return {
        "id": record.analysis_id,
        "analysis_id": record.analysis_id,
        "job_id": record.job_id,
        "trade_date": record.trade_date.isoformat(),
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "status": "succeeded",
        "standard_version": record.rule_version_id,
        "rule_version": record.rule_version_id,
        "snapshot": _public_snapshot(record.context.review_snapshot),
        "review_snapshot": _public_snapshot(record.context.review_snapshot),
        "result": {"candidates": [candidate]},
        "raw_result": record.result.model_dump(mode="json"),
        "context": record.context.model_dump(mode="json"),
    }


def _default_analysis_service() -> DragonAnalysisService:
    """按需复用现有 DeepSeek 配置，避免把密钥传给前端或写入数据库。"""

    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("本机 .env 尚未配置 DEEPSEEK_API_KEY")
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=api_key,
            base_url=API_BASE_URL,
            timeout=API_TIMEOUT_SECONDS,
            max_retries=API_MAX_RETRIES,
        )
    except Exception as exc:
        raise RuntimeError(f"DeepSeek 客户端初始化失败：{exc}") from exc
    return DragonAnalysisService(DeepSeekCompletionAdapter(client))


def _select_rule_version(
    store: DragonRuntimeStore, requested_id: str
) -> tuple[str, list[RuleDefinition]]:
    version = store.get_rule_version(requested_id) if requested_id else store.get_active_rule_version()
    if version is None and not requested_id:
        version = store.ensure_confirmed_default_rules()
    if version is None:
        raise ValueError("尚未配置并启用首板基础标准")
    return version.version_id, [rule for rule in version.rules if rule.enabled]


def create_dragon_router(
    verify_token: TokenVerifier,
    *,
    runtime_store_factory: RuntimeStoreFactory = DragonRuntimeStore,
    knowledge_store_factory: KnowledgeStoreFactory = DragonKnowledgeStore,
    market_provider_factory: MarketProviderFactory = EastmoneyDragonMarketProvider,
    analysis_service_factory: AnalysisServiceFactory | None = None,
    output_dir: Path | None = None,
) -> APIRouter:
    """创建挂载到现有本机服务的首板布局路由。

    工厂参数是测试和后续行情接入的单一注入点，不会改变规则、RAG 或旧站点 API。
    """

    def require_local_token(
        x_review_token: str | None = Header(default=None),
    ) -> None:
        verify_token(x_review_token)

    router = APIRouter(
        prefix="/api/dragon",
        tags=["首板布局"],
        dependencies=[Depends(require_local_token)],
    )
    export_dir = output_dir or PROJECT_DIR / "output"

    @router.get("/status")
    def status() -> dict[str, Any]:
        runtime = runtime_store_factory()
        with knowledge_store_factory() as knowledge:
            knowledge_stats = knowledge.stats()
        active_version = runtime.get_active_rule_version()
        provider = market_provider_factory()
        market_ready = not isinstance(provider, UnconfiguredDragonMarketProvider)
        if hasattr(provider, "close"):
            provider.close()
        return {
            "ok": True,
            "api_key_configured": bool(os.getenv("DEEPSEEK_API_KEY", "").strip()),
            "market_provider_configured": market_ready,
            "market_provider": provider.provider_name,
            "knowledge": knowledge_stats,
            "knowledge_documents": knowledge_stats["documents"],
            "knowledge_chunks": knowledge_stats["chunks"],
            "rules_count": len(active_version.rules) if active_version else 0,
            "field_registry": public_field_registry(),
            "attribute_alias_version": _jsonable(runtime.get_active_attribute_alias_version()),
            "active_rule_version": _jsonable(active_version) if active_version else None,
            "runtime": runtime.stats(),
        }

    @router.get("/snapshot")
    def get_snapshot(trade_date: date = Query(...)) -> dict[str, Any]:
        snapshot = runtime_store_factory().get_review_snapshot(trade_date)
        return {"snapshot": _public_snapshot(snapshot)}

    @router.post("/snapshot")
    def save_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
        snapshot_input = _snapshot_from_payload(payload)
        saved = runtime_store_factory().save_review_snapshot(
            snapshot_input,
            confirm=snapshot_input.confirm_as_layout,
        )
        return {"snapshot": _public_snapshot(saved), **(_public_snapshot(saved) or {})}

    @router.get("/rules")
    def list_rules() -> dict[str, Any]:
        runtime = runtime_store_factory()
        active = runtime.get_active_rule_version()
        versions = runtime.list_rule_versions()
        return {
            "rules": [
                _public_rule(rule, version_name=active.name)
                for rule in (active.rules if active else [])
            ],
            "active_version_id": active.version_id if active else "",
            "versions": [
                {
                    "version_id": version.version_id,
                    "name": version.name,
                    "note": version.note,
                    "is_active": version.is_active,
                    "created_at": version.created_at.isoformat() if version.created_at else "",
                    "rule_count": len(version.rules),
                }
                for version in versions
            ],
        }

    @router.post("/rules/bootstrap")
    def bootstrap_rules() -> dict[str, Any]:
        """首次使用时写入已确认的七条硬规则；已有版本不会被覆盖。"""

        version = runtime_store_factory().ensure_confirmed_default_rules()
        return {"version": _jsonable(version), "rules": [_public_rule(rule, version_name=version.name) for rule in version.rules]}

    @router.get("/fields")
    def list_fields() -> dict[str, Any]:
        return {"fields": public_field_registry()}

    @router.get("/attribute-alias-versions")
    def list_attribute_alias_versions() -> dict[str, Any]:
        runtime = runtime_store_factory()
        return {"versions": [_jsonable(version) for version in runtime.list_attribute_alias_versions()]}

    @router.post("/attribute-alias-versions")
    def create_attribute_alias_version(payload: AttributeAliasVersionCreateRequest) -> dict[str, Any]:
        version = runtime_store_factory().save_attribute_alias_version(payload)
        return _jsonable(version)

    @router.post("/attribute-alias-versions/{version_id}/activate")
    def activate_attribute_alias_version(version_id: str) -> dict[str, Any]:
        try:
            version = runtime_store_factory().set_active_attribute_alias_version(version_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _jsonable(version)

    @router.post("/rules")
    def add_rule(payload: dict[str, Any]) -> dict[str, Any]:
        """为页面的逐条编辑创建一个新的不可变规则版本。"""

        runtime = runtime_store_factory()
        if isinstance(payload.get("rules"), list):
            try:
                request = RuleVersionCreateRequest.model_validate(payload)
            except Exception as exc:
                raise HTTPException(status_code=422, detail=f"规则版本字段无效：{exc}") from exc
            version = runtime.save_rule_version(
                request.rules,
                name=request.name,
                note=request.note,
                activate=request.activate,
            )
            return {
                "version": _jsonable(version),
                "rules": [_public_rule(rule, version_name=version.name) for rule in version.rules],
            }

        active = runtime.get_active_rule_version()
        inputs = [_rule_input_from_stored(rule) for rule in (active.rules if active else [])]
        inputs.append(_rule_input_from_payload(payload))
        version_name = str(_first(payload, "version", default="")).strip() or (
            active.name if active else "首板基础标准"
        )
        version = runtime.save_rule_version(
            inputs,
            name=version_name,
            note=str(_first(payload, "note", default="")),
            activate=True,
        )
        return {
            "version": _jsonable(version),
            "rules": [_public_rule(rule, version_name=version.name) for rule in version.rules],
        }

    @router.post("/rules/{rule_id}")
    def update_rule(rule_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        runtime = runtime_store_factory()
        active = runtime.get_active_rule_version()
        if active is None:
            raise HTTPException(status_code=404, detail="没有可更新的基础标准")
        if not any(rule.rule_id == rule_id for rule in active.rules):
            raise HTTPException(status_code=404, detail="没有找到该基础标准")
        replacement = _rule_input_from_payload(payload)
        inputs = [
            replacement if rule.rule_id == rule_id else _rule_input_from_stored(rule)
            for rule in active.rules
        ]
        version_name = str(_first(payload, "version", default="")).strip() or active.name
        version = runtime.save_rule_version(
            inputs,
            name=version_name,
            note=str(_first(payload, "note", default=active.note)),
            activate=True,
        )
        return {
            "version": _jsonable(version),
            "rules": [_public_rule(rule, version_name=version.name) for rule in version.rules],
        }

    @router.get("/rule-versions")
    def list_rule_versions() -> dict[str, Any]:
        versions = runtime_store_factory().list_rule_versions()
        return {
            "versions": [
                {
                    **version.model_dump(mode="json"),
                    "rules": [_public_rule(rule, version_name=version.name) for rule in version.rules],
                }
                for version in versions
            ]
        }

    @router.post("/rule-versions")
    def create_rule_version(payload: RuleVersionCreateRequest) -> dict[str, Any]:
        version = runtime_store_factory().save_rule_version(
            payload.rules,
            name=payload.name,
            note=payload.note,
            activate=payload.activate,
        )
        return {
            **version.model_dump(mode="json"),
            "rules": [_public_rule(rule, version_name=version.name) for rule in version.rules],
        }

    @router.post("/rule-versions/{version_id}/activate")
    def activate_rule_version(version_id: str) -> dict[str, Any]:
        try:
            version = runtime_store_factory().set_active_rule_version(version_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            **version.model_dump(mode="json"),
            "rules": [_public_rule(rule, version_name=version.name) for rule in version.rules],
        }

    @router.delete("/rule-versions/{version_id}")
    def delete_rule_version(version_id: str) -> dict[str, Any]:
        try:
            runtime_store_factory().delete_rule_version(version_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"ok": True, "version_id": version_id}

    @router.get("/documents")
    def list_documents(limit: int = Query(default=200, ge=1, le=500)) -> dict[str, Any]:
        with knowledge_store_factory() as knowledge:
            documents = knowledge.list_documents(limit=limit)
        return {"documents": [_public_document(item) for item in documents]}

    @router.post("/documents")
    def import_document(payload: dict[str, Any]) -> dict[str, Any]:
        filename = str(_first(payload, "filename", "name", default="")).strip()
        encoded = str(_first(payload, "content_base64", default="")).strip()
        if not filename or not encoded:
            raise HTTPException(status_code=422, detail="上传资料需要 filename 和 content_base64")
        if "," in encoded and encoded.lower().startswith("data:"):
            encoded = encoded.split(",", 1)[1]
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise HTTPException(status_code=422, detail="上传资料的 Base64 内容无效") from exc
        if not content:
            raise HTTPException(status_code=422, detail="上传资料为空")
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="单个历史模型资料不得超过 30 MB")
        metadata = payload.get("metadata")
        if metadata is not None and not isinstance(metadata, Mapping):
            raise HTTPException(status_code=422, detail="资料 metadata 必须是对象")
        try:
            with knowledge_store_factory() as knowledge:
                document = knowledge.import_bytes(
                    filename,
                    content,
                    title=str(_first(payload, "title", default="")).strip() or None,
                    tags=_as_list(payload.get("tags")),
                    metadata=dict(metadata or {}),
                    source_id=str(_first(payload, "source_id", default="")).strip() or None,
                )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"document": _public_document(document), **_public_document(document)}

    @router.get("/documents/{document_id}/chunks")
    def list_document_chunks(
        document_id: str,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        with knowledge_store_factory() as knowledge:
            if knowledge.get_document(document_id) is None:
                raise HTTPException(status_code=404, detail="没有找到该历史模型资料")
            chunks = knowledge.list_chunks(document_id, limit=limit)
        return {"chunks": [_public_evidence(item) for item in chunks]}

    @router.post("/documents/{document_id}/tags")
    def update_document_tags(document_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with knowledge_store_factory() as knowledge:
            try:
                document = knowledge.update_document_tags(document_id, _as_list(payload.get("tags")))
            except KeyError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"document": _public_document(document), **_public_document(document)}

    @router.get("/tags")
    def list_tags() -> dict[str, Any]:
        with knowledge_store_factory() as knowledge:
            return {"tags": knowledge.list_tags()}

    @router.get("/search")
    def search(
        q: str = Query(min_length=1, max_length=2_000),
        limit: int = Query(default=8, ge=1, le=10),
        stock_code: str | None = Query(default=None),
        stock_name: str | None = Query(default=None),
        tags: str | None = Query(default=None),
    ) -> dict[str, Any]:
        with knowledge_store_factory() as knowledge:
            results = knowledge.search(
                q,
                limit=limit,
                stock_code=stock_code,
                stock_name=stock_name,
                tags=_as_list(tags),
            )
        return {"results": [_public_evidence(item) for item in results]}

    def _build_contexts(
        request: DragonAnalysisRequest,
        runtime: DragonRuntimeStore,
    ) -> list[Any]:
        provider = market_provider_factory()
        alias_version = runtime.get_active_attribute_alias_version()
        alias_map = {
            item.original_attribute: item.normalized_attribute
            for item in (alias_version.aliases if alias_version else [])
        }
        with knowledge_store_factory() as knowledge:
            try:
                output = DragonPipeline(
                    runtime, knowledge, provider, alias_map=alias_map,
                ).prepare(
                    request.trade_date,
                    stock_codes=request.stock_codes,
                    rule_version_id=request.rule_version_id,
                )
            finally:
                if hasattr(provider, "close"):
                    provider.close()
        return output.contexts

    def _run_analysis_job(job_id: str, request: DragonAnalysisRequest) -> None:
        runtime = runtime_store_factory()
        try:
            runtime.update_job(
                job_id,
                status="running",
                message="正在抓取并标准化当日首板数据",
                current=1,
                total=8,
            )
            contexts = _build_contexts(request, runtime)
            runtime.update_job(
                job_id,
                status="running",
                message="基础筛选、独立 RAG 检索与上下文构建已完成",
                current=6,
                total=8,
            )
            needs_completion = any(context.screening.basic_pass for context in contexts)
            service = (
                (analysis_service_factory or _default_analysis_service)()
                if needs_completion
                else DragonAnalysisService()
            )
            records = DragonAnalysisJobRunner(runtime, service).run_batch(
                job_id,
                contexts,
                policy=request.selection_policy,
                model=request.model or MODEL_NAME,
                thinking_enabled=request.thinking_enabled,
                result_builder=lambda completed: {
                    "analysis_ids": [record.analysis_id for record in completed],
                    "candidates": [_public_candidate(record) for record in completed],
                    "qualified": [
                        _public_candidate(record) for record in completed
                        if record.context.screening.candidate_bucket == "qualified"
                    ],
                    "late_break_watch": [
                        _public_candidate(record) for record in completed
                        if record.context.screening.candidate_bucket == "late_break_watch"
                    ],
                    "excluded": [
                        _public_candidate(record) for record in completed
                        if record.context.screening.candidate_bucket == "excluded"
                    ],
                },
            )
        except Exception as exc:
            try:
                runtime.update_job(job_id, status="failed", message=str(exc))
            except Exception:
                pass

    @router.post("/analyze-async")
    def start_analysis(payload: DragonAnalysisRequest) -> dict[str, Any]:
        provider = market_provider_factory()
        if isinstance(provider, UnconfiguredDragonMarketProvider):
            raise HTTPException(
                status_code=409,
                detail="尚未配置首板行情数据源，请先提供 API 文档或每日 CSV/XLSX 样例",
            )
        runtime = runtime_store_factory()
        if runtime.get_review_snapshot(payload.trade_date, confirmed_only=True) is None:
            raise HTTPException(status_code=409, detail="请先确认当日复盘结论")
        try:
            _select_rule_version(runtime, payload.rule_version_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        job = runtime.create_job(
            kind="dragon_analysis",
            trade_date=payload.trade_date,
            payload=payload.model_dump(mode="json"),
            total=8,
        )
        Thread(
            target=_run_analysis_job,
            args=(job.job_id, payload),
            daemon=True,
            name=f"dragon-analysis-{job.job_id[-8:]}",
        ).start()
        return {"job_id": job.job_id, "status": job.status, "reused": False}

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = runtime_store_factory().get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="没有找到该首板布局任务")
        return job.model_dump(mode="json")

    @router.get("/jobs/{job_id}/audit")
    def get_job_audit(job_id: str) -> dict[str, Any]:
        audit = runtime_store_factory().get_batch_audit(job_id)
        if audit is None:
            raise HTTPException(status_code=404, detail="没有找到该批次的分析审计记录")
        return audit

    @router.get("/analyses")
    def list_analyses(
        limit: int = Query(default=20, ge=1, le=200),
        trade_date: date | None = Query(default=None),
    ) -> dict[str, Any]:
        records = runtime_store_factory().list_analyses(
            trade_date=trade_date,
            limit=limit,
        )
        return {"analyses": [_public_analysis_record(record) for record in records]}

    @router.post("/analyses/export")
    def export_analyses(payload: dict[str, Any]) -> dict[str, Any]:
        raw_trade_date = str(payload.get("trade_date") or "").strip()
        if not raw_trade_date:
            raise HTTPException(status_code=422, detail="请选择要保存的首板分析日期")
        try:
            selected_date = date.fromisoformat(raw_trade_date[:10])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="首板分析日期格式无效") from exc

        runtime = runtime_store_factory()
        records = runtime.list_analyses(trade_date=selected_date, limit=200)
        requested_job_id = str(payload.get("job_id") or "").strip()
        job_id = requested_job_id or (records[0].job_id if records else "")
        selected = [record for record in records if record.job_id == job_id]
        if not selected:
            raise HTTPException(status_code=404, detail="该日期没有可保存的首板分析结果")

        filename = save_artifact(
            export_dir,
            build_dragon_analysis_docx(selected),
            f"首板布局_{selected_date.isoformat()}.docx",
        )
        return {
            "filename": filename,
            "path": str((export_dir / filename).resolve()),
            "job_id": job_id,
            "candidate_count": len(selected),
        }

    return router


__all__ = ["create_dragon_router"]
