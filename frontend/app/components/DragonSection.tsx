"use client";

import {
  ChangeEvent,
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import { Job, requestLocal } from "../lib/review-api";

export type DragonGeneratedReview = {
  trade_date: string;
  period_stage: string;
  market_core: string;
  expectation_point: string;
  negative_feedback: string;
  effective_directions: string;
  tomorrow_tasks: string;
  failure_conditions: string;
  user_notes: string;
  source_text: string;
  source_title: string;
  source_url: string;
};

type Props = {
  token: string;
  serviceConnected: boolean;
  defaultTradeDate: string;
  model: string;
  apiKeyConfigured: boolean;
  currentReviewText?: string;
  currentReviewSourceUrl?: string;
  currentReviewSourceTitle?: string;
  generatedReview?: DragonGeneratedReview;
  onNotice: (message: string) => void;
};

type JsonRecord = Record<string, unknown>;
type SnapshotKey =
  | "period_stage"
  | "market_core"
  | "expectation_point"
  | "negative_feedback"
  | "effective_directions"
  | "tomorrow_tasks"
  | "failure_conditions"
  | "user_notes"
  | "source_text";

type DragonSnapshot = {
  trade_date: string;
  period_stage: string;
  market_core: string;
  expectation_point: string;
  negative_feedback: string;
  effective_directions: string;
  tomorrow_tasks: string;
  failure_conditions: string;
  user_notes: string;
  source_text: string;
  source_title: string;
  source_url: string;
  confirmed_at: string;
};

type DragonStatus = {
  api_key_configured: boolean;
  market_provider_configured: boolean;
  knowledge_documents: number;
  knowledge_chunks: number;
  rules_count: number;
};

type DragonRule = {
  id: string;
  name: string;
  field: string;
  calculation: string;
  comparison: string;
  threshold: string;
  is_hard: boolean;
  missing_behavior: string;
  enabled: boolean;
};

type DragonRuleVersion = {
  id: string;
  name: string;
  note: string;
  is_active: boolean;
  created_at: string;
  rules: DragonRule[];
};

type DragonDocument = {
  id: string;
  filename: string;
  file_type: string;
  tags: string[];
  chunk_count: number;
  imported_at: string;
};

type DragonEvidence = {
  id: string;
  source_name: string;
  excerpt: string;
  tags: string[];
  score: number | null;
};

type DragonCheck = {
  rule_name: string;
  actual: string;
  standard: string;
  status: string;
  is_hard: boolean;
};

type DragonCandidate = {
  stock_code: string;
  stock_name: string;
  basic_pass: boolean;
  conclusion: string;
  historical_recognition: string;
  current_review_fit: string;
  layout_task: string;
  expectation_point: string;
  guided_point: string;
  evidence_refs: DragonEvidence[];
  history_dates: string[];
  analysis: JsonRecord;
  checks: DragonCheck[];
  candidate_bucket: string;
  metrics: JsonRecord;
  review_attribute_status: string;
  review_attributes: string[];
  same_attribute_orders: JsonRecord;
  attribute_evidence: JsonRecord[];
};

type DragonRecord = {
  id: string;
  job_id: string;
  trade_date: string;
  created_at: string;
  status: string;
  standard_version: string;
  snapshot: DragonSnapshot | null;
  candidates: DragonCandidate[];
  raw: unknown;
};

type DragonJob = Job<unknown> & { job_id?: string };
type RuleDraft = Omit<DragonRule, "id">;

const DRAGON_API = "/api/dragon";

const emptyStatus: DragonStatus = {
  api_key_configured: false,
  market_provider_configured: false,
  knowledge_documents: 0,
  knowledge_chunks: 0,
  rules_count: 0,
};

const emptyRule: RuleDraft = {
  name: "",
  field: "",
  calculation: "",
  comparison: "<=",
  threshold: "",
  is_hard: false,
  missing_behavior: "保留",
  enabled: true,
};

const snapshotFields: Array<{
  key: SnapshotKey;
  label: string;
  placeholder: string;
}> = [
  { key: "period_stage", label: "周期阶段", placeholder: "例如：退潮末端 / 修复初期" },
  { key: "market_core", label: "市场核心", placeholder: "当日核心股票、情绪锚或主线" },
  { key: "expectation_point", label: "超预期点", placeholder: "当日超预期信号" },
  { key: "negative_feedback", label: "负反馈", placeholder: "亏钱效应、断板反馈等" },
  { key: "effective_directions", label: "有效方向 / 属性", placeholder: "有持续性的方向、题材或属性" },
  { key: "tomorrow_tasks", label: "明日布局任务", placeholder: "仅填写用户确认的任务" },
  { key: "failure_conditions", label: "失效条件", placeholder: "周期或方向失效信号" },
  { key: "user_notes", label: "用户补充结论", placeholder: "可选：补充当天判断边界" },
  { key: "source_text", label: "已载入分析文本", placeholder: "布局分析生成后会自动带入；此处内容可修改，确认后才进入 Dragon" },
];

function emptySnapshot(tradeDate: string): DragonSnapshot {
  return {
    trade_date: tradeDate,
    period_stage: "",
    market_core: "",
    expectation_point: "",
    negative_feedback: "",
    effective_directions: "",
    tomorrow_tasks: "",
    failure_conditions: "",
    user_notes: "",
    source_text: "",
    source_title: "",
    source_url: "",
    confirmed_at: "",
  };
}

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function asText(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function displayValue(value: unknown, fallback = ""): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map((item) => displayValue(item)).filter(Boolean).join("；");
  if (isRecord(value)) return JSON.stringify(value);
  return fallback;
}

function asBool(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asStrings(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => asText(item)).filter(Boolean);
  if (typeof value === "string") {
    return value.split(/[,，、；;\n]/).map((item) => item.trim()).filter(Boolean);
  }
  return [];
}

function hasRelevantBreakSuspicion(metrics: JsonRecord): boolean {
  const firstSeal = asText(metrics.first_seal_time);
  return (
    asBool(metrics.break_suspected) &&
    /^\d{2}:\d{2}/.test(firstSeal) &&
    firstSeal.slice(0, 5) < "13:00"
  );
}

function asJoinedText(value: unknown): string {
  return Array.isArray(value) ? asStrings(value).join("；") : asText(value);
}

function normalizeMissingBehavior(value: unknown): "保留" | "淘汰" {
  const text = asText(value).trim().toLowerCase();
  return text === "淘汰" || text === "eliminate" ? "淘汰" : "保留";
}

function recordFrom(payload: unknown, key?: string): JsonRecord {
  if (!isRecord(payload)) return {};
  if (key && isRecord(payload[key])) return payload[key] as JsonRecord;
  return payload;
}

function arrayFrom(payload: unknown, key: string): unknown[] {
  if (Array.isArray(payload)) return payload;
  if (!isRecord(payload)) return [];
  const value = payload[key] ?? payload.items ?? payload.results ?? payload.records;
  return Array.isArray(value) ? value : [];
}

function normalizeSnapshot(payload: unknown, tradeDate: string): DragonSnapshot {
  const value = recordFrom(payload, "snapshot");
  return {
    trade_date: asText(value.trade_date, tradeDate),
    period_stage: asText(value.period_stage),
    market_core: asText(value.market_core),
    expectation_point: asJoinedText(value.expectation_point ?? value.positive_surprises),
    negative_feedback: asJoinedText(value.negative_feedback),
    effective_directions: asJoinedText(value.effective_directions),
    tomorrow_tasks: asJoinedText(value.tomorrow_tasks ?? value.layout_tasks),
    failure_conditions: asJoinedText(value.failure_conditions),
    user_notes: asText(value.user_notes),
    source_text: asText(value.source_text),
    source_title: asText(value.source_title),
    source_url: asText(value.source_url),
    confirmed_at: asText(value.confirmed_at, asBool(value.is_confirmed) ? "已确认" : ""),
  };
}

function normalizeStatus(payload: unknown): DragonStatus {
  const value = recordFrom(payload, "status");
  const knowledge = isRecord(value.knowledge) ? value.knowledge : {};
  return {
    api_key_configured: asBool(value.api_key_configured, asBool(value.deepseek_configured)),
    market_provider_configured: asBool(value.market_provider_configured, asBool(value.market_ready)),
    knowledge_documents: asNumber(value.knowledge_documents, asNumber(knowledge.documents)),
    knowledge_chunks: asNumber(value.knowledge_chunks, asNumber(knowledge.chunks)),
    rules_count: asNumber(value.rules_count),
  };
}

function normalizeRule(payload: unknown): DragonRule {
  const value = isRecord(payload) ? payload : {};
  return {
    id: asText(value.id, asText(value.rule_id)),
    name: asText(value.name, asText(value.rule_name, "未命名规则")),
    field: asText(value.field, asText(value.data_field)),
    calculation: asText(value.calculation, asText(value.calculation_method, asText(value.formula))),
    comparison: asText(value.comparison, asText(value.operator, "≤")),
    threshold: displayValue(value.threshold),
    is_hard: asBool(value.is_hard, asBool(value.hard_condition)),
    missing_behavior: normalizeMissingBehavior(
      value.missing_behavior ?? value.missing_policy,
    ),
    enabled: asBool(value.enabled, true),
  };
}

function normalizeRuleVersion(payload: unknown): DragonRuleVersion {
  const value = isRecord(payload) ? payload : {};
  return {
    id: asText(value.version_id, asText(value.id)),
    name: asText(value.name, "未命名版本"),
    note: asText(value.note),
    is_active: asBool(value.is_active),
    created_at: asText(value.created_at),
    rules: Array.isArray(value.rules) ? value.rules.map(normalizeRule) : [],
  };
}

function normalizeDocument(payload: unknown): DragonDocument {
  const value = isRecord(payload) ? payload : {};
  return {
    id: asText(value.id, asText(value.document_id)),
    filename: asText(value.filename, asText(value.name, "未命名资料")),
    file_type: asText(value.file_type, asText(value.format)),
    tags: asStrings(value.tags),
    chunk_count: asNumber(value.chunk_count, asNumber(value.chunks)),
    imported_at: asText(value.imported_at, asText(value.created_at)),
  };
}

function normalizeEvidence(payload: unknown): DragonEvidence {
  if (typeof payload === "string") {
    return {
      id: payload,
      source_name: payload,
      excerpt: "",
      tags: [],
      score: null,
    };
  }
  const value = isRecord(payload) ? payload : {};
  const score =
    value.score ??
    value.retrieval_score ??
    value.semantic_score ??
    value.fts_score ??
    value.exact_score;
  return {
    id: asText(value.id, asText(value.chunk_id)),
    source_name: asText(value.source_name, asText(value.filename, asText(value.title, "未命名来源"))),
    excerpt: asText(value.excerpt, asText(value.content, asText(value.text))),
    tags: asStrings(value.tags),
    score: typeof score === "number" ? score : null,
  };
}

function normalizeCandidate(payload: unknown): DragonCandidate {
  const value = isRecord(payload) ? payload : {};
  const rawChecks = Array.isArray(value.checks)
    ? value.checks
    : Array.isArray(value.rule_checks)
      ? value.rule_checks
      : [];
  return {
    stock_code: asText(value.stock_code, asText(value.code)),
    stock_name: asText(value.stock_name, asText(value.name, "未命名候选")),
    basic_pass: asBool(value.basic_pass),
    conclusion: asText(value.conclusion, "待分析"),
    historical_recognition: asText(value.historical_recognition),
    current_review_fit: asText(value.current_review_fit),
    layout_task: asText(value.layout_task),
    expectation_point: asText(value.expectation_point),
    guided_point: asText(value.guided_point),
    evidence_refs: Array.isArray(value.evidence_refs)
      ? value.evidence_refs.map(normalizeEvidence)
      : [],
    history_dates: asStrings(value.history_dates),
    analysis: isRecord(value.analysis) ? value.analysis : {},
    checks: rawChecks.map((item) => {
      const check = isRecord(item) ? item : {};
      return {
        rule_name: asText(check.rule_name, asText(check.name, "未命名检查项")),
        actual: displayValue(check.actual ?? check.actual_value, "—"),
        standard: displayValue(check.standard ?? check.expected ?? check.threshold, "—"),
        status: asText(check.status, "数据缺失"),
        is_hard: asBool(check.is_hard, asBool(check.hard_condition)),
      };
    }),
    candidate_bucket: asText(value.candidate_bucket, asBool(value.basic_pass) ? "qualified" : "excluded"),
    metrics: isRecord(value.metrics) ? value.metrics : {},
    review_attribute_status: asText(value.review_attribute_status, "没有提及"),
    review_attributes: asStrings(value.review_attributes),
    same_attribute_orders: isRecord(value.same_attribute_orders) ? value.same_attribute_orders : {},
    attribute_evidence: Array.isArray(value.attribute_evidence)
      ? value.attribute_evidence.filter(isRecord)
      : [],
  };
}

function candidatesFrom(payload: unknown): DragonCandidate[] {
  const value = recordFrom(payload, "result");
  const candidates = arrayFrom(value, "candidates");
  if (candidates.length) return candidates.map(normalizeCandidate);
  if (asText(value.stock_code) || asText(value.stock_name)) return [normalizeCandidate(value)];
  const records = arrayFrom(value, "records");
  return records.flatMap((item) => candidatesFrom(item));
}

function normalizeRecord(payload: unknown): DragonRecord {
  const value = isRecord(payload) ? payload : {};
  const context = isRecord(value.context) ? value.context : {};
  const snapshot = value.snapshot ?? value.review_snapshot ?? context.review_snapshot;
  const result = isRecord(value.result) ? value.result : value;
  const screening = isRecord(context.screening) ? context.screening : {};
  const candidate = asText(result.stock_code) || asText(result.stock_name)
    ? normalizeCandidate({ ...result, checks: result.checks ?? screening.checks })
    : null;
  return {
    id: asText(value.id, asText(value.analysis_id)),
    job_id: asText(value.job_id),
    trade_date: asText(value.trade_date),
    created_at: asText(value.created_at, asText(value.finished_at)),
    status: asText(value.status, "已完成"),
    standard_version: asText(value.standard_version, asText(value.rule_version, "未版本化")),
    snapshot: isRecord(snapshot) ? normalizeSnapshot(snapshot, asText(value.trade_date)) : null,
    candidates: candidate ? [candidate] : candidatesFrom(value),
    raw: value.raw_result ?? value.result ?? value,
  };
}

function applyGeneratedReview(
  snapshot: DragonSnapshot,
  generatedReview?: DragonGeneratedReview,
): DragonSnapshot {
  if (
    !generatedReview ||
    generatedReview.trade_date !== snapshot.trade_date ||
    snapshot.confirmed_at
  ) {
    return snapshot;
  }
  return {
    ...snapshot,
    ...generatedReview,
    confirmed_at: "",
  };
}

function ModelAnalysisView({ value }: { value: JsonRecord }) {
  return (
    <div className="dragon-candidate-analysis">
      {Object.entries(value).map(([key, item]) => (
        <div key={key}>
          <b>{key}：</b>
          {Array.isArray(item) ? (
            <ul>{item.map((entry, index) => <li key={index}>{displayValue(entry, "—")}</li>)}</ul>
          ) : isRecord(item) ? (
            <pre>{JSON.stringify(item, null, 2)}</pre>
          ) : (
            <span>{displayValue(item, "—")}</span>
          )}
        </div>
      ))}
    </div>
  );
}

function groupAnalysisRecords(records: DragonRecord[]): DragonRecord[] {
  const grouped = new Map<string, DragonRecord>();
  for (const record of records) {
    const key = record.job_id || record.id;
    const existing = grouped.get(key);
    if (!existing) {
      grouped.set(key, { ...record, candidates: [...record.candidates], raw: [record.raw] });
      continue;
    }
    existing.candidates.push(...record.candidates);
    existing.raw = [...(Array.isArray(existing.raw) ? existing.raw : [existing.raw]), record.raw];
  }
  return [...grouped.values()];
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = String(reader.result ?? "");
      resolve(value.includes(",") ? value.split(",", 2)[1] : value);
    };
    reader.onerror = () => reject(new Error("读取资料失败，请重新选择"));
    reader.readAsDataURL(file);
  });
}

