"use client";

import { ChangeEvent, useEffect, useState } from "react";

const API_BASE = "http://127.0.0.1:8765";

type Task = {
  id: string;
  name: string;
  role: string;
  origin: string;
  task: string;
  position: string;
  relation: string;
  state: "推进" | "观察" | "受阻";
};

type Stats = {
  core_posts: number;
  supplemental_posts: number;
  qa_pairs: number;
  community_comments: number;
  manual_chunks: number;
  chunks: number;
  last_sync: string;
};

type Source = {
  level: string;
  title: string;
  published_at: string;
  source_url: string;
  excerpt: string;
  source_type: string;
};

type AnalysisResult = {
  analysis: string;
  sections: Record<string, string>;
  tasks: AnalysisTask[];
  sources: Source[];
  document_base64: string;
  document_filename: string;
  excel_base64: string;
  excel_filename: string;
  branches: Record<"excel" | "word", BranchState>;
  warnings: string[];
};

type BranchState = {
  status: "pending" | "running" | "succeeded" | "failed" | "skipped";
  message: string;
};

type GenerationMode = "both" | "excel" | "word";

type AnalysisTask = {
  stock: string;
  origin: string;
  original_task: string;
  current_position: string;
  relations: string;
  success_signal: string;
  failure_signal: string;
};

type Job<T = unknown> = {
  status: "pending" | "running" | "succeeded" | "failed";
  message: string;
  current: number;
  total: number;
  branches?: Record<"excel" | "word", BranchState>;
  stats?: Stats;
  result?: T;
};

type PersistedJob<T = unknown> = Job<T> & {
  job_id: string;
  created_at: string;
  updated_at: string;
};

type FetchReviewResult = {
  title: string;
  review_date: string;
  source_url: string;
  text: string;
};

type HistoryDocument = {
  filename: string;
  modified_at: string;
  size: number;
  kind: "word" | "excel";
};

type KnowledgePost = {
  title: string;
  published_at: string;
  views: number;
  reply_count: number;
  likes: number;
  scope: "top_year" | "recent_qa";
  body_truncated: boolean;
  capture_mode: string;
  url: string;
};

const frameworkTasks: Task[] = [
  {
    id: "seed",
    name: "首板发起者",
    role: "进攻发起",
    origin: "主动首板",
    task: "替板块打开空间，验证新增量",
    position: "前排试错",
    relation: "带动承接核心，并接受风险锚点反馈",
    state: "推进",
  },
  {
    id: "core",
    name: "换手承接者",
    role: "承接中枢",
    origin: "分歧首板",
    task: "吸收抛压，为发起者提供持续性证明",
    position: "结构核心",
    relation: "承接发起者，压制后排地位上升",
    state: "观察",
  },
  {
    id: "anchor",
    name: "情绪锚点",
    role: "风险定价",
    origin: "逆势辨识度首板",
    task: "提示周期强弱，决定进攻仓位上限",
    position: "外部锚点",
    relation: "不争龙头，但影响整个队形的风险溢价",
    state: "受阻",
  },
  {
    id: "follower",
    name: "后排验证者",
    role: "扩散确认",
    origin: "题材助攻首板",
    task: "证明板块宽度，不承担打开高度的职责",
    position: "后排验证",
    relation: "依赖前排；主动卡位时才可能升级任务",
    state: "观察",
  },
];

const emptyStats: Stats = {
  core_posts: 20,
  supplemental_posts: 10,
  qa_pairs: 4306,
  community_comments: 342,
  manual_chunks: 14,
  chunks: 4723,
  last_sync: "等待连接本机服务",
};

const navItems = ["今日复盘", "布局分析", "知识库", "历史文档"];

function todayText() {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

function asText(value: unknown) {
  return typeof value === "string" ? value : "";
}

function cleanMarkdown(value: unknown) {
  return asText(value)
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/^[-*]\s+/gm, "• ")
    .trim();
}

function normalizeAnalysisResult(value: unknown): AnalysisResult {
  const raw =
    value && typeof value === "object"
      ? (value as Partial<AnalysisResult>)
      : {};
  const sections = Object.fromEntries(
    Object.entries(raw.sections ?? {}).map(([key, content]) => [
      key,
      asText(content),
    ]),
  );
  const tasks = Array.isArray(raw.tasks)
    ? raw.tasks.map((value) => {
        const task =
          value && typeof value === "object"
            ? (value as Partial<AnalysisTask>)
            : {};
        return {
          stock: asText(task.stock) || "未命名个股",
          origin: asText(task.origin) || "资料不足",
          original_task: asText(task.original_task) || "资料不足",
          current_position: asText(task.current_position) || "资料不足",
          relations: asText(task.relations) || "资料不足",
          success_signal: asText(task.success_signal) || "资料不足",
          failure_signal: asText(task.failure_signal) || "资料不足",
        };
      })
    : [];
  const sources = Array.isArray(raw.sources)
    ? raw.sources.map((value) => {
        const source =
          value && typeof value === "object"
            ? (value as Partial<Source>)
            : {};
        return {
          level: asText(source.level) || "公开资料",
          title: asText(source.title) || "未命名资料",
          published_at: asText(source.published_at),
          source_url: asText(source.source_url),
          excerpt: asText(source.excerpt),
          source_type: asText(source.source_type),
        };
      })
    : [];
  const rawBranches =
    raw.branches && typeof raw.branches === "object" ? raw.branches : {};
  const normalizeBranch = (
    name: "excel" | "word",
    ready: boolean,
  ): BranchState => {
    const branch = rawBranches[name] as Partial<BranchState> | undefined;
    const allowed = ["pending", "running", "succeeded", "failed", "skipped"];
    return {
      status: allowed.includes(asText(branch?.status))
        ? (branch?.status as BranchState["status"])
        : ready
          ? "succeeded"
          : "skipped",
      message:
        asText(branch?.message) ||
        (ready ? "已生成并保存" : "本次没有生成"),
    };
  };
  const documentFilename = asText(raw.document_filename);
  const excelFilename = asText(raw.excel_filename);
  return {
    analysis: asText(raw.analysis),
    sections,
    tasks,
    sources,
    document_base64: asText(raw.document_base64),
    document_filename: documentFilename,
    excel_base64: asText(raw.excel_base64),
    excel_filename: excelFilename,
    branches: {
      excel: normalizeBranch("excel", Boolean(excelFilename)),
      word: normalizeBranch("word", Boolean(documentFilename)),
    },
    warnings: Array.isArray(raw.warnings)
      ? raw.warnings.map(asText).filter(Boolean)
      : [],
  };
}

