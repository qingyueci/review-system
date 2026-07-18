import { Job } from "../lib/review-api";
import {
  AnalysisResult,
  GenerationMode,
} from "../lib/review-types";

type Props = {
  reviewFile: File | null;
  crawledText: string;
  crawledSource: string;
  apiKeyConfigured: boolean;
  apiKey: string;
  onApiKeyChange: (value: string) => void;
  actionMessage: string;
  isAnalyzing: boolean;
  generationMode: GenerationMode;
  onGenerationModeChange: (mode: GenerationMode) => void;
  generatesExcel: boolean;
  generatesWord: boolean;
  generationJob: Job<AnalysisResult> | null;
  analysis: AnalysisResult | null;
  onRetry: (branch: "excel" | "word") => void;
  onAnalyze: () => void;
  generationLabel: string;
  hasGeneratedFiles: boolean;
  onDownloadExcel: () => void;
  onDownloadWord: () => void;
};

export function TodayReviewSection({
  reviewFile,
  crawledText,
  crawledSource,
  apiKeyConfigured,
  apiKey,
  onApiKeyChange,
  actionMessage,
  isAnalyzing,
  generationMode,
  onGenerationModeChange,
  generatesExcel,
  generatesWord,
  generationJob,
  analysis,
  onRetry,
  onAnalyze,
  generationLabel,
  hasGeneratedFiles,
  onDownloadExcel,
  onDownloadWord,
}: Props) {
  return (
    <>
      <section className="intake-card">
        <div className="intake-heading">
          <span className="section-number">01</span>
          <div>
            <span className="eyebrow">生成输入</span>
            <h3>选择文件，或直接自爬取当日复盘</h3>
          </div>
        </div>
        <div className="input-status-row">
          <div>
            <span
              className={reviewFile || crawledText ? "ready-dot" : "empty-dot"}
            />
            {reviewFile
              ? reviewFile.name
              : crawledText
                ? "已载入公开复盘正文"
                : "尚未载入每日复盘"}
            {crawledSource && (
              <a href={crawledSource} target="_blank" rel="noreferrer">
                查看来源
              </a>
            )}
          </div>
          {!apiKeyConfigured && (
            <label className="api-key-field">
              <span>Kimi Code Key</span>
              <input
                type="password"
                value={apiKey}
                onChange={(event) => onApiKeyChange(event.target.value)}
                placeholder="只发送到 127.0.0.1"
                autoComplete="off"
              />
            </label>
          )}
          {apiKeyConfigured && (
            <span className="key-ready">本机已配置模型密钥</span>
          )}
        </div>
        {actionMessage && (
          <div className={`action-message ${isAnalyzing ? "working" : ""}`}>
            {actionMessage}
          </div>
        )}
        <div
          className="generation-mode"
          role="radiogroup"
          aria-label="生成内容"
        >
          {(
            [
              ["both", "同时生成", "完整 Excel + 核心 Word"],
              ["excel", "只生成 Excel", "完整整理，不新增观点"],
              ["word", "只生成 Word", "只分析核心任务"],
            ] as const
          ).map(([mode, title, description]) => (
            <button
              key={mode}
              type="button"
              role="radio"
              aria-checked={generationMode === mode}
              className={generationMode === mode ? "active" : ""}
              disabled={
                isAnalyzing ||
                (mode === "excel" &&
                  Boolean(reviewFile?.name.toLowerCase().endsWith(".xlsx")))
              }
              onClick={() => onGenerationModeChange(mode)}
            >
              <strong>{title}</strong>
              <small>{description}</small>
            </button>
          ))}
        </div>
        <div className="pipeline-row">
          <div>
            <span>1</span>
            <strong>载入并清洗</strong>
            <small>文件或公开原帖</small>
          </div>
          <i>→</i>
          <div>
            <span>2</span>
            <strong>并行启动</strong>
            <small>两条链路互不拖累</small>
          </div>
          <i>→</i>
          <div className={generatesExcel ? "" : "muted-step"}>
            <span>X</span>
            <strong>Excel 完整整理</strong>
            <small>保留全部复盘信息</small>
          </div>
          <i>→</i>
          <div className={generatesWord ? "" : "muted-step"}>
            <span>W</span>
            <strong>Word 核心分析</strong>
            <small>只写有地位的个股</small>
          </div>
        </div>
        {(generationJob?.branches || analysis?.branches) && (
          <div className="branch-status-grid">
            {(["excel", "word"] as const).map((name) => {
              const branch =
                (isAnalyzing
                  ? generationJob?.branches?.[name]
                  : analysis?.branches[name]) ?? generationJob?.branches?.[name];
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
                        onClick={() => onRetry(name)}
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
        <button
          className="primary-run-button"
          disabled={isAnalyzing}
          onClick={onAnalyze}
        >
          <span>
            {isAnalyzing ? "正在生成并保存结果…" : generationLabel}
          </span>
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
                onClick={onDownloadExcel}
              >
                下载 Excel
              </button>
              <button
                disabled={!analysis.document_filename}
                onClick={onDownloadWord}
              >
                下载 Word
              </button>
            </div>
          </div>
        )}
      </section>
      <section className="today-note-grid">
        <article>
          <span className="eyebrow">分析主线</span>
          <h3>首板出身决定原始任务</h3>
          <p>先确认从哪里发酵、为谁开路，再判断个股是否完成任务。</p>
        </article>
        <article>
          <span className="eyebrow">明确禁止</span>
          <h3>不用普通技术分析冲掉布局核心</h3>
          <p>价格、量能和均线只能作为任务是否被确认的证据。</p>
        </article>
      </section>
    </>
  );
}
