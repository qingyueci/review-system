import { Job } from "../lib/review-api";
import { KnowledgePost, Stats } from "../lib/review-types";

type Props = {
  stats: Stats;
  syncJob: Job | null;
  posts: KnowledgePost[];
  onSync: () => void;
};

export function KnowledgeSection({
  stats,
  syncJob,
  posts,
  onSync,
}: Props) {
  const syncing = Boolean(
    syncJob &&
      syncJob.status !== "failed" &&
      syncJob.status !== "succeeded",
  );
  return (
    <>
      <section className="knowledge-hero">
        <div>
          <span className="eyebrow">本机 RAG 状态</span>
          <h3>{stats.chunks.toLocaleString()} 条证据已建立检索索引</h3>
          <p>
            {stats.qa_pairs.toLocaleString()} 条原始回复已保留，{stats.retrievable_qa.toLocaleString()} 条代表回复进入检索。
          </p>
        </div>
        <button disabled={syncing} onClick={onSync}>
          {syncJob?.status === "running"
            ? "正在执行…"
            : "一键更新并语义清洗"}
        </button>
      </section>
      {syncJob &&
        (syncJob.status === "pending" || syncJob.status === "running") && (
          <div className="sync-progress">
            <div
              style={{
                width: `${Math.round(
                  (syncJob.current / Math.max(syncJob.total, 1)) * 100,
                )}%`,
              }}
            />
            <span>{syncJob.message}</span>
          </div>
        )}
      <section className="stat-grid">
        <article>
          <span>核心原帖</span>
          <strong>{stats.core_posts}</strong>
          <small>固定核心库，不参与日常更新</small>
        </article>
        <article>
          <span>近期补充帖</span>
          <strong>{stats.supplemental_posts}</strong>
          <small>增量更新近期 10 篇 · 滚动维护最新 10 篇</small>
        </article>
        <article>
          <span>历史归档帖</span>
          <strong>{stats.archived_posts}</strong>
          <small>保留参考价值，降低检索权重</small>
        </article>
        <article>
          <span>本人回复</span>
          <strong>{stats.qa_pairs.toLocaleString()}</strong>
          <small>原文全部保留</small>
        </article>
        <article>
          <span>代表回复</span>
          <strong>{stats.retrievable_qa.toLocaleString()}</strong>
          <small>进入主检索索引</small>
        </article>
        <article>
          <span>语义合并</span>
          <strong>{stats.semantic_duplicates.toLocaleString()}</strong>
          <small>{stats.semantic_cleaned_at.slice(0, 10)}</small>
        </article>
        <article>
          <span>社区精选</span>
          <strong>{stats.community_comments}</strong>
          <small>只作共识与疑问补充</small>
        </article>
        <article>
          <span>人工体系切片</span>
          <strong>{stats.manual_chunks}</strong>
          <small>本地整理文档</small>
        </article>
        <article>
          <span>最近同步</span>
          <strong className="date-stat">{stats.last_sync.slice(0, 10)}</strong>
          <small>{stats.last_sync.replace("T", " ")}</small>
        </article>
      </section>
      <section className="panel source-library-panel">
        <div className="panel-heading">
          <div>
            <span className="section-number">02</span>
            <div>
              <span className="eyebrow">采集明细</span>
              <h3>已进入知识库的公开帖子</h3>
            </div>
          </div>
          <span className="hint">{posts.length} 篇</span>
        </div>
        <div className="source-table-wrap">
          <table className="source-table">
            <thead>
              <tr>
                <th>标题</th>
                <th>日期</th>
                <th>浏览</th>
                <th>评论</th>
                <th>点赞</th>
                <th>用途</th>
                <th>正文</th>
              </tr>
            </thead>
            <tbody>
              {posts.map((post) => (
                <tr key={post.url}>
                  <td>
                    <a href={post.url} target="_blank" rel="noreferrer">
                      {post.title}
                    </a>
                  </td>
                  <td>{post.published_at}</td>
                  <td>{post.views.toLocaleString()}</td>
                  <td>{post.reply_count.toLocaleString()}</td>
                  <td>{post.likes.toLocaleString()}</td>
                  <td>
                    {post.scope === "top_year"
                      ? "固定高阅读量核心"
                      : post.scope === "recent_qa"
                        ? "近期问答补充"
                        : "历史问答归档"}
                  </td>
                  <td>
                    <span
                      className={
                        post.body_truncated
                          ? "source-badge warning"
                          : "source-badge"
                      }
                    >
                      {post.body_truncated ? "公开节选" : "完整"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