function dragonRequest<T>(token: string, path: string, init: RequestInit = {}): Promise<T> {
  return requestLocal<T>(token, DRAGON_API + path, init);
}

async function waitForDragonJob(
  token: string,
  jobId: string,
  onUpdate: (job: DragonJob) => void,
): Promise<DragonJob> {
  let retries = 0;
  while (true) {
    await new Promise((resolve) => window.setTimeout(resolve, 1200));
    let job: DragonJob;
    try {
      job = await dragonRequest<DragonJob>(token, "/jobs/" + encodeURIComponent(jobId));
      retries = 0;
    } catch (error) {
      retries += 1;
      if (retries >= 6) throw error;
      onUpdate({
        status: "running",
        message: "本机服务响应较慢，仍在等待首板布局任务",
        current: 0,
        total: 1,
      });
      continue;
    }
    onUpdate(job);
    if (job.status === "failed") throw new Error(job.message || "首板布局任务失败");
    if (job.status === "succeeded") return job;
  }
}

function checkClass(status: string): string {
  if (status === "通过") return "pass";
  if (status === "不通过") return "fail";
  return "missing";
}

function conclusionClass(conclusion: string): string {
  if (conclusion === "重点") return "focus";
  if (conclusion === "排除") return "exclude";
  return "watch";
}

