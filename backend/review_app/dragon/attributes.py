"""从刺大复盘原文提取明确的股票—属性关系。

这里坚持词面证据：公开行情的板块/概念只记录，不替补复盘原文关系；
含条件、复合或不确定措辞的关系标为“特殊条件”，并保留原文片段。
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Mapping

from .schemas import AttributeStatus, CandidateMetrics


@dataclass(frozen=True)
class ReviewAttributeEvidence:
    stock_code: str
    stock_name: str
    status: AttributeStatus
    original_attribute: str = ""
    normalized_attribute: str = ""
    evidence_text: str = ""
    source_title: str = ""
    source_url: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "status": self.status,
            "original_attribute": self.original_attribute,
            "normalized_attribute": self.normalized_attribute,
            "evidence_text": self.evidence_text,
            "source_title": self.source_title,
            "source_url": self.source_url,
        }


_RELATION_RE = re.compile(
    r"(?P<stock>[^，。；;\n]{1,24}?)(?:是|属于|归属|归于|为|所在)(?P<attr>[^，。；;\n]{1,32}?)(?:板块|概念|题材|属性)(?P<tail>[^，。；;\n]*)"
)
_REVERSE_RE = re.compile(
    r"(?P<attr>[\u4e00-\u9fffA-Za-z0-9+#/&·-]{1,24}?)(?:板块|概念|题材|属性)[：:、,，\s]*(?P<stocks>[^。；;\n]+)"
)
_AMBIGUOUS_MARKERS = ("如果", "若", "可能", "或", "兼具", "叠加", "偏", "条件", "一旦", "视为", "待验证")
_SEPARATORS = re.compile(r"[、,，/和及与\s]+")
_SECTION_STOP_MARKERS = (
    "首封时间", "尾盘", "首板总结", "二板晋级", "三板晋级", "四板晋级", "五板晋级", "六板晋级",
    "七板晋级", "观察计划", "高标情绪", "竞价最优解", "气质股", "思考题", "其余形式独苗",
)


def _normalise_match_text(value: object) -> str:
    """归一化用于个股名称匹配的文本。

    东方财富等行情源偶尔会把中文简称写成带内部空格的形式（例如
    ``金 螳 螂``），而复盘原文通常没有空格。匹配时去掉所有空白，
    证据文本仍保留原始句子，避免改变用户看到的原文。
    """

    return re.sub(r"\s+", "", str(value or ""))


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[。！？；;\n])", text or "") if part.strip()]


def _candidate_mention(sentence: str, candidate: CandidateMetrics) -> bool:
    sentence_key = _normalise_match_text(sentence)
    return (
        _normalise_match_text(candidate.stock_name) in sentence_key
        or _normalise_match_text(candidate.stock_code) in sentence_key
    )


def _candidate_in_text(text: str, candidate: CandidateMetrics) -> bool:
    """在已提取的关系片段中按同一规则判断候选是否出现。"""

    return _candidate_mention(text, candidate)


def _clean_attribute(value: str) -> str:
    return re.sub(r"^[\s:：,，、/]+|[\s:：,，、/]+$", "", value).strip()


def _plain_table_identity(value: str) -> str:
    """去掉常见 Markdown 标记，但不放宽表格首列的精确匹配。"""

    value = re.sub(r"!?(?:\[([^\]]+)\])\([^)]*\)", r"\1", value)
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"[`*_~]", "", value)
    return _clean_attribute(value)


def _table_attributes(sentence: str, candidate: CandidateMetrics) -> list[str]:
    """读取复盘任务表中明确写出的“个股 | 首板出身”关系。"""

    cells = [_clean_attribute(item) for item in sentence.strip().strip("|").split("|")]
    first_cell = _plain_table_identity(cells[0]) if cells else ""
    first_cell_key = _normalise_match_text(first_cell)
    candidate_name_key = _normalise_match_text(candidate.stock_name)
    candidate_code_key = _normalise_match_text(candidate.stock_code)
    if len(cells) < 2 or first_cell_key not in {candidate_name_key, candidate_code_key}:
        return []
    value = re.sub(r"（[^）]*）|\([^)]*\)", "", cells[1]).strip()
    return [item for item in (_clean_attribute(part) for part in value.split("/")) if item]


def _section_heading(line: str) -> str:
    """识别“板块标题换行后列股票”的复盘格式。"""

    value = re.sub(r"^[#>*\-\s]+|[`*_~]", "", line or "").strip()
    value = re.sub(r"[：:]$", "", value).strip()
    if not value or value in _SECTION_STOP_MARKERS:
        return ""
    if len(value) > 16 or re.search(r"[0-9０-９]|[。！？；;，,、]", value):
        return ""
    if any(marker in value for marker in ("时间", "板块", "总结", "计划", "情绪", "晋级", "最优", "思考", "形式")):
        return ""
    return value


def _section_attribute_matches(
    text: str,
    candidates: Iterable[CandidateMetrics],
) -> dict[str, list[tuple[str, str]]]:
    """读取“属性标题\n股票列表”关系，保持原文词面，不推断隐含属性。"""

    candidate_list = list(candidates)
    matches: dict[str, list[tuple[str, str]]] = {item.stock_code: [] for item in candidate_list}
    active_attribute = ""
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        heading = _section_heading(line)
        if heading:
            active_attribute = heading
            continue
        if line in _SECTION_STOP_MARKERS or line.startswith(("1", "2", "3", "4", "5", "6", "7", "8", "9")):
            active_attribute = ""
            continue
        if not active_attribute:
            continue
        if len(line) > 80 or any(marker in line for marker in ("。", "；", ";")):
            # 长段落里的股票提及不继承上一节标题；交给句内明确关系解析。
            continue
        for candidate in candidate_list:
            if _candidate_mention(line, candidate):
                matches[candidate.stock_code].append((active_attribute, line))
    return matches


def _normalizer(alias_map: Mapping[str, str] | None):
    aliases = {str(k).strip(): str(v).strip() for k, v in (alias_map or {}).items() if str(k).strip() and str(v).strip()}
    return lambda value: aliases.get(value, value)


def extract_review_attributes(
    text: str,
    candidates: Iterable[CandidateMetrics],
    *,
    alias_map: Mapping[str, str] | None = None,
    source_title: str = "",
    source_url: str = "",
) -> dict[str, list[ReviewAttributeEvidence]]:
    """按候选代码返回证据；未提及与特殊条件也返回一条状态记录。"""

    normalise = _normalizer(alias_map)
    candidate_list = list(candidates)
    by_key = {item.stock_code: item for item in candidate_list}
    results: dict[str, list[ReviewAttributeEvidence]] = {item.stock_code: [] for item in candidate_list}
    mentioned: dict[str, bool] = {item.stock_code: False for item in candidate_list}

    # 复盘常用“板块标题换行后列股票”的排版，例如“消费\n国芳集团，国光连锁”。
    # 这是原文明示关系，不是根据公开行业字段自动补关系。
    for code, section_matches in _section_attribute_matches(text, candidate_list).items():
        candidate = by_key[code]
        for original, sentence in section_matches:
            mentioned[code] = True
            ambiguous = any(marker in sentence for marker in _AMBIGUOUS_MARKERS)
            status: AttributeStatus = "特殊条件" if ambiguous else "明确匹配"
            results[code].append(ReviewAttributeEvidence(
                code, candidate.stock_name, status, original,
                normalise(original) if status == "明确匹配" else "", sentence,
                source_title, source_url,
            ))

    for sentence in _sentences(text):
        for candidate in candidate_list:
            if not _candidate_mention(sentence, candidate):
                continue
            mentioned[candidate.stock_code] = True
            found = False
            # 用去空白后的句子计算前缀，兼容行情简称内部空格与原文无空格的差异。
            match_sentence = _normalise_match_text(sentence)
            stock_index = match_sentence.find(_normalise_match_text(candidate.stock_name))
            if stock_index < 0:
                stock_index = match_sentence.find(_normalise_match_text(candidate.stock_code))
            if stock_index >= 0:
                prefix = match_sentence[:stock_index]
                prefix = re.split(r"[。！？；;，,、\n]", prefix)[-1]
                prefix = re.sub(r"^[\s#>*_`\-+0-9.（）()]+|[\s：:]+$", "", prefix)
                if (
                    re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9+#/&·-]{1,10}", prefix or "")
                    and not prefix.endswith(("板块", "概念", "题材", "属性"))
                ):
                    ambiguous = any(marker in sentence for marker in _AMBIGUOUS_MARKERS)
                    status: AttributeStatus = "特殊条件" if ambiguous else "明确匹配"
                    results[candidate.stock_code].append(ReviewAttributeEvidence(
                        candidate.stock_code, candidate.stock_name, status, prefix,
                        normalise(prefix) if status == "明确匹配" else "", sentence,
                        source_title, source_url,
                    ))
                    found = True
            table_attributes = _table_attributes(sentence, candidate)
            if table_attributes:
                ambiguous = any(marker in sentence for marker in _AMBIGUOUS_MARKERS)
                status: AttributeStatus = "特殊条件" if ambiguous else "明确匹配"
                for original in table_attributes:
                    results[candidate.stock_code].append(ReviewAttributeEvidence(
                        candidate.stock_code, candidate.stock_name, status, original,
                        normalise(original) if status == "明确匹配" else "", sentence,
                        source_title, source_url,
                    ))
                found = True
            for match in _RELATION_RE.finditer(sentence):
                stock_text = match.group("stock")
                if not _candidate_in_text(stock_text, candidate):
                    continue
                original = _clean_attribute(match.group("attr"))
                ambiguous = any(marker in sentence for marker in _AMBIGUOUS_MARKERS)
                status: AttributeStatus = "特殊条件" if ambiguous or not original else "明确匹配"
                results[candidate.stock_code].append(ReviewAttributeEvidence(
                    candidate.stock_code, candidate.stock_name, status, original,
                    normalise(original) if status == "明确匹配" else "", sentence, source_title, source_url,
                ))
                found = True
            for match in _REVERSE_RE.finditer(sentence):
                original = _clean_attribute(match.group("attr"))
                stock_text = match.group("stocks")
                if not _candidate_in_text(stock_text, candidate):
                    continue
                # 只有候选名字出现在属性后的同一句中，才建立明确关系。
                ambiguous = any(marker in sentence for marker in _AMBIGUOUS_MARKERS)
                status = "特殊条件" if ambiguous else "明确匹配"
                results[candidate.stock_code].append(ReviewAttributeEvidence(
                    candidate.stock_code, candidate.stock_name, status, original,
                    normalise(original) if status == "明确匹配" else "", sentence, source_title, source_url,
                ))
                found = True
            if not found and not results[candidate.stock_code]:
                results[candidate.stock_code].append(ReviewAttributeEvidence(
                    candidate.stock_code, candidate.stock_name, "特殊条件", evidence_text=sentence,
                    source_title=source_title, source_url=source_url,
                ))

    for code, candidate in by_key.items():
        if not mentioned[code]:
            results[code] = [ReviewAttributeEvidence(code, candidate.stock_name, "没有提及", source_title=source_title, source_url=source_url)]
        else:
            unique: dict[tuple[str, str, str], ReviewAttributeEvidence] = {}
            for item in results[code]:
                unique[(item.status, item.original_attribute, item.evidence_text)] = item
            results[code] = list(unique.values()) or [ReviewAttributeEvidence(code, candidate.stock_name, "特殊条件", source_title=source_title, source_url=source_url)]
    return results


def apply_review_attributes(
    candidates: Iterable[CandidateMetrics],
    evidence_by_code: Mapping[str, Iterable[ReviewAttributeEvidence]],
) -> list[CandidateMetrics]:
    result: list[CandidateMetrics] = []
    for candidate in candidates:
        evidence = list(evidence_by_code.get(candidate.stock_code, ()))
        explicit = [item for item in evidence if item.status == "明确匹配" and item.original_attribute]
        status: AttributeStatus = "明确匹配" if explicit else ("特殊条件" if any(item.status == "特殊条件" for item in evidence) else "没有提及")
        # 展示/排序使用人工别名归一化后的属性；证据中仍完整保留原词。
        attrs = list(dict.fromkeys(item.normalized_attribute or item.original_attribute for item in explicit))
        result.append(candidate.model_copy(update={
            "review_attribute_status": status,
            "review_attributes": attrs,
            "attribute_evidence": [item.as_dict() for item in evidence],
        }))
    return result


def assign_same_attribute_orders(candidates: Iterable[CandidateMetrics]) -> list[CandidateMetrics]:
    """按首次封板时间逐属性排序，使用竞赛式名次（1、2、2、4）。"""

    items = list(candidates)
    grouped: dict[str, list[CandidateMetrics]] = {}
    for item in items:
        if item.review_attribute_status != "明确匹配" or not item.first_seal_time:
            continue
        for attr in item.review_attributes:
            grouped.setdefault(attr, []).append(item)

    orders: dict[str, dict[str, int]] = {}
    for attr, group in grouped.items():
        ordered = sorted(group, key=lambda item: (item.first_seal_time or "99:99:99", item.stock_code))
        rank_by_code: dict[str, int] = {}
        previous_time: str | None = None
        previous_rank = 0
        for index, item in enumerate(ordered, 1):
            if item.first_seal_time == previous_time:
                rank = previous_rank
            else:
                rank = index
            rank_by_code[item.stock_code] = rank
            previous_time, previous_rank = item.first_seal_time, rank
        orders[attr] = rank_by_code

    return [item.model_copy(update={"same_attribute_orders": {attr: values[item.stock_code] for attr, values in orders.items() if item.stock_code in values}}) for item in items]


__all__ = ["ReviewAttributeEvidence", "apply_review_attributes", "assign_same_attribute_orders", "extract_review_attributes"]
