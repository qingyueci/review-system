import { HistoryDocument } from "../lib/review-types";

type Props = {
  documents: HistoryDocument[];
  onDownload: (filename: string) => void;
  onGoToToday: () => void;
};

export function HistoryDocumentsSection({
  documents,
  onDownload,
  onGoToToday,
}: Props) {
  return (
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
  );
}