function bucketLabel(bucket: string): string {
  if (bucket === "qualified") return "合格候选 · 调用模型";
  if (bucket === "late_break_watch") return "午后炸板 · 单列观察";
  return "其他硬性条件 · 排除";
}

function candidateFailureSummary(candidate: DragonCandidate): string {
  const blockers = candidate.checks.filter(
    (check) => check.status === "不通过" || (check.is_hard && check.status === "数据缺失"),
  );
  if (!blockers.length) return candidate.basic_pass ? "基础标准全部通过" : "未返回具体未通过原因";
  return blockers.map((check) => check.rule_name).join("、");
}

function candidateFailureReasons(candidate: DragonCandidate): string[] {
  const reasons = candidate.checks
    .filter(
      (check) =>
        check.is_hard &&
        (check.status === "不通过" || check.status === "数据缺失"),
    )
    .map((check) => check.rule_name);
  return reasons.length ? [...new Set(reasons)] : ["其他硬性条件"];
}

function comparisonLabel(value: string): string {
  return {
    "<=": "≤",
    ">=": "≥",
    "!=": "≠",
    in: "包含",
    not_in: "不包含",
    exists: "存在",
    not_exists: "不存在",
    in_time_windows: "时间窗口内",
    none_at_or_after: "不得晚于",
  }[value] ?? value;
}

function thresholdForApi(rule: DragonRule): unknown {
  if (rule.comparison === "exists" || rule.comparison === "not_exists") return null;
  if (["in_time_windows", "in", "not_in"].includes(rule.comparison)) {
    try {
      const parsed = JSON.parse(rule.threshold);
      if (Array.isArray(parsed)) return parsed;
    } catch {
      // 用户也可以直接输入逗号分隔的时间窗口。
    }
    return rule.threshold.split(/[,，、；;]/).map((item) => item.trim()).filter(Boolean);
  }
  const normalized = rule.threshold.trim().toLowerCase();
  if (normalized === "true") return true;
  if (normalized === "false") return false;
  return rule.threshold;
}

