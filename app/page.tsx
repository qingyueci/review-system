"use client";

import { ChangeEvent, useEffect, useState } from "react";

import { AnalysisSection } from "./components/AnalysisSection";
import { HistoryDocumentsSection } from "./components/HistoryDocumentsSection";
import { KnowledgeSection } from "./components/KnowledgeSection";
import { TodayReviewSection } from "./components/TodayReviewSection";
import {
  BranchState,
  Job,
  PersistedJob,
  StartedJob,
  requestLocal,
  waitForJob,
} from "./lib/review-api";
import {
  AnalysisResult,
  AnalysisTask,
  GenerationMode,
  HistoryDocument,
  KnowledgePost,
  Source,
  Stats,
} from "./lib/review-types";

type FetchReviewResult = {
  title: string;
  review_date: string;
  source_url: string;
  text: string;
};

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
    // 恢复逻辑只由连接状态触发，避免结果更新后重复接管同一任务。
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      const started = await requestLocal<StartedJob>(
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
      if (started.reused) {
        const message = "相同复盘正在生成，已接回原任务，不会重复调用模型。";
        setActionMessage(message);
        showNotice(message);
      }
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
      const started = await requestLocal<StartedJob>(
        token,
        `/api/jobs/${resultJobId}/retry`,
        {
        method: "POST",
        body: JSON.stringify({ branch, api_key: apiKey }),
        },
      );
      setResultJobId(started.job_id);
      window.localStorage.setItem(
        "review-active-generation",
        started.job_id,
      );
      if (started.reused) {
        const message = `${label} 已在重试中，已接回原任务，不会重复调用模型。`;
        setActionMessage(message);
        showNotice(message);
      }
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
            <TodayReviewSection
              reviewFile={reviewFile}
              crawledText={crawledText}
              crawledSource={crawledSource}
              apiKeyConfigured={apiKeyConfigured}
              apiKey={apiKey}
              onApiKeyChange={(value) => {
                setApiKey(value);
                setActionMessage("");
              }}
              actionMessage={actionMessage}
              isAnalyzing={isAnalyzing}
              generationMode={generationMode}
              onGenerationModeChange={setGenerationMode}
              generatesExcel={generatesExcel}
              generatesWord={generatesWord}
              generationJob={generationJob}
              analysis={analysis}
              onRetry={handleRetry}
              onAnalyze={handleAnalyze}
              generationLabel={generationLabel}
              hasGeneratedFiles={hasGeneratedFiles}
              onDownloadExcel={downloadExcel}
              onDownloadWord={downloadDocument}
            />
          )}

          {activeNav === "布局分析" && (
            <AnalysisSection
              analysis={analysis}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onGoToToday={() => setActiveNav("今日复盘")}
            />
          )}

          {activeNav === "知识库" && (
            <KnowledgeSection
              stats={stats}
              syncJob={syncJob}
              posts={knowledgePosts}
              onSync={handleSync}
            />
          )}

          {activeNav === "历史文档" && (
            <HistoryDocumentsSection
              documents={documents}
              onDownload={downloadHistoryDocument}
              onGoToToday={() => setActiveNav("今日复盘")}
            />
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
