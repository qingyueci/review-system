"""首板布局分通道召回、父案例展开与证据卡构建。"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Iterable

from .context import build_rag_query
from .knowledge import DragonKnowledgeStore
from .schemas import CandidateMetrics, DragonEvidence, ReviewSnapshot


HISTORY_TERMS = ("历史最高板", "历史高标", "穿越", "补涨", "再次启动", "历史属性")
NO_RESPONSE_TERMS = ("板块一点响应也没有", "板块没有响应", "无发酵", "没有发酵")


@dataclass(frozen=True)
class DragonRetrievalResult:
    evidence: list[DragonEvidence]
    evidence_card: dict[str, Any]
    trace: dict[str, Any]


def _loads(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return fallback


def _entity_rows(store: DragonKnowledgeStore, candidate: CandidateMetrics) -> list[dict[str, Any]]:
    with store._lock:  # 同一独立知识库连接上的只读检索。
        rows = store.connection.execute(
            """
            SELECT c.*, d.title, d.source_path, d.source_type, d.updated_at
            FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE c.stock_code = ? OR c.stock_name = ?
               OR instr(c.content, ?) > 0 OR instr(c.content, ?) > 0
            ORDER BY
                CASE WHEN c.stock_code = ? THEN 0
                     WHEN c.stock_name = ? THEN 1
                     WHEN instr(c.content, ?) > 0 THEN 2 ELSE 3 END,
                d.updated_at DESC, c.chunk_index
            LIMIT 60
            """,
            (
                candidate.stock_code,
                candidate.stock_name,
                candidate.stock_code,
                candidate.stock_name,
                candidate.stock_code,
                candidate.stock_name,
                candidate.stock_code,
            ),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        structured = row["stock_code"] == candidate.stock_code or row["stock_name"] == candidate.stock_name
        result.append(
            {
                "chunk_id": str(row["id"]),
                "source_id": row["document_id"],
                "document_id": row["document_id"],
                "title": row["title"],
                "source_path": row["source_path"],
                "content": row["content"],
                "metadata": _loads(row["metadata_json"], {}),
                "tags": _loads(row["tags_json"], []),
                "stock_code": row["stock_code"],
                "stock_name": row["stock_name"],
                "model_name": row["model_name"],
                "parent_case_id": row["parent_case_id"],
                "chunk_role": row["chunk_role"],
                "score": 1.0 if structured else 0.9,
                "exact_score": 1.0 if structured else 0.9,
                "retrieval_channel": "A_实体精确",
                "retrieval_mode": "结构化实体精确" if structured else "正文实体精确",
            }
        )
    return result


def _case_date(case: dict[str, Any] | None, metadata: dict[str, Any]) -> str:
    if case:
        return str(case.get("evidence_date") or "").strip()
    return str(metadata.get("case_date") or metadata.get("start_date") or metadata.get("end_date") or "").strip()


def _expanded_evidence(
    store: DragonKnowledgeStore,
    row: dict[str, Any],
    *,
    channel: str,
) -> DragonEvidence:
    metadata = dict(row.get("metadata") or {})
    case_id = str(row.get("parent_case_id") or "")
    case = store.expand_case(case_id, chunk_limit=6) if case_id else None
    if case:
        metadata = {**dict(case.get("metadata") or {}), **metadata}
        content = str(case.get("case_text") or row.get("content") or "")
        title = str(case.get("case_title") or row.get("title") or "")
    else:
        content = str(row.get("content") or "")
        title = str(row.get("title") or "")
    return DragonEvidence(
        source_id=str(row.get("source_id") or row.get("document_id") or "unknown-source"),
        chunk_id=str(row.get("chunk_id") or ""),
        title=title,
        source_path=str(row.get("source_path") or ""),
        content=content,
        score=float(row.get("score") or row.get("retrieval_score") or 0.0),
        tags=list(row.get("tags") or []),
        metadata=metadata,
        exact_score=float(row.get("exact_score") or 0.0),
        fts_score=float(row.get("fts_score") or 0.0),
        semantic_score=float(row.get("semantic_score") or 0.0),
        retrieval_mode=str(row.get("retrieval_mode") or channel),
        retrieval_channel=channel,
        parent_case_id=case_id,
        chunk_role=str(row.get("chunk_role") or "正文"),
        evidence_date=_case_date(case, metadata),
    )


def _board_number(value: Any) -> int | None:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else None


def _height_layer(board: int | None) -> str:
    if board is None:
        return ""
    if board >= 7:
        return f"历史{board}板及以上高辨识度高标"
    if board == 6:
        return "历史6板高辨识度高标"
    if board == 5:
        return "历史5板高标"
    return f"历史{board}板记录"


def _select_channels(
    channels: list[tuple[str, Iterable[dict[str, Any]]]],
    store: DragonKnowledgeStore,
    *,
    limit: int,
) -> list[DragonEvidence]:
    selected: list[DragonEvidence] = []
    seen_cases: dict[str, int] = {}
    seen_chunks: set[str] = set()
    for channel, rows in channels:
        for row in rows:
            chunk_id = str(row.get("chunk_id") or "")
            case_id = str(row.get("parent_case_id") or "")
            identity = case_id or f"chunk:{chunk_id}"
            # 每个父案例最多一条展开证据；不同股票即使来自同一 DOCX 也互不挤占。
            if seen_cases.get(identity, 0) >= 1 or chunk_id in seen_chunks:
                continue
            selected.append(_expanded_evidence(store, row, channel=channel))
            seen_cases[identity] = seen_cases.get(identity, 0) + 1
            if chunk_id:
                seen_chunks.add(chunk_id)
            if len(selected) >= limit:
                return selected
    return selected


class DragonRetriever:
    def __init__(self, store: DragonKnowledgeStore) -> None:
        self.store = store

    def retrieve(
        self,
        candidate: CandidateMetrics,
        snapshot: ReviewSnapshot,
        *,
        limit: int = 10,
    ) -> DragonRetrievalResult:
        maximum = max(6, min(int(limit), 10))
        query = build_rag_query(candidate, snapshot)
        entity = _entity_rows(self.store, candidate)
        history_query = " ".join(
            [candidate.stock_code, candidate.stock_name, *candidate.review_attributes, *HISTORY_TERMS]
        )
        history = self.store.search(
            history_query,
            limit=30,
            stock_code=candidate.stock_code,
            stock_name=candidate.stock_name,
            semantic=False,
        )
        for item in history:
            item["retrieval_channel"] = "B_历史字段"
        supplemental = self.store.search(
            query,
            limit=30,
            stock_code=candidate.stock_code,
            stock_name=candidate.stock_name,
            semantic=True,
        )
        for item in supplemental:
            item["retrieval_channel"] = "D_FTS语义补充"
        evidence = _select_channels(
            [
                ("A_实体精确", entity),
                ("B_历史字段", history),
                ("D_FTS语义补充", supplemental),
            ],
            self.store,
            limit=maximum,
        )

        owner_evidence = [
            item for item in evidence
            if str(item.metadata.get("stock_code") or "") == candidate.stock_code
            or str(item.metadata.get("stock_name") or "") == candidate.stock_name
        ]
        boards = [
            value for value in (
                _board_number(item.metadata.get("historical_highest_board"))
                for item in owner_evidence
            ) if value is not None
        ]
        highest_board = max(boards) if boards else None
        model_tags = list(dict.fromkeys(
            str(item.metadata.get("model_name") or "").strip()
            for item in owner_evidence
            if str(item.metadata.get("model_name") or "").strip()
        ))
        history_dates = list(dict.fromkeys(
            item.evidence_date for item in owner_evidence if item.evidence_date
        ))
        related_review = "\n".join(
            str(item.get("text") or item.get("evidence_text") or "")
            for item in candidate.attribute_evidence
        )
        no_response = any(term in related_review for term in NO_RESPONSE_TERMS)
        retrieval_status = (
            "完整" if owner_evidence and highest_board is not None
            else "部分匹配" if evidence
            else "未匹配"
        )
        card = {
            "stock_code": candidate.stock_code,
            "stock_name": candidate.stock_name,
            "objective_facts": candidate.model_dump(mode="json"),
            "review": {
                "attribute_status": candidate.review_attribute_status,
                "attributes": candidate.review_attributes,
                "evidence": candidate.attribute_evidence,
                "sector_response": "无发酵" if no_response else "未确认",
            },
            "history": {
                "highest_board": highest_board,
                "height_layer": _height_layer(highest_board),
                "identity_tags": [_height_layer(highest_board)] if highest_board is not None else [],
                "model_tags": model_tags,
                "dates": history_dates,
                "auto_old_dragon": False,
            },
            "positive_factors": [],
            "negative_factors": ["当日板块无发酵"] if no_response else [],
            "next_day_conditions": ["等待次日板块响应确认"] if no_response else [],
            "retrieval_status": retrieval_status,
        }
        trace = {
            "query": query,
            "channels": {
                "A_实体精确": [str(item.get("chunk_id") or "") for item in entity],
                "B_历史字段": [str(item.get("chunk_id") or "") for item in history],
                "C_复盘明示属性": candidate.attribute_evidence,
                "D_FTS语义补充": [str(item.get("chunk_id") or "") for item in supplemental],
            },
            "selected": [
                {
                    "reference": item.reference,
                    "parent_case_id": item.parent_case_id,
                    "channel": item.retrieval_channel,
                    "date": item.evidence_date,
                }
                for item in evidence
            ],
        }
        return DragonRetrievalResult(evidence=evidence, evidence_card=card, trace=trace)


__all__ = ["DragonRetriever", "DragonRetrievalResult"]