export function DragonSection({
  token,
  serviceConnected,
  defaultTradeDate,
  model,
  apiKeyConfigured,
  currentReviewText = "",
  currentReviewSourceUrl = "",
  currentReviewSourceTitle = "",
  generatedReview,
  onNotice,
}: Props) {
  const [activeTab, setActiveTab] = useState<"today" | "rules" | "knowledge" | "records">("today");
  const [tradeDate, setTradeDate] = useState(defaultTradeDate);
  const [status, setStatus] = useState<DragonStatus>(emptyStatus);
  const [moduleReady, setModuleReady] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [snapshot, setSnapshot] = useState<DragonSnapshot>(() => emptySnapshot(defaultTradeDate));
  const [isSavingSnapshot, setIsSavingSnapshot] = useState(false);
  const [rules, setRules] = useState<DragonRule[]>([]);
  const [ruleVersions, setRuleVersions] = useState<DragonRuleVersion[]>([]);
  const [ruleVersionName, setRuleVersionName] = useState("");
  const [ruleVersionNote, setRuleVersionNote] = useState("");
  const [ruleDraft, setRuleDraft] = useState<RuleDraft>(emptyRule);
  const [editingRuleId, setEditingRuleId] = useState("");
  const [isPublishingRuleVersion, setIsPublishingRuleVersion] = useState(false);
  const [rulesDirty, setRulesDirty] = useState(false);
  const [documents, setDocuments] = useState<DragonDocument[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [tagDrafts, setTagDrafts] = useState<Record<string, string>>({});
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<DragonEvidence[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [selectedDocumentId, setSelectedDocumentId] = useState("");
  const [documentChunks, setDocumentChunks] = useState<DragonEvidence[]>([]);
  const [records, setRecords] = useState<DragonRecord[]>([]);
  const [selectedRecordId, setSelectedRecordId] = useState("");
  const [candidates, setCandidates] = useState<DragonCandidate[]>([]);
  const [candidateView, setCandidateView] = useState<"pass" | "fail">("pass");
  const [passedConclusion, setPassedConclusion] = useState<"全部" | "重点" | "观察" | "排除">("全部");
  const [failureCategory, setFailureCategory] = useState("全部");
  const [dragonJob, setDragonJob] = useState<DragonJob | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isSavingOutput, setIsSavingOutput] = useState(false);

  const selectedRecord = useMemo(
    () => records.find((record) => record.id === selectedRecordId) ?? null,
    [records, selectedRecordId],
  );
  const activeRuleVersionId = useMemo(
    () => ruleVersions.find((version) => version.is_active)?.id ?? "",
    [ruleVersions],
  );
  const ruleVersionNames = useMemo(
    () => new Map(ruleVersions.map((version) => [version.id, version.name])),
    [ruleVersions],
  );
  const snapshotConfirmed = Boolean(snapshot.confirmed_at);
  const hasRules = rules.some((rule) => rule.enabled);
  const apiConfigured = status.api_key_configured || apiKeyConfigured;
  const canRun = Boolean(token) && snapshotConfirmed && hasRules && Boolean(activeRuleVersionId) && !rulesDirty && status.market_provider_configured && apiConfigured && !isAnalyzing;
  const passedCandidates = useMemo(
    () => candidates.filter((candidate) => candidate.basic_pass),
    [candidates],
  );
  const failedCandidates = useMemo(
    () => candidates.filter((candidate) => !candidate.basic_pass),
    [candidates],
  );
  const failureCategories = useMemo(
    () => [
      "全部",
      ...new Set(failedCandidates.flatMap(candidateFailureReasons)),
    ],
    [failedCandidates],
  );
  const visibleCandidates = useMemo(
    () => candidateView === "pass"
      ? passedCandidates.filter(
          (candidate) => passedConclusion === "全部" || candidate.conclusion === passedConclusion,
        )
      : failedCandidates.filter(
          (candidate) =>
            failureCategory === "全部" ||
            candidateFailureReasons(candidate).includes(failureCategory),
        ),
    [candidateView, failedCandidates, failureCategory, passedCandidates, passedConclusion],
  );

  const loadDashboard = useCallback(async () => {
    if (!token) {
      setModuleReady(false);
      return;
    }
    setIsLoading(true);
    const results = await Promise.allSettled([
      dragonRequest<unknown>(token, "/status"),
      dragonRequest<unknown>(token, "/snapshot?trade_date=" + encodeURIComponent(tradeDate)),
      dragonRequest<unknown>(token, "/rules"),
      dragonRequest<unknown>(token, "/rule-versions"),
      dragonRequest<unknown>(token, "/documents"),
      dragonRequest<unknown>(token, "/analyses?limit=200"),
      dragonRequest<unknown>(token, "/analyses?limit=200&trade_date=" + encodeURIComponent(tradeDate)),
    ]);
    const [statusResult, snapshotResult, rulesResult, ruleVersionsResult, documentsResult, recordsResult, todayRecordsResult] = results;
    if (statusResult.status === "fulfilled") {
      setStatus(normalizeStatus(statusResult.value));
      setModuleReady(true);
    } else {
      setModuleReady(false);
    }
    const loadedSnapshot = snapshotResult.status === "fulfilled"
      ? normalizeSnapshot(snapshotResult.value, tradeDate)
      : emptySnapshot(tradeDate);
    setSnapshot(applyGeneratedReview(loadedSnapshot, generatedReview));
    let activeVersion: DragonRuleVersion | null = null;
    if (ruleVersionsResult.status === "fulfilled") {
      const versions = arrayFrom(ruleVersionsResult.value, "versions").map(normalizeRuleVersion);
      setRuleVersions(versions);
      activeVersion = versions.find((version) => version.is_active) ?? versions[0] ?? null;
      if (activeVersion) {
        setRuleVersionName(activeVersion.name);
        setRuleVersionNote(activeVersion.note);
      }
    }
    if (activeVersion?.rules.length) setRules(activeVersion.rules);
    else if (rulesResult.status === "fulfilled") setRules(arrayFrom(rulesResult.value, "rules").map(normalizeRule));
    if (documentsResult.status === "fulfilled") setDocuments(arrayFrom(documentsResult.value, "documents").map(normalizeDocument));
    if (recordsResult.status === "fulfilled") {
      const nextRecords = groupAnalysisRecords(arrayFrom(recordsResult.value, "analyses").map(normalizeRecord));
      setRecords(nextRecords);
      setSelectedRecordId((current) => nextRecords.some((record) => record.id === current) ? current : nextRecords[0]?.id || "");
    }
    if (todayRecordsResult.status === "fulfilled") {
      const todayRecords = groupAnalysisRecords(arrayFrom(todayRecordsResult.value, "analyses").map(normalizeRecord));
      setCandidates(todayRecords[0]?.candidates ?? []);
    } else {
      setCandidates([]);
    }
    setRulesDirty(false);
    setIsLoading(false);
  }, [token, tradeDate, generatedReview]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadDashboard();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadDashboard]);

  useEffect(() => {
    if (defaultTradeDate) setTradeDate(defaultTradeDate);
  }, [defaultTradeDate]);

  useEffect(() => {
    setCandidates([]);
    setCandidateView("pass");
    setPassedConclusion("全部");
    setFailureCategory("全部");
    setDragonJob(null);
    setIsAnalyzing(false);
  }, [tradeDate]);

  useEffect(() => {
    if (candidates.length && !passedCandidates.length) setCandidateView("fail");
    if (!failureCategories.includes(failureCategory)) setFailureCategory("全部");
  }, [candidates.length, failureCategories, failureCategory, passedCandidates.length]);

  function updateSnapshot(key: SnapshotKey, value: string) {
    setSnapshot((current) => ({ ...current, [key]: value, confirmed_at: "" }));
  }

  async function saveSnapshot(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return onNotice("本机服务未连接，无法保存首板布局快照。");
    const hasConfirmedContent = snapshotFields.some((field) => snapshot[field.key].trim());
    if (!hasConfirmedContent) return onNotice("请至少填写一项复盘结论，或先载入现有复盘文本供确认。");
    setIsSavingSnapshot(true);
    try {
      const saved = await dragonRequest<unknown>(token, "/snapshot", {
        method: "POST",
        body: JSON.stringify({
          trade_date: tradeDate,
          period_stage: snapshot.period_stage,
          market_core: snapshot.market_core,
          positive_surprises: asStrings(snapshot.expectation_point),
          negative_feedback: asStrings(snapshot.negative_feedback),
          effective_directions: asStrings(snapshot.effective_directions),
          layout_tasks: asStrings(snapshot.tomorrow_tasks),
          failure_conditions: asStrings(snapshot.failure_conditions),
          user_notes: snapshot.user_notes,
          source_text: snapshot.source_text,
          source_title: snapshot.source_text.trim() ? (snapshot.source_title || "用户确认的复盘原文") : "",
          source_url: snapshot.source_url,
          confirm_as_layout: true,
        }),
      });
      const next = normalizeSnapshot(saved, tradeDate);
      setSnapshot({ ...next, confirmed_at: next.confirmed_at || new Date().toISOString() });
      onNotice("已确认并写入独立首板布局快照。只有这份内容会进入后续 API 上下文。");
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "保存今日布局结论失败");
    } finally {
      setIsSavingSnapshot(false);
    }
  }

  function editRule(rule: DragonRule) {
    setEditingRuleId(rule.id);
    setRuleDraft({
      name: rule.name,
      field: rule.field,
      calculation: rule.calculation,
      comparison: rule.comparison,
      threshold: rule.threshold,
      is_hard: rule.is_hard,
      missing_behavior: rule.missing_behavior,
      enabled: rule.enabled,
    });
  }

  function resetRule() {
    setEditingRuleId("");
    setRuleDraft(emptyRule);
  }

  function saveRule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const thresholdRequired = !["exists", "not_exists"].includes(ruleDraft.comparison);
    if (!ruleDraft.name.trim() || !ruleDraft.field.trim() || (thresholdRequired && !ruleDraft.threshold.trim())) {
      return onNotice("请填写检查项、对应数据字段和阈值。");
    }
    const nextRule: DragonRule = {
      ...ruleDraft,
      id: editingRuleId || "draft-" + Date.now(),
      name: ruleDraft.name.trim(),
      field: ruleDraft.field.trim(),
      threshold: ruleDraft.threshold.trim(),
    };
    setRules((current) =>
      editingRuleId
        ? current.map((rule) => rule.id === editingRuleId ? nextRule : rule)
        : [...current, nextRule],
    );
    setRulesDirty(true);
    resetRule();
    onNotice("规则已加入当前草稿；点击“保存为规则版本并启用”后才写入独立运行库。");
  }

  function toggleRule(rule: DragonRule) {
    setRules((current) =>
      current.map((item) =>
        item.id === rule.id ? { ...item, enabled: !item.enabled } : item,
      ),
    );
    setRulesDirty(true);
  }

  async function publishRuleVersion() {
    if (!token) return onNotice("本机服务未连接，无法保存规则版本。");
    if (!ruleVersionName.trim()) return onNotice("请填写规则版本名称。");
    if (!rules.length) return onNotice("请先新增至少一条基础标准。");
    setIsPublishingRuleVersion(true);
    try {
      await dragonRequest<unknown>(token, "/rule-versions", {
        method: "POST",
        body: JSON.stringify({
          name: ruleVersionName.trim(),
          note: ruleVersionNote.trim(),
          activate: true,
          rules: rules.map((rule) => ({
            name: rule.name,
            data_field: rule.field,
            calculation: rule.calculation,
            comparison: rule.comparison,
            threshold: thresholdForApi(rule),
            hard_condition: rule.is_hard,
            missing_policy: normalizeMissingBehavior(rule.missing_behavior),
            enabled: rule.enabled,
          })),
        }),
      });
      await loadDashboard();
      setRulesDirty(false);
      onNotice("规则版本已保存并启用。后续筛选会记录该版本。");
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "保存规则版本失败");
    } finally {
      setIsPublishingRuleVersion(false);
    }
  }

  async function bootstrapRules() {
    if (!token) return onNotice("本机服务未连接，无法初始化标准。");
    try {
      await dragonRequest<unknown>(token, "/rules/bootstrap", { method: "POST" });
      await loadDashboard();
      onNotice("已载入用户确认的首板基础硬规则 v1，可继续编辑并保存新版本。");
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "初始化首板基础标准失败");
    }
  }

  async function activateRuleVersion(version: DragonRuleVersion) {
    if (!token) return onNotice("本机服务未连接，无法切换规则版本。");
    try {
      await dragonRequest<unknown>(
        token,
        "/rule-versions/" + encodeURIComponent(version.id) + "/activate",
        { method: "POST", body: "{}" },
      );
      await loadDashboard();
      setRulesDirty(false);
      onNotice("已启用规则版本「" + version.name + "」。");
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "切换规则版本失败");
    }
  }

  async function deleteRuleVersion(version: DragonRuleVersion) {
    if (!token) return onNotice("本机服务未连接，无法删除规则版本。");
    if (version.is_active) return onNotice("请先启用另一个规则版本，再删除当前版本。");
    try {
      await dragonRequest<unknown>(
        token,
        "/rule-versions/" + encodeURIComponent(version.id),
        { method: "DELETE" },
      );
      await loadDashboard();
      onNotice("已删除规则版本「" + version.name + "」。");
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "删除规则版本失败");
    }
  }

  async function uploadDocument(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!token) return onNotice("本机服务未连接，无法导入历史模型资料。");
    setIsUploading(true);
    try {
      await dragonRequest<unknown>(token, "/documents", {
        method: "POST",
        body: JSON.stringify({
          filename: file.name,
          content_base64: await fileToBase64(file),
        }),
      });
      await loadDashboard();
      onNotice("资料已导入独立首板模型库，未写入现有复盘 RAG。");
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "导入历史模型资料失败");
    } finally {
      setIsUploading(false);
    }
  }

  async function saveTags(document: DragonDocument) {
    if (!token) return onNotice("本机服务未连接，无法保存模型标签。");
    try {
      await dragonRequest<unknown>(token, "/documents/" + encodeURIComponent(document.id) + "/tags", {
        method: "POST",
        body: JSON.stringify({ tags: asStrings(tagDrafts[document.id] ?? document.tags) }),
      });
      await loadDashboard();
      onNotice("模型标签已保存。");
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "保存模型标签失败");
    }
  }

  async function inspectChunks(document: DragonDocument) {
    if (!token) return;
    setSelectedDocumentId(document.id);
    try {
      const result = await dragonRequest<unknown>(
        token,
        "/documents/" + encodeURIComponent(document.id) + "/chunks?limit=10",
      );
      setDocumentChunks(arrayFrom(result, "chunks").map(normalizeEvidence));
    } catch (error) {
      setDocumentChunks([]);
      onNotice(error instanceof Error ? error.message : "读取 RAG 切片失败");
    }
  }

  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !searchQuery.trim()) return;
    setIsSearching(true);
    setSelectedDocumentId("");
    try {
      const result = await dragonRequest<unknown>(
        token,
        "/search?q=" + encodeURIComponent(searchQuery.trim()) + "&limit=10",
      );
      setSearchResults(arrayFrom(result, "results").map(normalizeEvidence));
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "测试检索失败");
    } finally {
      setIsSearching(false);
    }
  }

  async function runAnalysis() {
    if (!canRun) {
      return onNotice("生成前需确认今日布局结论、启用基础标准，并配置当日行情数据源和 DeepSeek。");
    }
    setIsAnalyzing(true);
    setDragonJob({ status: "pending", message: "正在创建首板布局任务", current: 0, total: 8 });
    try {
      const started = await dragonRequest<{ job_id: string; reused?: boolean }>(token, "/analyze-async", {
        method: "POST",
        body: JSON.stringify({
          trade_date: tradeDate,
          rule_version_id: activeRuleVersionId,
          model,
          thinking_enabled: true,
        }),
      });
      if (started.reused) onNotice("已接回同一日期的首板布局任务，不会重复调用模型。");
      const complete = await waitForDragonJob(token, started.job_id, setDragonJob);
      setCandidates(candidatesFrom(complete.result ?? complete));
      await loadDashboard();
      onNotice("首板布局结论已生成：基础不合格候选保持排除，不进入模型分析。");
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "生成首板布局结论失败");
    } finally {
      setIsAnalyzing(false);
    }
  }

  async function saveAnalysisOutput() {
    if (!token || !candidates.length) return onNotice("请先生成首板布局结论，再保存结果。");
    setIsSavingOutput(true);
    try {
      const saved = await dragonRequest<{ filename: string; path: string }>(
        token,
        "/analyses/export",
        {
          method: "POST",
          body: JSON.stringify({
            trade_date: tradeDate,
            job_id: dragonJob?.job_id || "",
          }),
        },
      );
      onNotice("首板布局结果已保存到 output：" + saved.filename);
    } catch (error) {
      onNotice(error instanceof Error ? error.message : "保存首板布局结果失败");
    } finally {
      setIsSavingOutput(false);
    }
  }

  const checklist = [
    { label: "今日复盘快照", done: snapshotConfirmed, detail: snapshotConfirmed ? "已由用户确认" : "待手工填写并确认" },
    { label: "基础标准", done: hasRules && Boolean(activeRuleVersionId) && !rulesDirty, detail: rulesDirty ? "当前草稿待保存为新版本" : activeRuleVersionId ? "已启用规则版本" : "待保存并启用规则版本" },
    { label: "当日行情", done: status.market_provider_configured, detail: status.market_provider_configured ? "数据源已配置" : "待提供 API 或日导出文件" },
    { label: "独立模型库", done: status.knowledge_chunks > 0, detail: status.knowledge_chunks > 0 ? String(status.knowledge_chunks) + " 条可检索切片" : "可稍后导入历史案例" },
  ];

  return (
    <div className="dragon-section">
      <section className="dragon-hero">
        <div>
          <span className="eyebrow">独立首板模型 · 本机私有数据</span>
          <h3>首板布局</h3>
          <p>候选先按用户标准完成三态检查；合格候选再结合独立历史模型库与已确认的当日复盘结论生成布局任务。</p>
        </div>
        <div className="dragon-hero-status">
          <span className={moduleReady && serviceConnected ? "ready-dot" : "empty-dot"} />
          <strong>{moduleReady && serviceConnected ? "独立模块已连接" : "等待本机 dragon 路由"}</strong>
          <small>仅访问 /api/dragon/*</small>
        </div>
      </section>

      <nav className="dragon-tabs" aria-label="首板布局功能">
        {(["today", "rules", "knowledge", "records"] as const).map((tab) => (
          <button
            className={activeTab === tab ? "active" : ""}
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
          >
            {{
              today: "今日布局",
              rules: "基础标准",
              knowledge: "历史模型库",
              records: "分析记录",
            }[tab]}
          </button>
        ))}
      </nav>

      {activeTab === "today" && (
        <>
          <section className="panel dragon-layout-panel">
            <div className="panel-heading">
              <div>
                <span className="section-number">01</span>
                <div>
                  <span className="eyebrow">A. 当日复盘 · 用户确认内容</span>
                  <h3>确认作为今日布局结论</h3>
                </div>
              </div>
              <input
                aria-label="首板布局日期"
                className="date-input"
                type="date"
                value={tradeDate}
                onChange={(event) => setTradeDate(event.target.value)}
              />
            </div>
            <p className="dragon-panel-intro">
              {generatedReview && generatedReview.trade_date === tradeDate
                ? "布局分析生成结果已自动带入下方草稿；你仍可修改，确认后才会进入首板分析。"
                : "尚无可带入的布局分析结果；可先生成布局分析，或载入当前复盘原文后手工确认。"}
            </p>
            <form className="dragon-snapshot-form" onSubmit={saveSnapshot}>
              <div className="dragon-snapshot-grid">
                {snapshotFields.map((field) => (
                  <label key={field.key}>
                    <span>{field.label}</span>
                    <textarea
                      placeholder={field.placeholder}
                      value={snapshot[field.key]}
                      onChange={(event) => updateSnapshot(field.key, event.target.value)}
                    />
                  </label>
                ))}
              </div>
              <div className="dragon-form-footer">
                <button
                  className="btn btn-secondary"
                  disabled={
                    !(
                      generatedReview?.trade_date === tradeDate &&
                      generatedReview.source_text.trim()
                    ) && !currentReviewText.trim()
                  }
                  type="button"
                  onClick={() => {
                    if (generatedReview?.trade_date === tradeDate) {
                      setSnapshot((current) =>
                        applyGeneratedReview(
                          { ...current, confirmed_at: "" },
                          generatedReview,
                        ),
                      );
                      return;
                    }
                    setSnapshot((current) => ({
                      ...current,
                      source_text: currentReviewText,
                      source_url: currentReviewSourceUrl,
                      source_title: currentReviewSourceTitle || current.source_title || "用户确认的复盘原文",
                      confirmed_at: "",
                    }));
                  }}
                >
                  {generatedReview?.trade_date === tradeDate
                    ? "重新载入布局分析结果"
                    : "载入当前复盘文本供修改"}
                </button>
                {generatedReview?.trade_date === tradeDate && currentReviewText.trim() && (
                  <button
                    className="btn btn-secondary"
                    type="button"
                    onClick={() => {
                      setSnapshot((current) => ({
                        ...current,
                        source_text: currentReviewText,
                        source_url: currentReviewSourceUrl,
                        source_title:
                          currentReviewSourceTitle || "用户确认的复盘原文",
                        confirmed_at: "",
                      }));
                    }}
                  >
                    载入原始复盘文本供修改
                  </button>
                )}
                {snapshot.source_url ? (
                  <a className="dragon-source-link" href={snapshot.source_url} target="_blank" rel="noreferrer">
                    已载入原文来源 →
                  </a>
                ) : (
                  <span className="dragon-source-missing">原文来源未载入</span>
                )}
                <span className={snapshotConfirmed ? "dragon-confirmed" : "dragon-pending"}>
                  {snapshotConfirmed
                    ? "已确认 · " + snapshot.confirmed_at.replace("T", " ")
                    : "未确认，不会进入 API 上下文"}
                </span>
                <button className="btn btn-primary" disabled={isSavingSnapshot || !token} type="submit">
                  {isSavingSnapshot ? "正在保存…" : "确认作为今日布局结论"}
                </button>
              </div>
            </form>
          </section>

          <section className="dragon-run-panel">
            <div>
              <span className="eyebrow">执行流程</span>
              <h3>抓取数据并生成首板布局结论</h3>
              <p>抓取 → 字段标准化 → 用户规则三态检查 → 按原因归类硬性不通过 → 独立 RAG 召回 → DeepSeek 批量结构化结论。</p>
            </div>
            <div className="dragon-run-actions">
              <button className="dragon-run-button" disabled={!canRun} type="button" onClick={runAnalysis}>
                <span>{isAnalyzing ? "正在执行首板布局…" : "抓取数据并生成首板布局结论"}</span>
                <small>{apiConfigured ? "仅向合格候选调用模型" : "待配置 DeepSeek API Key"}</small>
              </button>
              <button
                className="btn btn-secondary dragon-save-output"
                disabled={!candidates.length || isSavingOutput || !token}
                type="button"
                onClick={saveAnalysisOutput}
              >
                {isSavingOutput ? "正在保存…" : "保存本次结果到 output"}
              </button>
            </div>
          </section>

          <section aria-label="首板布局前置条件" className="dragon-checklist-grid">
            {checklist.map((item) => (
              <article className={item.done ? "done" : ""} key={item.label}>
                <span>{item.done ? "✓" : "·"}</span>
                <div>
                  <strong>{item.label}</strong>
                  <small>{item.detail}</small>
                </div>
              </article>
            ))}
          </section>

          {dragonJob && (
            <section className="dragon-job-card">
              <div>
                <span className="eyebrow">任务进度</span>
                <strong>{dragonJob.message}</strong>
              </div>
              <span>{dragonJob.current}/{dragonJob.total}</span>
              <div className="dragon-job-progress">
                <i style={{ width: Math.round((dragonJob.current / Math.max(dragonJob.total, 1)) * 100) + "%" }} />
              </div>
            </section>
          )}

          <section className="panel dragon-candidate-panel">
            <div className="panel-heading">
              <div>
                <span className="section-number">02</span>
                <div>
                  <span className="eyebrow">B. 客观事实 · 规则检查</span>
                  <h3>当日候选</h3>
                </div>
              </div>
              <span className="hint">
                {candidates.length
                  ? `${candidates.length} 只 · ${candidates.filter((item) => item.candidate_bucket === "qualified").length} 合格 · ${candidates.filter((item) => item.candidate_bucket === "late_break_watch").length} 午后炸板 · ${candidates.filter((item) => hasRelevantBreakSuspicion(item.metrics)).length} 疑似标记`
                  : "尚未运行"}
              </span>
            </div>
            {candidates.length > 0 && (
              <div className="dragon-candidate-navigation" aria-label="候选通过状态">
                <div className="dragon-candidate-status-tabs">
                  <button
                    className={candidateView === "pass" ? "active" : ""}
                    type="button"
                    onClick={() => setCandidateView("pass")}
                  >
                    通过 <span>{passedCandidates.length}</span>
                  </button>
                  <button
                    className={candidateView === "fail" ? "active" : ""}
                    type="button"
                    onClick={() => setCandidateView("fail")}
                  >
                    不通过 <span>{failedCandidates.length}</span>
                  </button>
                </div>
                {candidateView === "fail" && (
                  <div className="dragon-failure-categories" aria-label="不通过原因归类">
                    {failureCategories.map((category) => (
                      <button
                        className={failureCategory === category ? "active" : ""}
                        key={category}
                        type="button"
                        onClick={() => setFailureCategory(category)}
                      >
                        {category}
                        <span>
                          {category === "全部"
                            ? failedCandidates.length
                            : failedCandidates.filter((candidate) => candidateFailureReasons(candidate).includes(category)).length}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
                {candidateView === "pass" && (
                  <div className="dragon-conclusion-categories" aria-label="通过候选的模型结论">
                    {(["全部", "重点", "观察", "排除"] as const).map((conclusion) => (
                      <button
                        className={passedConclusion === conclusion ? "active" : ""}
                        key={conclusion}
                        type="button"
                        onClick={() => setPassedConclusion(conclusion)}
                      >
                        {conclusion}
                        <span>
                          {conclusion === "全部"
                            ? passedCandidates.length
                            : passedCandidates.filter((candidate) => candidate.conclusion === conclusion).length}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
            {candidates.length ? (
              visibleCandidates.length ? (
                <div className="dragon-candidate-list">
                  {visibleCandidates.map((candidate) => (
                  <article className="dragon-candidate-card" key={candidate.stock_code + candidate.stock_name}>
                    <div className="dragon-candidate-head">
                      <div>
                        <strong>{candidate.stock_name}</strong>
                        <small>{candidate.stock_code || "代码待返回"}</small>
                      </div>
                      <span className={conclusionClass(candidate.conclusion)}>{candidate.conclusion}</span>
                    </div>
                    <small className="dragon-candidate-bucket">{bucketLabel(candidate.candidate_bucket)}</small>
                    <div className="dragon-candidate-summary">
                      <span className={candidate.basic_pass ? "pass" : "fail"}>{candidate.basic_pass ? "通过" : "未通过"}</span>
                      <p><b>原因：</b>{candidateFailureSummary(candidate)}</p>
                    </div>
                    <p className="dragon-attribute-line">
                      <b>复盘属性：</b>{candidate.review_attribute_status}
                      {candidate.review_attributes.length ? ` · ${candidate.review_attributes.join("、")}` : ""}
                      {Object.keys(candidate.same_attribute_orders).length
                        ? ` · 同属性顺序 ${Object.entries(candidate.same_attribute_orders).map(([key, value]) => `${key} ${String(value)}`).join("；")}`
                        : ""}
                    </p>
                    {hasRelevantBreakSuspicion(candidate.metrics) && (
                      <p className="dragon-attribute-line">
                        <b>炸板标记：</b>
                        {asStrings(candidate.metrics.break_suspicion_reasons).join("；") || "分钟行情未完整还原炸板时点"}
                      </p>
                    )}
                    <details className="dragon-candidate-details">
                      <summary>查看完整规则与证据</summary>
                      {candidate.checks.length > 0 && (
                        <div className="dragon-rule-checks">
                          {candidate.checks.map((check, index) => (
                            <div key={check.rule_name + index}>
                              <span>{check.rule_name}{check.is_hard ? " · 硬性" : ""}</span>
                              <small>实际 {check.actual} / 标准 {check.standard}</small>
                              <b className={checkClass(check.status)}>{check.status}</b>
                            </div>
                          ))}
                        </div>
                      )}
                      <div className="dragon-candidate-facts">
                        <span>首封 {displayValue(candidate.metrics.first_seal_time, "数据缺失")}</span>
                        <span>最终封板 {displayValue(candidate.metrics.last_seal_time, "数据缺失")}</span>
                        <span>最终封单 {displayValue(candidate.metrics.final_order_amount, "数据缺失")}</span>
                        <span>流通值 {displayValue(candidate.metrics.float_market_cap, "数据缺失")}</span>
                      </div>
                      {candidate.basic_pass && (
                        Object.keys(candidate.analysis).length ? (
                          <ModelAnalysisView value={candidate.analysis} />
                        ) : (
                          <div className="dragon-candidate-analysis">
                            <p>{candidate.layout_task || candidate.current_review_fit || candidate.historical_recognition || "等待批量模型结论"}</p>
                          </div>
                        )
                      )}
                      <div className="dragon-record-candidate">
                        <b>历史时间：</b>
                        <p>{candidate.history_dates.length ? candidate.history_dates.join("、") : "未匹配"}</p>
                      </div>
                    </details>
                  </article>
                  ))}
                </div>
              ) : (
                <div className="dragon-empty-state">
                  <strong>当前分类没有候选</strong>
                  <p>可切换“通过 / 不通过”，或选择其他不通过原因查看。</p>
                </div>
              )
            ) : (
              <div className="dragon-empty-state">
                <strong>尚无当日候选</strong>
                <p>用户提供行情数据源、基础标准并确认复盘快照后，候选与逐项三态检查会显示在这里。</p>
              </div>
            )}
          </section>
        </>
      )}

      {activeTab === "rules" && (
        <>
          <section className="panel dragon-rule-editor">
            <div className="panel-heading">
              <div>
                <span className="section-number">01</span>
                <div>
                  <span className="eyebrow">用户标准 · 不自动评分</span>
                  <h3>{editingRuleId ? "修改基础标准" : "新增基础标准"}</h3>
                </div>
              </div>
              {editingRuleId && (
                <button className="btn btn-secondary" type="button" onClick={resetRule}>
                  取消编辑
                </button>
              )}
            </div>
            <p className="dragon-panel-intro">
              只保存用户给出的字段、比较方式、阈值、硬性条件和缺失处理。系统只返回“通过 / 不通过 / 数据缺失”，不发明权重或综合评分。
            </p>
            <form className="dragon-rule-form" onSubmit={saveRule}>
              <label>
                <span>检查项</span>
                <input
                  placeholder="例如：首封时间"
                  value={ruleDraft.name}
                  onChange={(event) => setRuleDraft((current) => ({ ...current, name: event.target.value }))}
                />
              </label>
              <label>
                <span>对应数据字段</span>
                <input
                  placeholder="例如：first_seal_time"
                  value={ruleDraft.field}
                  onChange={(event) => setRuleDraft((current) => ({ ...current, field: event.target.value }))}
                />
              </label>
              <label>
                <span>计算口径</span>
                <input
                  placeholder="尤其填写封单质量公式；留空表示不计算"
                  value={ruleDraft.calculation}
                  onChange={(event) => setRuleDraft((current) => ({ ...current, calculation: event.target.value }))}
                />
              </label>
              <label>
                <span>比较方式</span>
                <select
                  value={ruleDraft.comparison}
                  onChange={(event) => setRuleDraft((current) => ({ ...current, comparison: event.target.value }))}
                >
                  <option value="<=">≤</option>
                  <option value="<">&lt;</option>
                  <option value="=">=</option>
                  <option value=">=">≥</option>
                  <option value=">">&gt;</option>
                  <option value="!=">≠</option>
                  <option value="in">包含</option>
                  <option value="not_in">不包含</option>
                  <option value="exists">存在</option>
                  <option value="not_exists">不存在</option>
                  <option value="in_time_windows">时间窗口内</option>
                  <option value="none_at_or_after">不得晚于时间</option>
                </select>
              </label>
              <label>
                <span>阈值</span>
                <input
                  placeholder="例如：10:00 或 1.50"
                  value={ruleDraft.threshold}
                  onChange={(event) => setRuleDraft((current) => ({ ...current, threshold: event.target.value }))}
                />
              </label>
              <label>
                <span>数据缺失时</span>
                <select
                  value={ruleDraft.missing_behavior}
                  onChange={(event) => setRuleDraft((current) => ({ ...current, missing_behavior: event.target.value }))}
                >
                  <option value="保留">标记数据缺失并保留</option>
                  <option value="淘汰">淘汰</option>
                </select>
              </label>
              <label className="dragon-toggle">
                <input
                  checked={ruleDraft.is_hard}
                  type="checkbox"
                  onChange={(event) => setRuleDraft((current) => ({ ...current, is_hard: event.target.checked }))}
                />
                <span>一票否决（硬性条件）</span>
              </label>
              <label className="dragon-toggle">
                <input
                  checked={ruleDraft.enabled}
                  type="checkbox"
                  onChange={(event) => setRuleDraft((current) => ({ ...current, enabled: event.target.checked }))}
                />
                <span>立即启用</span>
              </label>
              <div className="dragon-form-actions">
                <button className="btn btn-primary" type="submit">
                  {editingRuleId ? "保存到当前草稿" : "加入当前草稿"}
                </button>
              </div>
            </form>
          </section>

          <section className="panel dragon-rule-list-panel">
            <div className="panel-heading">
              <div>
                <span className="section-number">02</span>
                <div>
                  <span className="eyebrow">已保存标准</span>
                  <h3>规则与版本</h3>
                </div>
              </div>
              <span className="hint">{rules.length} 条</span>
            </div>
            {rules.length ? (
              <div className="dragon-rule-list">
                {rules.map((rule) => (
                  <article key={rule.id || rule.name}>
                    <div>
                      <strong>{rule.name}</strong>
                      <small>{rule.field} {comparisonLabel(rule.comparison)} {rule.threshold}</small>
                      <small>口径：{rule.calculation || "未提供，不自动推断"}</small>
                    </div>
                    <span className={rule.enabled ? "dragon-enabled" : "dragon-disabled"}>
                      {rule.enabled ? "已启用" : "已停用"}
                    </span>
                    <span>{rule.is_hard ? "硬性条件" : "普通条件"}</span>
                    <small>缺失：{rule.missing_behavior}</small>
                    <div className="dragon-row-actions">
                      <button type="button" onClick={() => editRule(rule)}>编辑</button>
                      <button type="button" onClick={() => toggleRule(rule)}>
                        {rule.enabled ? "停用" : "启用"}
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className="dragon-empty-state">
                <strong>尚未定义基础标准</strong>
                <p>可先载入已确认的七条硬性标准，再按需要编辑并保存新版本。</p>
                <button className="btn btn-secondary" type="button" onClick={bootstrapRules} disabled={!token}>
                  载入已确认的基础标准
                </button>
              </div>
            )}
            <div className="dragon-version-editor">
              <div>
                <span className="eyebrow">规则版本记录</span>
                <strong>将当前规则保存为独立版本</strong>
              </div>
              <input
                placeholder="版本名称，例如：首板基础标准 v1"
                value={ruleVersionName}
                onChange={(event) => setRuleVersionName(event.target.value)}
              />
              <input
                placeholder="版本说明（可选）"
                value={ruleVersionNote}
                onChange={(event) => setRuleVersionNote(event.target.value)}
              />
              <button
                className="btn btn-primary"
                disabled={isPublishingRuleVersion || !token || !rules.length}
                type="button"
                onClick={publishRuleVersion}
              >
                {isPublishingRuleVersion ? "正在保存…" : "保存为规则版本并启用"}
              </button>
            </div>
            {ruleVersions.length > 0 && (
              <div className="dragon-version-list">
                {ruleVersions.map((version) => (
                  <article
                    className={version.is_active ? "active" : ""}
                    key={version.id}
                  >
                    <button
                      className="dragon-version-activate"
                      type="button"
                      onClick={() => {
                        if (!version.is_active) void activateRuleVersion(version);
                      }}
                    >
                      <strong>{version.name}</strong>
                      <small>
                        {version.is_active ? "当前启用" : "点击启用"} ·
                        {version.created_at ? " " + version.created_at.replace("T", " ") : " 未记录时间"}
                      </small>
                    </button>
                    <button
                      className="dragon-version-delete"
                      disabled={version.is_active}
                      type="button"
                      onClick={() => void deleteRuleVersion(version)}
                    >
                      {version.is_active ? "启用中" : "删除"}
                    </button>
                  </article>
                ))}
              </div>
            )}
          </section>
        </>
      )}

      {activeTab === "knowledge" && (
        <>
          <section className="panel dragon-library-panel">
            <div className="panel-heading">
              <div>
                <span className="section-number">01</span>
                <div>
                  <span className="eyebrow">独立 RAG · dragon_knowledge.db</span>
                  <h3>导入历史模型与案例</h3>
                </div>
              </div>
              <label className="file-picker">
                <input
                  accept=".docx,.xlsx,.csv,.json,.md,.txt"
                  disabled={isUploading || !token}
                  type="file"
                  onChange={uploadDocument}
                />
                <span>{isUploading ? "正在导入…" : "上传资料"}</span>
              </label>
            </div>
            <p className="dragon-panel-intro">
              支持 DOCX、XLSX/CSV、JSON、Markdown、TXT。导入内容仅进入独立历史模型库，不会写入或检索现有 review_knowledge.db。
            </p>
            {documents.length ? (
              <div className="dragon-document-list">
                {documents.map((document) => (
                  <article key={document.id || document.filename}>
                    <div className="dragon-document-head">
                      <div>
                        <strong>{document.filename}</strong>
                        <small>
                          {document.file_type || "资料"} · {document.chunk_count} 个切片 ·
                          {document.imported_at ? " " + document.imported_at.replace("T", " ") : " 等待索引"}
                        </small>
                      </div>
                      <button type="button" onClick={() => inspectChunks(document)}>
                        {selectedDocumentId === document.id ? "已查看切片" : "查看切片"}
                      </button>
                    </div>
                    <div className="dragon-tag-editor">
                      <input
                        placeholder="案例标签：连板、卡位、补涨…"
                        value={tagDrafts[document.id] ?? document.tags.join("，")}
                        onChange={(event) => setTagDrafts((current) => ({ ...current, [document.id]: event.target.value }))}
                      />
                      <button type="button" onClick={() => saveTags(document)}>保存标签</button>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className="dragon-empty-state">
                <strong>尚未导入历史模型资料</strong>
                <p>可以先完成页面和规则配置；历史案例资料到位后再上传并补充模型标签。</p>
              </div>
            )}
          </section>

          <section className="panel dragon-retrieval-panel">
            <div className="panel-heading">
              <div>
                <span className="section-number">02</span>
                <div>
                  <span className="eyebrow">检索验证</span>
                  <h3>测试独立 RAG</h3>
                </div>
              </div>
            </div>
            <form className="dragon-search-form" onSubmit={search}>
              <input
                placeholder="输入股票代码、股票名称或案例关键词"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
              />
              <button className="btn btn-secondary" disabled={isSearching || !token} type="submit">
                {isSearching ? "检索中…" : "测试检索"}
              </button>
            </form>
            <div className="dragon-evidence-list">
              {(selectedDocumentId ? documentChunks : searchResults).map((item, index) => (
                <article key={item.id || item.source_name + index}>
                  <div>
                    <strong>{item.source_name}</strong>
                    <span>{item.score === null ? "来源切片" : "相关度 " + item.score.toFixed(3)}</span>
                  </div>
                  <p>{item.excerpt || "切片正文待返回"}</p>
                  {item.tags.length > 0 && <small>{item.tags.join(" · ")}</small>}
                </article>
              ))}
              {!((selectedDocumentId ? documentChunks : searchResults).length) && (
                <div className="dragon-empty-state">
                  <strong>{selectedDocumentId ? "尚未返回该资料的切片" : "尚未执行检索"}</strong>
                  <p>每次 API 分析只会取最相关的约 6–10 条证据，而不会发送整个模型库。</p>
                </div>
              )}
            </div>
          </section>
        </>
      )}

      {activeTab === "records" && (
        <section className="panel dragon-records-panel">
          <div className="panel-heading">
            <div>
              <span className="section-number">01</span>
              <div>
                <span className="eyebrow">历史快照 · 规则版本 · RAG 引用</span>
                <h3>分析记录</h3>
              </div>
            </div>
            <button className="btn btn-secondary" type="button" onClick={() => { void loadDashboard(); }}>
              刷新
            </button>
          </div>
          {isLoading && <p className="dragon-loading">正在读取独立首板模块记录…</p>}
          {records.length ? (
            <div className="dragon-record-layout">
              <div className="dragon-record-list">
                {records.map((record) => (
                  <button
                    className={record.id === selectedRecordId ? "active" : ""}
                    key={record.id || record.created_at}
                    type="button"
                    onClick={() => setSelectedRecordId(record.id)}
                  >
                    <strong>{record.trade_date || "未标记日期"}</strong>
                    <small>{record.status} · {record.candidates.length} 只候选</small>
                    <span>{ruleVersionNames.get(record.standard_version) || record.standard_version}</span>
                  </button>
                ))}
              </div>
              {selectedRecord && (
                <article className="dragon-record-detail">
                  <div className="dragon-record-meta">
                    <span>{selectedRecord.created_at.replace("T", " ")}</span>
                    <span>标准：{ruleVersionNames.get(selectedRecord.standard_version) || selectedRecord.standard_version}</span>
                  </div>
                  <h4>当时复盘快照</h4>
                  {selectedRecord.snapshot ? (
                    <dl>
                      {snapshotFields.map((field) => (
                        <div key={field.key}>
                          <dt>{field.label}</dt>
                          <dd>{selectedRecord.snapshot?.[field.key] || "—"}</dd>
                        </div>
                      ))}
                    </dl>
                  ) : <p>记录未返回复盘快照。</p>}
                  <h4>候选结论与历史时间</h4>
                  {selectedRecord.candidates.length ? selectedRecord.candidates.map((candidate) => (
                    <div className="dragon-record-candidate" key={candidate.stock_code + candidate.stock_name}>
                      <strong>{candidate.stock_name} · {candidate.conclusion}</strong>
                      {Object.keys(candidate.analysis).length ? <ModelAnalysisView value={candidate.analysis} /> : null}
                      <p>{candidate.history_dates.length ? candidate.history_dates.join("、") : "未匹配历史时间"}</p>
                    </div>
                  )) : <p>记录未返回候选。</p>}
                  <details>
                    <summary>查看 API 原始结论</summary>
                    <pre>{JSON.stringify(selectedRecord.raw, null, 2)}</pre>
                  </details>
                </article>
              )}
            </div>
          ) : (
            <div className="dragon-empty-state">
              <strong>暂无首板布局分析记录</strong>
              <p>完成一次独立首板布局任务后，这里会保留当时复盘快照、标准版本、RAG 证据与 API 原始结论。</p>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
