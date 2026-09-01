import { HistoryDocument, RunRecord } from "../lib/review-types";

type Props = {
  documents: HistoryDocument[];
  runs: RunRecord[];
  onDownload: (filename: string) => void;
  onGoToToday: () => void;
};

export function HistoryDocumentsSection({
  documents,
  runs,
  onDownload,
  onGoToToday,
}: Props) {
  const durationText = (milliseconds = 0) =>
    milliseconds >= 60_000
      ? `${(milliseconds / 60_000).toFixed(1)} 分钟`
      : `${Math.max(0, milliseconds / 1000).toFixed(1)} 秒`;
  const sourceLabels: Record<string, string> = {
    qa: "本人回复",
    post: "历史主帖",
    manual: "人工体系",
    community: "社区评论",
  };

  return (
    <>
      <section className="history-panel">
      <div className="history-heading">
        <div>
          <span className="eyebrow">本机保存</span>
          <h3>已生成的 Excel 与 Word</h3>
        </div>
        <span>{documents.length} 份</span>
      </div>
      {documents.length ? (
        <div className="document-list">
          {documents.map((item) => (
            <article key={item.filename}>
              <div className={`doc-icon ${item.kind}`}>
                {item.kind === "excel" ? "X" : "W"}
              </div>
              <div>
                <strong>{item.filename}</strong>
                <small>
                  {item.modified_at.replace("T", " ")} ·{" "}
                  {Math.max(1, Math.round(item.size / 1024))} KB
                </small>
              </div>
              <button onClick={() => onDownload(item.filename)}>下载</button>
            </article>
          ))}
        </div>
      ) : (
        <div className="page-empty compact">
          <h3>还没有生成文件</h3>
          <p>每次运行后，成功生成的 Excel 和 Word 都会独立保存到这里。</p>
          <button onClick={onGoToToday}>开始第一次生成</button>
        </div>
      )}
      </section>
      <section className="run-log-panel">
        <div className="history-heading">
          <div>
            <span className="eyebrow">运行记录</span>
            <h3>模型调用与生成链路</h3>
          </div>
          <span>{runs.length} 次</span>
        </div>
        {runs.length ? (
          <div className="run-log-list">
            {runs.map((run) => (
              <article className="run-log-item" key={run.job_id}>
                <div className="run-log-head">
                  <div>
                    <strong>{run.review_date || "未标日期"}复盘</strong>
                    <small>
                      {run.started_at.replace("T", " ")} ·{" "}
                      {durationText(run.duration_ms)}
                      {run.retry_of ? " · 单项重试" : ""}
                    </small>
                  </div>
                  <span className={`run-state ${run.status}`}>
                    {run.status === "succeeded"
                      ? "已完成"
                      : run.status === "failed"
                        ? "失败"
                        : "运行中"}
                  </span>
                </div>
                <div className="run-branch-grid">
                  {(["excel", "word"] as const).map((name) => {
                    const branch = run.branches[name];
                    const usage = branch?.usage;
                    return (
                      <div className={`run-branch ${branch?.status}`} key={name}>
                        <div>
                          <strong>{name === "excel" ? "Excel" : "Word"}</strong>
                          <span>{branch?.message || "没有运行"}</span>
                        </div>
                        <small>
                          耗时 {durationText(branch?.duration_ms)}
                          {name === "word"
                            ? ` · 引用 ${branch?.source_count ?? 0} 条`
                            : ""}
                        </small>
                        <small>
                          模型消耗：
                          {usage?.available
                            ? `${usage.total_tokens ?? 0} tokens`
                            : "供应商未返回"}
                        </small>
                        {branch?.error_type && (
                          <small className="run-error">
                            失败类型：{branch.error_type}
                          </small>
                        )}
                      </div>
                    );
                  })}
                </div>
                {run.sources.length > 0 && (
                  <details className="run-sources">
                    <summary>查看本次引用资料</summary>
                    <div>
                      {run.sources.map((source, index) => (
                        <a
                          href={source.source_url}
                          target="_blank"
                          rel="noreferrer"
                          key={`${source.source_url}-${index}`}
                        >
                          <span>
                            {sourceLabels[source.source_type] || "公开资料"}
                          </span>
                          <strong>{source.title}</strong>
                          <small>
                            相关度{" "}
                            {Math.round((source.retrieval_score || 0) * 100)}%
                          </small>
                        </a>
                      ))}
                    </div>
                  </details>
                )}
              </article>
            ))}
          </div>
        ) : (
          <div className="page-empty compact">
            <h3>还没有运行记录</h3>
          <p>下一次生成后，这里会显示两条链路的耗时、引用和失败原因；失败分支支持降级归档。</p>
          </div>
        )}
      </section>
    </>
  );
}
