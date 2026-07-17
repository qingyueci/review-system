"use client";

import { ChangeEvent, useEffect, useMemo, useState } from "react";

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
  sources: Source[];
  document_base64: string;
  document_filename: string;
};

type Job = {
  status: "pending" | "running" | "succeeded" | "failed";
  message: string;
  current: number;
  total: number;
  stats?: Stats;
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

function cleanMarkdown(value: string) {
  return value
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/^[-*]\s+/gm, "• ")
    .trim();
}

async function requestLocal<T>(
  token: string,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 180_000);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        "X-Review-Token": token,
        ...(init.headers ?? {}),
      },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || `本机服务返回错误：${response.status}`);
    }
    return payload as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("操作超时，请检查网络后重试");
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
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
  const [reviewDate, setReviewDate] = useState(todayText);
  const [reviewFile, setReviewFile] = useState<File | null>(null);
  const [crawledText, setCrawledText] = useState("");
  const [crawledSource, setCrawledSource] = useState("");
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isFetching, setIsFetching] = useState(false);
  const [syncJob, setSyncJob] = useState<Job | null>(null);
  const [notice, setNotice] = useState("");

  const selectedTask = useMemo(
    () => frameworkTasks.find((task) => task.id === selectedId) ?? frameworkTasks[0],
    [selectedId],
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
      })
      .catch(() => {
        if (!cancelled) setConnected(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  function showNotice(message: string) {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 4200);
  }

  function requireConnection() {
    if (connected && token) return true;
    showNotice("请双击“启动复盘驾驶舱.cmd”，它会连接本机知识库并重新打开本站。");
    return false;
  }

  function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setReviewFile(file);
    if (file) {
      setCrawledText("");
      setCrawledSource("");
      showNotice(`已选择「${file.name}」，点击“开始分析”即可。`);
    }
  }

  async function handleFetchReview() {
    if (!requireConnection()) return;
    setIsFetching(true);
    try {
      const result = await requestLocal<{
        title: string;
        review_date: string;
        source_url: string;
        text: string;
      }>(token, "/api/fetch-review", {
        method: "POST",
        body: JSON.stringify({ review_date: reviewDate }),
      });
      setCrawledText(result.text);
      setCrawledSource(result.source_url);
      setReviewFile(null);
      showNotice(`已自爬取「${result.title}」，无需手动复制。`);
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "自爬取失败");
    } finally {
      setIsFetching(false);
    }
  }

  async function handleAnalyze() {
    if (!requireConnection()) return;
    if (!reviewFile && !crawledText) {
      showNotice("请先导入复盘文件，或点击“自爬取当日复盘”。");
      return;
    }
    if (!apiKeyConfigured && !apiKey.trim()) {
      showNotice("请填写 Kimi Code API Key。密钥只发送给本机服务。");
      return;
    }
    setIsAnalyzing(true);
    try {
      const contentBase64 = reviewFile ? await fileToBase64(reviewFile) : "";
      const result = await requestLocal<AnalysisResult>(token, "/api/analyze", {
        method: "POST",
        body: JSON.stringify({
          filename: reviewFile?.name || `${reviewDate}复盘.txt`,
          content_base64: contentBase64,
          text: crawledText,
          review_date: reviewDate,
          api_key: apiKey,
        }),
      });
      setAnalysis(result);
      setActiveNav("布局分析");
      showNotice("RAG 分析完成，已同步生成 Word 文档。");
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "分析失败");
    } finally {
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
      let job: Job = {
        status: "pending",
        message: "准备更新知识库",
        current: 0,
        total: 1,
      };
      setSyncJob(job);
      while (job.status === "pending" || job.status === "running") {
        await new Promise((resolve) => window.setTimeout(resolve, 1200));
        job = await requestLocal<Job>(token, `/api/jobs/${started.job_id}`);
        setSyncJob(job);
      }
      if (job.status === "succeeded" && job.stats) {
        setStats(job.stats);
        showNotice("自爬取、清洗和知识库更新已完成。");
      } else {
        showNotice(job.message || "知识库更新失败");
      }
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "知识库更新失败");
      setSyncJob(null);
    }
  }

  function downloadDocument() {
    if (!analysis) {
      showNotice("请先完成一次真实分析。");
      return;
    }
    const binary = window.atob(analysis.document_base64);
    const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
    const blob = new Blob([bytes], {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = analysis.document_filename;
    anchor.click();
    URL.revokeObjectURL(url);
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
            {syncJob?.status === "running" ? `清洗中 ${syncJob.current}/${syncJob.total}` : "自爬取并清洗"}
          </button>
          <button className="btn btn-primary" disabled={isAnalyzing} onClick={handleAnalyze}>
            {isAnalyzing ? "正在检索分析…" : "开始分析"}
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
                <input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="只发送到 127.0.0.1" autoComplete="off" />
              </label>
            )}
            {apiKeyConfigured && <span className="key-ready">本机已配置模型密钥</span>}
          </div>

          {syncJob && (syncJob.status === "pending" || syncJob.status === "running") && (
            <div className="sync-progress">
              <div style={{ width: `${Math.round((syncJob.current / Math.max(syncJob.total, 1)) * 100)}%` }} />
              <span>{syncJob.message}</span>
            </div>
          )}

          <section className="judgement-card">
            <div className="judgement-topline">
              <span className="section-number">01</span>
              <span className="eyebrow">{analysis ? "RAG 核心判断" : "等待真实分析"}</span>
              <span className={`confidence ${analysis ? "" : "muted-confidence"}`}>{analysis ? `引用 ${evidence.length} 条资料` : "未使用演示行情"}</span>
            </div>
            <div className="judgement-grid">
              <div>
                <h3>{coreJudgement ? cleanMarkdown(coreJudgement).split("\n")[0] : "先导入或自爬取每日复盘，再判断谁在完成任务"}</h3>
                <p className={coreJudgement ? "analysis-text" : ""}>
                  {coreJudgement
                    ? cleanMarkdown(coreJudgement)
                    : "系统会先检索首板出身、本人回复和人工体系，再分析原始任务、布局关系、地位迁移与失败条件。"}
                </p>
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
              <div>
                <span className="section-number">02</span>
                <div><span className="eyebrow">布局关系</span><h3>{analysis ? "本次检索分析" : "任务如何在队形中传递 · 框架示意"}</h3></div>
              </div>
              <div className="legend">
                <span><i className="dot amber" />核心任务</span>
                <span><i className="dot green" />推进</span>
                <span><i className="dot red" />受阻</span>
              </div>
            </div>
            {layoutText && <div className="generated-analysis">{cleanMarkdown(layoutText)}</div>}
            <div className="relationship-map" aria-label="个股任务关系框架示意图">
              {frameworkTasks.map((task) => (
                <button key={task.id} className={`map-node ${task.id} ${selectedId === task.id ? "selected" : ""}`} onClick={() => setSelectedId(task.id)}>
                  <small>{task.role.slice(0, 2)}</small>
                  <strong>{task.name}</strong>
                  <span>{task.position}</span>
                </button>
              ))}
              <div className="relation-line line-a"><span>带动</span></div>
              <div className="relation-line line-b"><span>反馈</span></div>
              <div className="relation-line line-c"><span>验证</span></div>
              <div className="map-center"><span>市场合力</span><strong>任务迁移</strong></div>
            </div>
          </section>

          <section className="panel matrix-panel">
            <div className="panel-heading">
              <div>
                <span className="section-number">03</span>
                <div><span className="eyebrow">个股任务</span><h3>{taskText ? "模型提取的任务表" : "从首板出身追踪地位变化 · 框架示意"}</h3></div>
              </div>
            </div>
            {taskText ? (
              <div className="task-output">{cleanMarkdown(taskText)}</div>
            ) : (
              <div className="task-table-wrap">
                <table className="task-table">
                  <thead><tr><th>对象 / 角色</th><th>首板出身</th><th>原始任务</th><th>当前位置</th><th>协同 / 压制</th><th>状态</th></tr></thead>
                  <tbody>
                    {frameworkTasks.map((task) => (
                      <tr key={task.id} className={selectedId === task.id ? "selected-row" : ""} onClick={() => setSelectedId(task.id)}>
                        <td><strong>{task.name}</strong><small>{task.role}</small></td>
                        <td>{task.origin}</td><td>{task.task}</td><td>{task.position}</td><td>{task.relation}</td>
                        <td><span className={`state state-${task.state}`}>{task.state}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="tomorrow-grid">
            <article>
              <span className="eyebrow">明日竞价确认</span>
              <h3>{analysis ? "完成任务需要出现什么" : `${selectedTask.name} · 等待分析`}</h3>
              <p className={tomorrowText ? "analysis-text" : ""}>{tomorrowText ? cleanMarkdown(tomorrowText) : "真实分析完成后自动生成。"}</p>
            </article>
            <article className="failure-card">
              <span className="eyebrow">失效条件</span>
              <h3>什么时候必须推翻当前判断</h3>
              <p className={failureText ? "analysis-text" : ""}>{failureText ? cleanMarkdown(failureText) : "真实分析完成后自动生成。"}</p>
            </article>
          </section>
        </section>

        <aside className="evidence-panel">
          <div className="evidence-header"><span className="eyebrow">RAG 证据链</span><span className="evidence-count">{evidence.length} 条</span></div>
          <h2>{analysis ? "本次真实引用" : "等待检索"}</h2>
          <p className="evidence-intro">优先级：本人回复 → 历史原帖 → 人工整理体系 → 社区精选观点。</p>
          <div className="evidence-list">
            {evidence.length ? evidence.map((item, index) => (
              <article className="evidence-item" key={`${item.source_url}-${index}`}>
                <div className="evidence-meta"><span>{item.level}</span><span className={item.source_type === "qa" ? "primary-tag" : ""}>{item.published_at}</span></div>
                <h3>{item.title}</h3>
                <p>{item.excerpt}</p>
                <a href={item.source_url} target="_blank" rel="noreferrer">查看原文定位 →</a>
              </article>
            )) : (
              <div className="empty-evidence">
                <strong>这里不会放虚构引用</strong>
                <p>完成一次真实 RAG 分析后，才会显示检索到的原帖、回复和体系片段。</p>
              </div>
            )}
          </div>
          <div className="evidence-rule">
            <strong>分析固定顺序</strong>
            <ol><li>首板出身</li><li>原始任务</li><li>布局关系与地位变化</li><li>完成信号与失效条件</li></ol>
          </div>
          <button className="export-button" disabled={!analysis} onClick={downloadDocument}>
            <span>生成今日复盘文档</span><small>{analysis ? "点击下载 Word" : "完成分析后启用"}</small>
          </button>
        </aside>
      </div>
      {notice && <div className="toast" role="status">{notice}</div>}
    </main>
  );
}
