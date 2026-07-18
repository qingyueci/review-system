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
          <p>更新会自动完成发现、抓取、去重、清洗、分段和索引重建。</p>
        </div>
        <button disabled={syncing} onClick={onSync}>
          {syncJob?.status === "running"
            ? "正在更新…"
            : "更新知识库（爬取并清洗）"}
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
          <small>近一年高阅读量前 20</small>
        </article>
        <article>
          <span>近期补充帖</span>
          <strong>{stats.supplemental_posts}</strong>
          <small>补充公开问答语境</small>
        </article>
        <article>
          <span>本人回复</span>
          <strong>{stats.qa_pairs.toLocaleString()}</strong>
          <small>作者原始语境优先</small>
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
      <section className="panel cleaning-panel">
        <span className="eyebrow">清洗规则</span>
        <h3>什么会保留，什么会被降权</h3>
        <div className="cleaning-columns">
          <div>
            <strong>保留</strong>
            <p>
              完整正文、本人有效回复、问题上下文、高赞且有布局信息的评论、人工体系文档。
            </p>
          </div>
          <div>
            <strong>降权或过滤</strong>
            <p>
              重复文本、空话、广告、过短回复、脱离布局语境的泛泛评论以及网页噪声。
            </p>
          </div>
        </div>
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
                      ? "高阅读量核心"
                      : "近期问答补充"}
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