function mergeAnalysisResults(
  previous: AnalysisResult,
  incoming: AnalysisResult,
): AnalysisResult {
  const keepPreviousBranch = (name: "excel" | "word") =>
    incoming.branches[name].status === "skipped" &&
    previous.branches[name].status === "succeeded";
  return {
    analysis: incoming.analysis || previous.analysis,
    sections:
      Object.keys(incoming.sections).length > 0
        ? incoming.sections
        : previous.sections,
    tasks: incoming.tasks.length ? incoming.tasks : previous.tasks,
    sources: incoming.sources.length ? incoming.sources : previous.sources,
    document_base64:
      incoming.document_base64 || previous.document_base64,
    document_filename:
      incoming.document_filename || previous.document_filename,
    excel_base64: incoming.excel_base64 || previous.excel_base64,
    excel_filename: incoming.excel_filename || previous.excel_filename,
    branches: {
      excel: keepPreviousBranch("excel")
        ? previous.branches.excel
        : incoming.branches.excel,
      word: keepPreviousBranch("word")
        ? previous.branches.word
        : incoming.branches.word,
    },
    warnings: incoming.warnings,
  };
}

async function requestLocal<T>(
  token: string,
  path: string,
  init: RequestInit & { timeoutMs?: number } = {},
): Promise<T> {
  const { timeoutMs = 15_000, ...fetchInit } = init;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...fetchInit,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        "X-Review-Token": token,
        ...(fetchInit.headers ?? {}),
      },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || `本机服务返回错误：${response.status}`);
    }
    return payload as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("本机服务响应较慢，正在重新连接");
    }
    if (error instanceof TypeError) {
      throw new Error("本机服务连接中断，请重新双击启动器");
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

async function waitForJob<T>(
  token: string,
  jobId: string,
  onUpdate: (job: Job<T>) => void,
): Promise<Job<T>> {
  let consecutiveFailures = 0;
  while (true) {
    await new Promise((resolve) => window.setTimeout(resolve, 1200));
    let job: Job<T>;
    try {
      job = await requestLocal<Job<T>>(token, `/api/jobs/${jobId}`);
    } catch (error) {
      consecutiveFailures += 1;
      if (consecutiveFailures < 6) {
        onUpdate({
          status: "running",
          message: "本机服务响应较慢，仍在等待后台任务",
          current: 0,
          total: 1,
        });
        continue;
      }
      throw error;
    }
    consecutiveFailures = 0;
    onUpdate(job);
    if (job.status === "failed") {
      throw new Error(job.message || "后台任务执行失败");
    }
    if (job.status === "succeeded") {
      return job;
    }
  }
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = String(reader.result ?? "");
      resolve(value.includes(",") ? value.split(",", 2)[1] : value);
    };
    reader.onerror = () => reject(new Error("读取文件失败，请重新选择"));
    reader.readAsDataURL(file);
  });
}

export default function Home() {
  const [activeNav, setActiveNav] = useState("今日复盘");
  const [selectedId, setSelectedId] = useState("seed");
  const [token, setToken] = useState("");
  const [connected, setConnected] = useState(false);
  const [stats, setStats] = useState<Stats>(emptyStats);
  const [apiKeyConfigured, setApiKeyConfigured] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [generationMode, setGenerationMode] =
    useState<GenerationMode>("both");
  const [reviewDate, setReviewDate] = useState(todayText);
  const [reviewFile, setReviewFile] = useState<File | null>(null);
  const [crawledText, setCrawledText] = useState("");
  const [crawledSource, setCrawledSource] = useState("");
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isFetching, setIsFetching] = useState(false);
  const [generationJob, setGenerationJob] = useState<Job<AnalysisResult> | null>(null);
  const [resultJobId, setResultJobId] = useState("");
  const [syncJob, setSyncJob] = useState<Job | null>(null);
  const [notice, setNotice] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [documents, setDocuments] = useState<HistoryDocument[]>([]);
  const [knowledgePosts, setKnowledgePosts] = useState<KnowledgePost[]>([]);

  const generatesExcel = generationMode !== "word";
  const generatesWord = generationMode !== "excel";
  const generationLabel =
    generationMode === "both"
      ? "生成 Excel + Word"
      : generationMode === "excel"
        ? "只生成 Excel"
        : "只生成 Word";
  const hasWordAnalysis = Boolean(analysis?.analysis.trim());
  const hasGeneratedFiles = Boolean(
    analysis?.document_filename || analysis?.excel_filename,
  );
  const evidence = analysis?.sources ?? [];
  const sections = analysis?.sections ?? {};
  const coreJudgement = sections["今日核心判断"];
  const layoutText =
    sections["题材之间的任务关系"] ||
    sections["布局总图"] ||
    sections["地位演化和相互确认"];
  const taskText = sections["个股任务表"];
  const tomorrowText = sections["明日竞价确认条件"];
  const failureText = sections["判断失效条件"];
  const displayTasks =
    analysis?.tasks?.length ? analysis.tasks.slice(0, 4) : null;

  useEffect(() => {
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const incoming = hash.get("token");
    if (incoming) {
      window.sessionStorage.setItem("review-service-token", incoming);
      window.history.replaceState(null, "", window.location.pathname);
    }
    const savedToken =
      incoming || window.sessionStorage.getItem("review-service-token") || "";
    const timer = window.setTimeout(() => setToken(savedToken), 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    requestLocal<{
      stats: Stats;
      api_key_configured: boolean;
    }>(token, "/api/status")
      .then((result) => {
        if (cancelled) return;
        setConnected(true);
        setStats(result.stats);
        setApiKeyConfigured(result.api_key_configured);
        return requestLocal<{ documents: HistoryDocument[] }>(
          token,
          "/api/documents",
        );
      })
      .then((result) => {
        if (!cancelled && result) setDocuments(result.documents);
        return requestLocal<{ posts: KnowledgePost[] }>(token, "/api/posts");
      })
      .then((result) => {
        if (!cancelled && result) setKnowledgePosts(result.posts);
      })
      .catch(() => {
        if (!cancelled) setConnected(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    if (!connected || !token) return;
    let cancelled = false;
    async function restoreGeneration() {
      let jobId = window.localStorage.getItem(
        "review-active-generation",
      );
      let job: Job<AnalysisResult> | null = null;
      try {
        if (jobId) {
          job = await requestLocal<Job<AnalysisResult>>(
            token,
            `/api/jobs/${jobId}`,
          );
        } else {
          const recent = await requestLocal<{
            jobs: PersistedJob<AnalysisResult>[];
          }>(token, "/api/jobs/recent?limit=1");
          const latest = recent.jobs[0];
          if (latest) {
            jobId = latest.job_id;
            job = latest;
          }
        }
      } catch {
        window.localStorage.removeItem("review-active-generation");
        return;
      }
      if (cancelled || !job || !jobId) return;
      setResultJobId(jobId);
      setGenerationJob(job);
      if (job.status === "succeeded" || job.status === "failed") {
        window.localStorage.removeItem("review-active-generation");
        if (job.result) setAnalysis(normalizeAnalysisResult(job.result));
        if (job.status === "failed") setActionMessage(job.message);
        return;
      }

      setIsAnalyzing(true);
      setActionMessage("检测到未结束的生成任务，正在恢复进度……");
      try {
        const completed = await waitForJob<AnalysisResult>(
          token,
          jobId,
          (current) => {
            if (!cancelled) {
              setGenerationJob(current);
              setActionMessage(
                `${current.message}${
                  current.total > 1
                    ? `（${current.current}/${current.total}）`
                    : ""
                }`,
              );
            }
          },
        );
        if (!cancelled && completed.result) {
          setGenerationJob(completed);
          await applyGenerationResult(completed.result, true);
        }
      } catch (error) {
        if (!cancelled) {
          const message =
            error instanceof Error ? error.message : "未能恢复上次生成任务";
          setActionMessage(message);
          showNotice(message);
        }
      } finally {
        window.localStorage.removeItem("review-active-generation");
        if (!cancelled) setIsAnalyzing(false);
      }
    }
    void restoreGeneration();
    return () => {
      cancelled = true;
    };
  }, [connected, token]);

  function showNotice(message: string) {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 4200);
  }

  async function applyGenerationResult(
    value: AnalysisResult,
    recovered = false,
    mergePrevious = false,
  ) {
    const incoming = normalizeAnalysisResult(value);
    const result =
      mergePrevious && analysis
        ? mergeAnalysisResults(analysis, incoming)
        : incoming;
    setAnalysis(result);
    try {
      const history = await requestLocal<{ documents: HistoryDocument[] }>(
        token,
        "/api/documents",
      );
      setDocuments(history.documents);
    } catch {
      // 文件已经在本机保存，历史列表连接恢复后会重新加载。
    }
    if (result.analysis) {
      setActiveNav("布局分析");
    } else {
      setActiveNav("今日复盘");
    }
    const completed = [
      result.excel_filename ? "Excel" : "",
      result.document_filename ? "Word" : "",
    ].filter(Boolean);
    const prefix = recovered ? "已恢复上次任务" : "本次生成完成";
    const summary = completed.length
      ? `${prefix}：${completed.join(" + ")} 已保存。`
      : `${prefix}，没有新增文件。`;
    const warning = result.warnings[0];
    setActionMessage(warning ? `${summary} ${warning}` : "");
    showNotice(warning ? `${summary} 部分任务未完成。` : summary);
  }

  function requireConnection() {
    if (connected && token) return true;
    const message =
      "本机服务未连接。请双击“启动复盘驾驶舱.cmd”，再从自动打开的页面进入。";
    setActionMessage(message);
    setActiveNav("今日复盘");
    showNotice(message);
    return false;
  }

  function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setReviewFile(file);
    if (file) {
      setCrawledText("");
      setCrawledSource("");
      setActionMessage("");
      if (
        file.name.toLowerCase().endsWith(".xlsx") &&
        generationMode === "excel"
      ) {
        setGenerationMode("word");
        showNotice("导入内容已经是 Excel，已切换为只生成 Word。");
        return;
      }
      showNotice(
        `已选择「${file.name}」，点击“${generationLabel}”即可。`,
      );
    }
  }

  async function handleFetchReview() {
    if (!requireConnection()) return;
    setIsFetching(true);
    setActionMessage("正在启动自爬取任务……");
    try {
      const started = await requestLocal<{ job_id: string; status: string }>(
        token,
        "/api/fetch-review-async",
        {
          method: "POST",
          body: JSON.stringify({ review_date: reviewDate }),
        },
      );
      const completed = await waitForJob<FetchReviewResult>(
        token,
        started.job_id,
        (job) =>
          setActionMessage(
            `${job.message}${job.total > 1 ? `（${job.current}/${job.total}）` : ""}`,
          ),
      );
      if (!completed.result) {
        throw new Error("自爬取完成，但没有返回复盘正文");
      }
      const result = completed.result;
      setCrawledText(result.text);
      setCrawledSource(result.source_url);
      setReviewFile(null);
      setActionMessage("复盘正文已载入，可以开始 RAG 分析。");
      showNotice(`已自爬取「${result.title}」，无需手动复制。`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "自爬取失败";
      setActionMessage(message);
      showNotice(message);
    } finally {
      setIsFetching(false);
    }
  }

  async function handleAnalyze() {
    if (!requireConnection()) return;
    if (!reviewFile && !crawledText) {
      const message = "缺少每日复盘：请导入文件，或点击“自爬取当日复盘”。";
      setActiveNav("今日复盘");
      setActionMessage(message);
      showNotice(message);
      return;
    }
    if (!apiKeyConfigured && !apiKey.trim()) {
      const message = "缺少 Kimi Code API Key：请在下方密码框填写后再分析。";
      setActiveNav("今日复盘");
      setActionMessage(message);
      showNotice(message);
      return;
    }
    setIsAnalyzing(true);
    setGenerationJob(null);
    setActionMessage(`正在启动：${generationLabel}……`);
    try {
      const contentBase64 = reviewFile ? await fileToBase64(reviewFile) : "";
      const started = await requestLocal<{ job_id: string; status: string }>(
        token,
        "/api/analyze-async",
        {
          method: "POST",
          body: JSON.stringify({
            filename: reviewFile?.name || `${reviewDate}复盘.txt`,
            content_base64: contentBase64,
            text: crawledText,
            review_date: reviewDate,
            api_key: apiKey,
            generate_excel: generatesExcel,
            generate_word: generatesWord,
          }),
        },
      );
      setResultJobId(started.job_id);
      window.localStorage.setItem(
        "review-active-generation",
        started.job_id,
      );
      const completed = await waitForJob<AnalysisResult>(
        token,
        started.job_id,
        (job) => {
          setGenerationJob(job);
          setActionMessage(
            `${job.message}${job.total > 1 ? `（${job.current}/${job.total}）` : ""}`,
          );
        },
      );
      if (!completed.result) {
        throw new Error("任务结束，但没有返回生成结果");
      }
      setGenerationJob(completed);
      await applyGenerationResult(completed.result);
    } catch (error) {
      const message = error instanceof Error ? error.message : "分析失败";
      setActionMessage(message);
      showNotice(message);
    } finally {
      window.localStorage.removeItem("review-active-generation");
      setIsAnalyzing(false);
    }
  }

  async function handleRetry(branch: "excel" | "word") {
    if (!requireConnection()) return;
    if (!resultJobId) {
      showNotice("没有找到可重试的任务记录，请重新生成。");
      return;
    }
    if (!apiKeyConfigured && !apiKey.trim()) {
      const message = "缺少 Kimi Code API Key，无法重试失败项。";
      setActionMessage(message);
      showNotice(message);
      return;
    }
    const label = branch === "excel" ? "Excel" : "Word";
    setIsAnalyzing(true);
    setActionMessage(`正在单独重试 ${label}……`);
    try {
      const started = await requestLocal<{
        job_id: string;
        status: string;
      }>(token, `/api/jobs/${resultJobId}/retry`, {
        method: "POST",
        body: JSON.stringify({ branch, api_key: apiKey }),
      });
      setResultJobId(started.job_id);
      window.localStorage.setItem(
        "review-active-generation",
        started.job_id,
      );
      const completed = await waitForJob<AnalysisResult>(
        token,
        started.job_id,
        (job) => {
          setGenerationJob(job);
          setActionMessage(
            `${job.message}${
              job.total > 1 ? `（${job.current}/${job.total}）` : ""
            }`,
          );
        },
      );
      if (!completed.result) {
        throw new Error(`${label} 重试结束，但没有返回结果`);
      }
      setGenerationJob(completed);
      await applyGenerationResult(completed.result, false, true);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : `${label} 重试失败`;
      setActionMessage(message);
      showNotice(message);
    } finally {
      window.localStorage.removeItem("review-active-generation");
      setIsAnalyzing(false);
    }
  }

  async function handleSync() {
    if (!requireConnection()) return;
    try {
      const started = await requestLocal<{ job_id: string; status: string }>(
        token,
        "/api/sync",
        { method: "POST", body: "{}" },
      );
      const completed = await waitForJob<unknown>(
        token,
        started.job_id,
        (job) => setSyncJob(job),
      );
      if (completed.stats) {
        setStats(completed.stats);
        const refreshed = await requestLocal<{ posts: KnowledgePost[] }>(
          token,
          "/api/posts",
        );
        setKnowledgePosts(refreshed.posts);
        showNotice("自爬取、清洗和知识库更新已完成。");
      } else {
        showNotice(completed.message || "知识库更新失败");
      }
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "知识库更新失败");
      setSyncJob(null);
    }
  }

  function downloadDocument() {
    if (!analysis?.document_filename) {
      showNotice("本次还没有生成 Word。");
      return;
    }
    void downloadHistoryDocument(analysis.document_filename);
  }

  function downloadExcel() {
    if (!analysis?.excel_filename) {
      showNotice("本次还没有生成 Excel。");
      return;
    }
    void downloadHistoryDocument(analysis.excel_filename);
  }

  async function downloadHistoryDocument(filename: string) {
    if (!requireConnection()) return;
    try {
      const response = await fetch(
        `${API_BASE}/api/documents/${encodeURIComponent(filename)}`,
        { headers: { "X-Review-Token": token } },
      );
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || "生成文件下载失败");
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "生成文件下载失败");
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">刺</div>
          <div>
            <div className="brand-line">
              <h1>复盘驾驶舱</h1>
              <span className="beta">布局任务模型</span>
            </div>
            <p>不追着价格解释，先判断每只个股在队形里承担什么任务</p>
          </div>
        </div>
        <div className="top-actions">
          <div className={`knowledge-status ${connected ? "" : "offline"}`}>
            <span className="pulse-dot" />
            <div>
              <strong>{connected ? "本机知识库已连接" : "本机服务未连接"}</strong>
              <small>{connected ? `${stats.chunks.toLocaleString()} 条可检索证据` : "请从启动器打开"}</small>
            </div>
          </div>
          <button className="btn btn-secondary" disabled={Boolean(syncJob && syncJob.status !== "failed" && syncJob.status !== "succeeded")} onClick={handleSync}>
            {syncJob?.status === "running" ? `更新中 ${syncJob.current}/${syncJob.total}` : "更新知识库"}
          </button>
          <button className="btn btn-primary" disabled={isAnalyzing} onClick={handleAnalyze}>
            {isAnalyzing ? "正在生成…" : generationLabel}
          </button>
        </div>
      </header>

      <div className="workspace">
        <aside className="sidebar">
          <nav aria-label="主要功能">
            {navItems.map((item, index) => (
              <button key={item} className={`nav-item ${activeNav === item ? "active" : ""}`} onClick={() => setActiveNav(item)}>
                <span className="nav-index">0{index + 1}</span>
                <span>{item}</span>
              </button>
            ))}
          </nav>
          <div className="sidebar-divider" />
          <div className="library-card">
            <span className="eyebrow">RAG 知识构成</span>
            <dl>
              <div><dt>核心原帖</dt><dd>{stats.core_posts}</dd></div>
              <div><dt>本人回复</dt><dd>{stats.qa_pairs.toLocaleString()}</dd></div>
              <div><dt>社区精选</dt><dd>{stats.community_comments}</dd></div>
              <div><dt>人工体系切片</dt><dd>{stats.manual_chunks}</dd></div>
            </dl>
            <div className="source-note">已纳入《延边刺客短线打板体系》</div>
          </div>
          <p className="sidebar-foot">最近同步 · {stats.last_sync.replace("T", " ")}</p>
        </aside>

        <section className="main-column">
          <div className="context-bar">
            <div>
              <span className="eyebrow">本地资料 · 私有分析</span>
              <h2>{activeNav}</h2>
            </div>
            {activeNav === "今日复盘" && (
              <div className="context-tools">
                <input className="date-input" type="date" value={reviewDate} max={todayText()} onChange={(event) => setReviewDate(event.target.value)} aria-label="复盘日期" />
                <label className="file-picker">
                  <input type="file" accept=".docx,.xlsx,.txt,.md" onChange={handleFile} />
                  <span>导入复盘文件</span>
                </label>
                <button className="file-picker crawl-button" disabled={isFetching} onClick={handleFetchReview}>
                  {isFetching ? "正在爬取…" : "自爬取当日复盘"}
                </button>
              </div>
            )}
          </div>

          {activeNav === "今日复盘" && (
            <>
              <section className="intake-card">
                <div className="intake-heading">
                  <span className="section-number">01</span>
                  <div><span className="eyebrow">生成输入</span><h3>选择文件，或直接自爬取当日复盘</h3></div>
                </div>
                <div className="input-status-row">
                  <div>
                    <span className={reviewFile || crawledText ? "ready-dot" : "empty-dot"} />
                    {reviewFile ? reviewFile.name : crawledText ? "已载入公开复盘正文" : "尚未载入每日复盘"}
                    {crawledSource && <a href={crawledSource} target="_blank" rel="noreferrer">查看来源</a>}
                  </div>
                  {!apiKeyConfigured && (
                    <label className="api-key-field">
                      <span>Kimi Code Key</span>
                      <input type="password" value={apiKey} onChange={(event) => { setApiKey(event.target.value); setActionMessage(""); }} placeholder="只发送到 127.0.0.1" autoComplete="off" />
                    </label>
                  )}
                  {apiKeyConfigured && <span className="key-ready">本机已配置模型密钥</span>}
                </div>
                {actionMessage && <div className={`action-message ${isAnalyzing ? "working" : ""}`}>{actionMessage}</div>}
                <div className="generation-mode" role="radiogroup" aria-label="生成内容">
                  {([
                    ["both", "同时生成", "完整 Excel + 核心 Word"],
                    ["excel", "只生成 Excel", "完整整理，不新增观点"],
                    ["word", "只生成 Word", "只分析核心任务"],
                  ] as const).map(([mode, title, description]) => (
                    <button
                      key={mode}
                      type="button"
                      role="radio"
                      aria-checked={generationMode === mode}
                      className={generationMode === mode ? "active" : ""}
                      disabled={
                        isAnalyzing ||
                        (mode === "excel" &&
                          Boolean(
                            reviewFile?.name
                              .toLowerCase()
                              .endsWith(".xlsx"),
                          ))
                      }
                      onClick={() => setGenerationMode(mode)}
                    >
                      <strong>{title}</strong>
                      <small>{description}</small>
                    </button>
                  ))}
                </div>
                <div className="pipeline-row">
                  <div><span>1</span><strong>载入并清洗</strong><small>文件或公开原帖</small></div>
                  <i>→</i>
                  <div><span>2</span><strong>并行启动</strong><small>两条链路互不拖累</small></div>
                  <i>→</i>
                  <div className={generatesExcel ? "" : "muted-step"}><span>X</span><strong>Excel 完整整理</strong><small>保留全部复盘信息</small></div>
                  <i>→</i>
                  <div className={generatesWord ? "" : "muted-step"}><span>W</span><strong>Word 核心分析</strong><small>只写有地位的个股</small></div>
                </div>
                {(generationJob?.branches || analysis?.branches) && (
                  <div className="branch-status-grid">
                    {(["excel", "word"] as const).map((name) => {
                      const branch =
                        (isAnalyzing
                          ? generationJob?.branches?.[name]
                          : analysis?.branches[name]) ??
                        generationJob?.branches?.[name];
                      if (!branch) return null;
                      return (
                        <div
                          key={name}
                          className={`branch-status ${branch.status}`}
                        >
                          <span>{name === "excel" ? "X" : "W"}</span>
                          <div>
                            <strong>
                              {name === "excel"
                                ? "Excel 完整整理"
                                : "Word 布局分析"}
                            </strong>
                            <small>{branch.message}</small>
                            {branch.status === "failed" && !isAnalyzing && (
                              <button
                                type="button"
                                className="retry-branch"
                                onClick={() => handleRetry(name)}
                              >
                                只重试{name === "excel" ? " Excel" : " Word"}
                              </button>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
                <button className="primary-run-button" disabled={isAnalyzing} onClick={handleAnalyze}>
                  <span>{isAnalyzing ? "正在生成并保存结果…" : generationLabel}</span>
                  <small>
                    {reviewFile?.name.toLowerCase().endsWith(".xlsx")
                      ? "输入已是 Excel，本次只新增 Word 分析"
                      : reviewFile || crawledText
                        ? generationMode === "both"
                          ? "一次点击，分别保存两个结果"
                          : "只调用当前选择的生成链路"
                        : "需要先载入每日复盘"}
                  </small>
                </button>
                {hasGeneratedFiles && analysis && (
                  <div className="generated-files">
                    <div>
                      <span className="eyebrow">本次输出</span>
                      <strong>成功结果已独立保存</strong>
                      <small>其中一条链路失败时，另一条结果不会丢失。</small>
                    </div>
                    <div className="generated-file-actions">
                      <button
                        disabled={!analysis.excel_filename}
                        onClick={downloadExcel}
                      >
                        下载 Excel
                      </button>
                      <button
                        disabled={!analysis.document_filename}
                        onClick={downloadDocument}
                      >
                        下载 Word
                      </button>
                    </div>
                  </div>
                )}
              </section>
              <section className="today-note-grid">
                <article><span className="eyebrow">分析主线</span><h3>首板出身决定原始任务</h3><p>先确认从哪里发酵、为谁开路，再判断个股是否完成任务。</p></article>
                <article><span className="eyebrow">明确禁止</span><h3>不用普通技术分析冲掉布局核心</h3><p>价格、量能和均线只能作为任务是否被确认的证据。</p></article>
              </section>
            </>
          )}

          {activeNav === "布局分析" && (
            <>
              {!hasWordAnalysis && (
                <div className="page-empty">
                  <span className="empty-symbol">未</span>
                  <h3>还没有真实分析结果</h3>
                  <p>Excel 可能已经生成；Word 布局分析需要模型额度可用后才能显示。</p>
                  <button onClick={() => setActiveNav("今日复盘")}>前往今日复盘</button>
                </div>
              )}
              {analysis && hasWordAnalysis && (
                <>
                  <section className="judgement-card">
                    <div className="judgement-topline">
                      <span className="section-number">01</span>
                      <span className="eyebrow">RAG 核心判断</span>
                      <span className="confidence">引用 {evidence.length} 条资料</span>
                    </div>
                    <div className="judgement-grid">
                      <div>
                        <h3>{coreJudgement ? cleanMarkdown(coreJudgement).split("\n")[0] : "本次分析已完成"}</h3>
                        <p className="analysis-text">{coreJudgement ? cleanMarkdown(coreJudgement) : cleanMarkdown(analysis.analysis)}</p>
                      </div>
                      <div className="decision-box">
                        <span>核心约束</span>
                        <strong>技术指标只能验证任务，不能替代布局关系</strong>
                        <small>社区评论仅作补充；与本人原帖冲突时，以可核对的公开原文为准。</small>
                      </div>
                    </div>
                  </section>
                  <section className="panel relationship-panel">
                    <div className="panel-heading">
                      <div><span className="section-number">02</span><div><span className="eyebrow">布局关系</span><h3>本次检索分析</h3></div></div>
                    </div>
                    {layoutText && <div className="generated-analysis">{cleanMarkdown(layoutText)}</div>}
                    <div className="relationship-map" aria-label="个股任务关系框架示意图">
                      {displayTasks
                        ? displayTasks.map((task, index) => {
                            const position = ["seed", "core", "anchor", "follower"][index];
                            return (
                              <button key={`${task.stock}-${index}`} className={`map-node ${position} ${selectedId === task.stock ? "selected" : ""}`} onClick={() => setSelectedId(task.stock)}>
                                <small>{task.current_position || "任务节点"}</small>
                                <strong>{task.stock}</strong>
                                <span>{task.original_task}</span>
                              </button>
                            );
                          })
                        : frameworkTasks.map((task) => (
                            <button key={task.id} className={`map-node ${task.id} ${selectedId === task.id ? "selected" : ""}`} onClick={() => setSelectedId(task.id)}>
                              <small>{task.role.slice(0, 2)}</small><strong>{task.name}</strong><span>{task.position}</span>
                            </button>
                          ))}
                      <div className="relation-line line-a"><span>带动</span></div><div className="relation-line line-b"><span>反馈</span></div><div className="relation-line line-c"><span>验证</span></div>
                      <div className="map-center"><span>市场合力</span><strong>任务迁移</strong></div>
                    </div>
                  </section>
                  <section className="panel matrix-panel">
                    <div className="panel-heading"><div><span className="section-number">03</span><div><span className="eyebrow">个股任务</span><h3>模型提取的任务表</h3></div></div></div>
                    {analysis.tasks?.length ? (
                      <div className="task-table-wrap">
                        <table className="task-table analysis-task-table">
                          <thead><tr><th>个股</th><th>首板出身</th><th>原始任务</th><th>当前地位</th><th>协同 / 压制</th><th>完成信号</th><th>失败信号</th></tr></thead>
                          <tbody>
                            {analysis.tasks.map((task, index) => (
                              <tr key={`${task.stock}-${index}`} className={selectedId === task.stock ? "selected-row" : ""} onClick={() => setSelectedId(task.stock)}>
                                <td><strong>{task.stock}</strong></td><td>{task.origin}</td><td>{task.original_task}</td><td>{task.current_position}</td><td>{task.relations}</td><td>{task.success_signal}</td><td>{task.failure_signal}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <div className="task-output">{taskText ? cleanMarkdown(taskText) : "本次模型没有按指定格式输出任务表，请以完整分析和证据链为准。"}</div>
                    )}
                  </section>
                  <section className="tomorrow-grid">
                    <article><span className="eyebrow">明日竞价确认</span><h3>完成任务需要出现什么</h3><p className="analysis-text">{tomorrowText ? cleanMarkdown(tomorrowText) : "资料不足"}</p></article>
                    <article className="failure-card"><span className="eyebrow">失效条件</span><h3>什么时候必须推翻当前判断</h3><p className="analysis-text">{failureText ? cleanMarkdown(failureText) : "资料不足"}</p></article>
                  </section>
                </>
              )}
            </>
          )}

          {activeNav === "知识库" && (
            <>
              <section className="knowledge-hero">
                <div><span className="eyebrow">本机 RAG 状态</span><h3>{stats.chunks.toLocaleString()} 条证据已建立检索索引</h3><p>更新会自动完成发现、抓取、去重、清洗、分段和索引重建。</p></div>
                <button disabled={Boolean(syncJob && syncJob.status !== "failed" && syncJob.status !== "succeeded")} onClick={handleSync}>{syncJob?.status === "running" ? "正在更新…" : "更新知识库（爬取并清洗）"}</button>
              </section>
              {syncJob && (syncJob.status === "pending" || syncJob.status === "running") && (
                <div className="sync-progress"><div style={{ width: `${Math.round((syncJob.current / Math.max(syncJob.total, 1)) * 100)}%` }} /><span>{syncJob.message}</span></div>
              )}
              <section className="stat-grid">
                <article><span>核心原帖</span><strong>{stats.core_posts}</strong><small>近一年高阅读量前 20</small></article>
                <article><span>近期补充帖</span><strong>{stats.supplemental_posts}</strong><small>补充公开问答语境</small></article>
                <article><span>本人回复</span><strong>{stats.qa_pairs.toLocaleString()}</strong><small>作者原始语境优先</small></article>
                <article><span>社区精选</span><strong>{stats.community_comments}</strong><small>只作共识与疑问补充</small></article>
                <article><span>人工体系切片</span><strong>{stats.manual_chunks}</strong><small>本地整理文档</small></article>
                <article><span>最近同步</span><strong className="date-stat">{stats.last_sync.slice(0, 10)}</strong><small>{stats.last_sync.replace("T", " ")}</small></article>
              </section>
              <section className="panel cleaning-panel">
                <span className="eyebrow">清洗规则</span>
                <h3>什么会保留，什么会被降权</h3>
                <div className="cleaning-columns">
                  <div><strong>保留</strong><p>完整正文、本人有效回复、问题上下文、高赞且有布局信息的评论、人工体系文档。</p></div>
                  <div><strong>降权或过滤</strong><p>重复文本、空话、广告、过短回复、脱离布局语境的泛泛评论以及网页噪声。</p></div>
                </div>
              </section>
              <section className="panel source-library-panel">
                <div className="panel-heading">
                  <div><span className="section-number">02</span><div><span className="eyebrow">采集明细</span><h3>已进入知识库的公开帖子</h3></div></div>
                  <span className="hint">{knowledgePosts.length} 篇</span>
                </div>
                <div className="source-table-wrap">
                  <table className="source-table">
                    <thead><tr><th>标题</th><th>日期</th><th>浏览</th><th>评论</th><th>点赞</th><th>用途</th><th>正文</th></tr></thead>
                    <tbody>
                      {knowledgePosts.map((post) => (
                        <tr key={post.url}>
                          <td><a href={post.url} target="_blank" rel="noreferrer">{post.title}</a></td>
                          <td>{post.published_at}</td><td>{post.views.toLocaleString()}</td><td>{post.reply_count.toLocaleString()}</td><td>{post.likes.toLocaleString()}</td>
                          <td>{post.scope === "top_year" ? "高阅读量核心" : "近期问答补充"}</td>
                          <td><span className={post.body_truncated ? "source-badge warning" : "source-badge"}>{post.body_truncated ? "公开节选" : "完整"}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}

          {activeNav === "历史文档" && (
            <section className="history-panel">
              <div className="history-heading"><div><span className="eyebrow">本机保存</span><h3>已生成的 Excel 与 Word</h3></div><span>{documents.length} 份</span></div>
              {documents.length ? (
                <div className="document-list">
                  {documents.map((item) => (
                    <article key={item.filename}>
                      <div className={`doc-icon ${item.kind}`}>{item.kind === "excel" ? "X" : "W"}</div>
                      <div><strong>{item.filename}</strong><small>{item.modified_at.replace("T", " ")} · {Math.max(1, Math.round(item.size / 1024))} KB</small></div>
                      <button onClick={() => downloadHistoryDocument(item.filename)}>下载</button>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="page-empty compact"><h3>还没有生成文件</h3><p>每次运行后，成功生成的 Excel 和 Word 都会独立保存到这里。</p><button onClick={() => setActiveNav("今日复盘")}>开始第一次生成</button></div>
              )}
            </section>
          )}
        </section>

        <aside className="evidence-panel">
          {activeNav === "布局分析" && (
            <>
              <div className="evidence-header"><span className="eyebrow">RAG 证据链</span><span className="evidence-count">{evidence.length} 条</span></div>
              <h2>{hasWordAnalysis ? "本次真实引用" : "等待检索"}</h2>
              <p className="evidence-intro">优先级：本人回复 → 历史原帖 → 人工整理体系 → 社区精选观点。</p>
              <div className="evidence-list">
                {evidence.length ? evidence.map((item, index) => (
                  <article className="evidence-item" key={`${item.source_url}-${index}`}>
                    <div className="evidence-meta"><span>{item.level}</span><span className={item.source_type === "qa" ? "primary-tag" : ""}>{item.published_at}</span></div>
                    <h3>{item.title}</h3><p>{item.excerpt}</p><a href={item.source_url} target="_blank" rel="noreferrer">查看原文定位 →</a>
                  </article>
                )) : <div className="empty-evidence"><strong>这里不会放虚构引用</strong><p>完成一次真实分析后才显示检索来源。</p></div>}
              </div>
              <button className="export-button" disabled={!analysis?.document_filename} onClick={downloadDocument}><span>下载本次 Word</span><small>{analysis?.document_filename ? "已同时保存到历史" : "完成 Word 分析后启用"}</small></button>
            </>
          )}
          {activeNav === "今日复盘" && (
            <>
              <div className="evidence-header"><span className="eyebrow">开始分析检查</span></div>
              <h2>三个条件</h2>
              <div className="check-list">
                <div className={connected ? "done" : ""}><span>{connected ? "✓" : "1"}</span><strong>本机服务</strong><small>{connected ? "已连接" : "需要从启动器进入"}</small></div>
                <div className={reviewFile || crawledText ? "done" : ""}><span>{reviewFile || crawledText ? "✓" : "2"}</span><strong>每日复盘</strong><small>{reviewFile || crawledText ? "已载入" : "文件或自爬取"}</small></div>
                <div className={apiKeyConfigured || Boolean(apiKey.trim()) ? "done" : ""}><span>{apiKeyConfigured || apiKey.trim() ? "✓" : "3"}</span><strong>模型密钥</strong><small>{apiKeyConfigured || apiKey.trim() ? "已就绪" : "临时填写即可"}</small></div>
              </div>
              <div className="evidence-rule"><strong>准备完成后</strong><ol><li>清洗同一份原始复盘</li><li>并行生成完整 Excel</li><li>只分析有地位个股并保存 Word</li></ol></div>
            </>
          )}
          {activeNav === "知识库" && (
            <>
              <div className="evidence-header"><span className="eyebrow">证据优先级</span></div>
              <h2>原文高于共识</h2>
              <div className="priority-list"><span>01 刺大本人回复</span><span>02 历史原帖</span><span>03 人工整理体系</span><span>04 社区精选观点</span></div>
              <p className="evidence-intro">自清洗不会把社区评论冒充作者观点，也不会用普通技术分析覆盖布局逻辑。</p>
            </>
          )}
          {activeNav === "历史文档" && (
            <>
              <div className="evidence-header"><span className="eyebrow">保存位置</span></div>
              <h2>只保存在本机</h2>
              <p className="evidence-intro">Excel 和 Word 都不会上传到站点。历史列表来自本机生成器的 output 目录。</p>
              <div className="evidence-rule"><strong>两类结果分工</strong><ol><li>Excel：完整整理，不新增观点</li><li>Word：只分析有任务和地位的核心个股</li><li>任一失败，成功结果仍会保留</li></ol></div>
            </>
          )}
        </aside>
      </div>
      {notice && <div className="toast" role="status">{notice}</div>}
    </main>
  );
}
