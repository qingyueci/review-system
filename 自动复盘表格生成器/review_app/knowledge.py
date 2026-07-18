from collections import Counter
from datetime import datetime
import json
import re
import sqlite3
from typing import Callable

from docx import Document
import jieba

from .cleaning import content_hash, normalize_text, split_chunks
from .config import CRAWL_TOP_POST_LIMIT, KNOWLEDGE_DB_PATH, MANUAL_SYSTEM_DOCX
from .crawler import TgbCrawler

jieba.setLogLevel(20)

STOP_WORDS = {
    "一个", "今天", "明天", "这个", "那个", "还是", "就是", "感觉", "怎么", "什么",
    "已经", "没有", "可以", "如果", "因为", "所以", "但是", "然后", "一下", "现在",
    "市场", "个股", "板块", "老师", "刺大", "发财",
}
CRAWL_PIPELINE_VERSION = 3


def _tokens(value: str, *, maximum: int = 80) -> list[str]:
    text = normalize_text(value)
    words = [
        word.strip().lower()
        for word in jieba.lcut(text)
        if word.strip() and (len(word.strip()) > 1 or word.strip().isascii())
    ]
    words = [word for word in words if word not in STOP_WORDS and not re.fullmatch(r"\W+", word)]
    cjk = re.sub(r"[^\u4e00-\u9fff]", "", text)
    bigrams = [f"g_{cjk[index:index + 2]}" for index in range(max(0, len(cjk) - 1))]
    ranked = [item for item, _count in Counter(words + bigrams).most_common(maximum)]
    return ranked


def _index_text(value: str) -> str:
    return " ".join(_tokens(value, maximum=400))


class KnowledgeStore:
    def __init__(self, path=KNOWLEDGE_DB_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self._create_schema()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def _create_schema(self) -> None:
        self.connection.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS posts (
                url TEXT PRIMARY KEY,
                topic_id TEXT,
                title TEXT NOT NULL,
                published_at TEXT NOT NULL,
                views INTEGER NOT NULL DEFAULT 0,
                reply_count INTEGER NOT NULL DEFAULT 0,
                likes INTEGER NOT NULL DEFAULT 0,
                summary TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT '',
                body_hash TEXT NOT NULL DEFAULT '',
                body_truncated INTEGER NOT NULL DEFAULT 0,
                comments_accessible INTEGER NOT NULL DEFAULT 0,
                useful_comment_count INTEGER NOT NULL DEFAULT 0,
                total_comment_pages INTEGER NOT NULL DEFAULT 0,
                scanned_comment_pages TEXT NOT NULL DEFAULT '[]',
                scope TEXT NOT NULL DEFAULT 'top_year',
                capture_mode TEXT NOT NULL DEFAULT 'public_http',
                pipeline_version INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS qa_pairs (
                reply_id TEXT PRIMARY KEY,
                post_url TEXT NOT NULL,
                question TEXT NOT NULL DEFAULT '',
                answer TEXT NOT NULL,
                question_author TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL DEFAULT '',
                floor INTEGER NOT NULL DEFAULT 0,
                likes INTEGER NOT NULL DEFAULT 0,
                source_url TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                FOREIGN KEY(post_url) REFERENCES posts(url) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL,
                source_id TEXT NOT NULL,
                post_url TEXT NOT NULL,
                title TEXT NOT NULL,
                published_at TEXT NOT NULL,
                content TEXT NOT NULL,
                source_url TEXT NOT NULL,
                chunk_order INTEGER NOT NULL DEFAULT 0,
                search_text TEXT NOT NULL,
                UNIQUE(source_type, source_id, chunk_order)
            );
            CREATE TABLE IF NOT EXISTS crawl_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                discovered INTEGER NOT NULL,
                fetched INTEGER NOT NULL,
                reused INTEGER NOT NULL,
                failed INTEGER NOT NULL,
                error_details TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS local_sources (
                path TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                modified_at TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                content TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        existing_columns = {
            row["name"] for row in self.connection.execute("PRAGMA table_info(posts)").fetchall()
        }
        for name in ("body_truncated", "comments_accessible", "useful_comment_count"):
            if name not in existing_columns:
                self.connection.execute(
                    f"ALTER TABLE posts ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0"
                )
        if "pipeline_version" not in existing_columns:
            self.connection.execute(
                "ALTER TABLE posts ADD COLUMN pipeline_version INTEGER NOT NULL DEFAULT 1"
            )
        if "capture_mode" not in existing_columns:
            self.connection.execute(
                "ALTER TABLE posts ADD COLUMN capture_mode TEXT NOT NULL DEFAULT 'public_http'"
            )
        try:
            self.connection.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
                USING fts5(chunk_id UNINDEXED, search_text)
            """)
        except sqlite3.OperationalError as exc:
            raise RuntimeError("当前 Python 的 SQLite 不支持 FTS5，无法建立本地检索索引") from exc
        self.connection.commit()

    def post_state(self, url: str) -> dict | None:
        row = self.connection.execute(
            """
            SELECT reply_count, body_hash, pipeline_version, capture_mode
            FROM posts WHERE url = ?
            """,
            (url,),
        ).fetchone()
        return dict(row) if row else None

    def update_post_metrics(self, post: dict, scope: str) -> None:
        self.connection.execute(
            """
            UPDATE posts
            SET views = ?, reply_count = ?, likes = ?, summary = ?, scope = ?, updated_at = ?
            WHERE url = ?
            """,
            (
                post["views"], post["reply_count"], post["likes"], post.get("summary", ""),
                scope, datetime.now().isoformat(timespec="seconds"), post["url"],
            ),
        )
        self.connection.commit()

    def upsert_post(
        self,
        post: dict,
        *,
        scope: str = "top_year",
        rebuild_index: bool = True,
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO posts (
                    url, topic_id, title, published_at, views, reply_count, likes, summary,
                    body, body_hash, total_comment_pages, scanned_comment_pages, scope, updated_at,
                    body_truncated, comments_accessible, useful_comment_count,
                    capture_mode, pipeline_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    topic_id=excluded.topic_id, title=excluded.title,
                    published_at=excluded.published_at, views=excluded.views,
                    reply_count=excluded.reply_count, likes=excluded.likes,
                    summary=excluded.summary, body=excluded.body,
                    body_hash=excluded.body_hash,
                    body_truncated=excluded.body_truncated,
                    comments_accessible=excluded.comments_accessible,
                    useful_comment_count=excluded.useful_comment_count,
                    capture_mode=excluded.capture_mode,
                    total_comment_pages=excluded.total_comment_pages,
                    scanned_comment_pages=excluded.scanned_comment_pages,
                    scope=excluded.scope, pipeline_version=excluded.pipeline_version,
                    updated_at=excluded.updated_at
                """,
                (
                    post["url"], post.get("topic_id", ""), post["title"], post["published_at"],
                    post["views"], post["reply_count"], post["likes"], post.get("summary", ""),
                    post["body"], post["body_hash"], post.get("total_comment_pages", 0),
                    json.dumps(post.get("scanned_comment_pages", []), ensure_ascii=False),
                    scope, now, int(post.get("body_truncated", False)),
                    int(post.get("comments_accessible", False)),
                    int(post.get("useful_comment_count", 0)),
                    post.get("capture_mode", "public_http"),
                    CRAWL_PIPELINE_VERSION,
                ),
            )
            self.connection.execute("DELETE FROM qa_pairs WHERE post_url = ?", (post["url"],))
            self.connection.execute("DELETE FROM chunks WHERE post_url = ?", (post["url"],))

            for reply in post.get("author_replies", []):
                answer = normalize_text(reply["answer"])
                question = normalize_text(reply.get("question", ""))
                self.connection.execute(
                    """
                    INSERT OR REPLACE INTO qa_pairs (
                        reply_id, post_url, question, answer, question_author,
                        published_at, floor, likes, source_url, content_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        reply["reply_id"], post["url"], question, answer,
                        reply.get("question_author", ""), reply.get("published_at", ""),
                        reply.get("floor", 0), reply.get("likes", 0), reply["source_url"],
                        content_hash(question, answer),
                    ),
                )

            article_prefix = "【网页公开节选】\n" if post.get("body_truncated") else ""
            for order, chunk in enumerate(split_chunks(post["body"])):
                self._insert_chunk(
                    "post", post["url"], post, article_prefix + chunk, post["url"], order,
                )
            for reply in post.get("author_replies", []):
                question = normalize_text(reply.get("question", ""))
                answer = normalize_text(reply["answer"])
                combined = f"用户问题：{question}\n刺大回复：{answer}" if question else f"刺大评论：{answer}"
                self._insert_chunk(
                    "qa", reply["reply_id"], post, combined, reply["source_url"], 0,
                )
            for comment in post.get("community_comments", []):
                answer = normalize_text(comment["answer"])
                quote = normalize_text(comment.get("question", ""))
                author = normalize_text(comment.get("author_name", "")) or "社区用户"
                likes = int(comment.get("likes", 0))
                combined = f"社区精选评论（{author}，点赞{likes}）：{answer}"
                if quote:
                    combined += f"\n引用上下文：{quote}"
                self._insert_chunk(
                    "community", comment["reply_id"], post, combined,
                    comment["source_url"], 0,
                )
        if rebuild_index:
            self.rebuild_fts()

    def import_manual_docx(self, path=MANUAL_SYSTEM_DOCX) -> dict:
        """把人工整理的 Word 体系文件清洗、切片后加入检索库。"""
        source_path = path.resolve()
        if not source_path.is_file():
            raise RuntimeError(f"没有找到本地体系文件：{source_path}")

        document = Document(source_path)
        sections: list[str] = []
        for paragraph in document.paragraphs:
            text = normalize_text(paragraph.text)
            if not text:
                continue
            style_name = paragraph.style.name if paragraph.style else ""
            if style_name.startswith("Heading") or style_name.startswith("标题"):
                text = f"章节：{text}"
            sections.append(text)
        for table in document.tables:
            for row in table.rows:
                values = [normalize_text(cell.text) for cell in row.cells]
                values = [value for value in values if value]
                if values:
                    sections.append(" | ".join(values))
        content = normalize_text("\n\n".join(sections))
        if not content:
            raise RuntimeError(f"本地体系文件没有可读取的文字：{source_path}")

        digest = content_hash(content)
        path_text = str(source_path)
        current = self.connection.execute(
            "SELECT content_hash FROM local_sources WHERE path = ?", (path_text,)
        ).fetchone()
        if current and current["content_hash"] == digest:
            return {"imported": False, "path": path_text, "chunks": 0}

        modified_at = datetime.fromtimestamp(source_path.stat().st_mtime).isoformat(
            timespec="seconds"
        )
        source_key = f"manual:{path_text}"
        source = {
            "url": source_key,
            "title": source_path.stem,
            "published_at": modified_at,
        }
        chunks = split_chunks(content)
        with self.connection:
            self.connection.execute(
                "DELETE FROM chunks WHERE source_type='manual' AND post_url = ?",
                (source_key,),
            )
            self.connection.execute(
                """
                INSERT INTO local_sources (
                    path, title, modified_at, content_hash, content, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    title=excluded.title, modified_at=excluded.modified_at,
                    content_hash=excluded.content_hash, content=excluded.content,
                    updated_at=excluded.updated_at
                """,
                (
                    path_text, source_path.stem, modified_at, digest, content,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            for order, chunk in enumerate(chunks):
                self._insert_chunk(
                    "manual", source_key, source, chunk, source_path.as_uri(), order,
                )
        self.rebuild_fts()
        return {"imported": True, "path": path_text, "chunks": len(chunks)}

    def _insert_chunk(
        self,
        source_type: str,
        source_id: str,
        post: dict,
        content: str,
        source_url: str,
        order: int,
    ) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO chunks (
                source_type, source_id, post_url, title, published_at,
                content, source_url, chunk_order, search_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_type, source_id, post["url"], post["title"], post["published_at"],
                content, source_url, order, _index_text(content),
            ),
        )

    def prune_scope_to_urls(self, scope: str, urls: list[str]) -> None:
        if not urls:
            return
        placeholders = ",".join("?" for _ in urls)
        with self.connection:
            stale = self.connection.execute(
                f"SELECT url FROM posts WHERE scope=? AND url NOT IN ({placeholders})", [scope, *urls]
            ).fetchall()
            stale_urls = [row["url"] for row in stale]
            if stale_urls:
                stale_placeholders = ",".join("?" for _ in stale_urls)
                self.connection.execute(f"DELETE FROM qa_pairs WHERE post_url IN ({stale_placeholders})", stale_urls)
                self.connection.execute(f"DELETE FROM chunks WHERE post_url IN ({stale_placeholders})", stale_urls)
                self.connection.execute(f"DELETE FROM posts WHERE url IN ({stale_placeholders})", stale_urls)
        self.rebuild_fts()

    def rebuild_fts(self) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM chunks_fts")
            self.connection.execute(
                "INSERT INTO chunks_fts(chunk_id, search_text) SELECT id, search_text FROM chunks"
            )

    def search(self, query: str, *, limit: int = 12) -> list[dict]:
        terms = _tokens(query, maximum=30)
        if not terms:
            return []
        match_query = " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)
        rows = self.connection.execute(
            """
            SELECT c.*, bm25(chunks_fts) AS rank
            FROM chunks_fts
            JOIN chunks c ON c.id = CAST(chunks_fts.chunk_id AS INTEGER)
            WHERE chunks_fts MATCH ?
            ORDER BY rank ASC, c.published_at DESC
            LIMIT ?
            """,
            (match_query, limit * 6),
        ).fetchall()
        # 先保证作者原文和人工体系进入上下文，再用社区观点补充。
        source_limits = {"qa": 4, "post": 3, "manual": 3, "community": 2}
        ordered_rows = []
        for source_type in ("qa", "post", "manual", "community"):
            ordered_rows.extend(
                row for row in rows
                if row["source_type"] == source_type
            )

        # 同一来源最多保留三条，避免单篇长文垄断上下文。
        selected: list[dict] = []
        per_post: Counter = Counter()
        per_type: Counter = Counter()
        for row in ordered_rows:
            if per_post[row["post_url"]] >= 3:
                continue
            if per_type[row["source_type"]] >= source_limits.get(row["source_type"], 2):
                continue
            selected.append(dict(row))
            per_post[row["post_url"]] += 1
            per_type[row["source_type"]] += 1
            if len(selected) >= limit:
                break
        # 配额没有填满时，按原始相关度顺序补齐。
        selected_ids = {item["id"] for item in selected}
        for row in rows:
            if len(selected) >= limit:
                break
            if row["id"] in selected_ids or per_post[row["post_url"]] >= 3:
                continue
            selected.append(dict(row))
            selected_ids.add(row["id"])
            per_post[row["post_url"]] += 1
        return selected

    def stats(self) -> dict:
        post_count = self.connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        core_count = self.connection.execute(
            "SELECT COUNT(*) FROM posts WHERE scope='top_year'"
        ).fetchone()[0]
        supplemental_count = self.connection.execute(
            "SELECT COUNT(*) FROM posts WHERE scope='recent_qa'"
        ).fetchone()[0]
        qa_count = self.connection.execute("SELECT COUNT(*) FROM qa_pairs").fetchone()[0]
        community_count = self.connection.execute(
            "SELECT COUNT(*) FROM chunks WHERE source_type='community'"
        ).fetchone()[0]
        manual_source_count = self.connection.execute(
            "SELECT COUNT(*) FROM local_sources"
        ).fetchone()[0]
        manual_chunk_count = self.connection.execute(
            "SELECT COUNT(*) FROM chunks WHERE source_type='manual'"
        ).fetchone()[0]
        chunk_count = self.connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        last_run = self.connection.execute(
            "SELECT finished_at FROM crawl_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return {
            "posts": post_count,
            "core_posts": core_count,
            "supplemental_posts": supplemental_count,
            "qa_pairs": qa_count,
            "community_comments": community_count,
            "manual_sources": manual_source_count,
            "manual_chunks": manual_chunk_count,
            "chunks": chunk_count,
            "last_sync": last_run["finished_at"] if last_run else "尚未同步",
        }

    def list_posts(self) -> list[dict]:
        return [
            dict(row)
            for row in self.connection.execute(
                """
                SELECT title, published_at, views, reply_count, likes,
                       scope, body_truncated, comments_accessible,
                       useful_comment_count, capture_mode, total_comment_pages,
                       scanned_comment_pages, url
                FROM posts ORDER BY views DESC
                """
            ).fetchall()
        ]

    def record_run(self, result: dict) -> None:
        self.connection.execute(
            """
            INSERT INTO crawl_runs (
                started_at, finished_at, discovered, fetched, reused, failed, error_details
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result["started_at"], result["finished_at"], result["discovered"],
                result["fetched"], result["reused"], result["failed"],
                "\n".join(result["errors"]),
            ),
        )
        self.connection.commit()


def sync_top_year(
    progress: Callable[[str, int, int], None] | None = None,
) -> dict:
    started_at = datetime.now().isoformat(timespec="seconds")
    with TgbCrawler() as crawler, KnowledgeStore() as store:
        posts = crawler.discover_top_posts(
            days=365,
            limit=CRAWL_TOP_POST_LIMIT,
            progress=progress,
        )
        recent_posts = crawler.discover_recent_posts(limit=10)
        top_urls = {post["url"] for post in posts}
        supplements = [post for post in recent_posts if post["url"] not in top_urls]
        work_items = [(post, "top_year") for post in posts] + [
            (post, "recent_qa") for post in supplements
        ]
        result = {
            "started_at": started_at,
            "finished_at": "",
            "discovered": len(work_items),
            "core_posts": len(posts),
            "supplemental_posts": len(supplements),
            "fetched": 0,
            "reused": 0,
            "failed": 0,
            "errors": [],
        }
        for index, (post, scope) in enumerate(work_items, 1):
            if progress:
                label = "高阅读量主帖" if scope == "top_year" else "近期公开问答补充"
                progress(f"正在处理 {index}/{len(work_items)}：{post['title']}（{label}）", index, len(work_items))
            state = store.post_state(post["url"])
            if (
                state
                and state["body_hash"]
                and (
                    state["capture_mode"] == "authenticated_browser"
                    or (
                        state["pipeline_version"] == CRAWL_PIPELINE_VERSION
                        and state["reply_count"] == post["reply_count"]
                    )
                )
            ):
                store.update_post_metrics(post, scope)
                result["reused"] += 1
                continue
            try:
                store.upsert_post(crawler.fetch_post(post), scope=scope)
                result["fetched"] += 1
            except RuntimeError as exc:
                result["failed"] += 1
                result["errors"].append(f"{post['title']}：{exc}")
        store.prune_scope_to_urls("top_year", [post["url"] for post in posts])
        if supplements:
            store.prune_scope_to_urls("recent_qa", [post["url"] for post in supplements])
        try:
            result["manual_source"] = store.import_manual_docx()
        except RuntimeError as exc:
            result["manual_source"] = {"imported": False, "error": str(exc)}
        result["finished_at"] = datetime.now().isoformat(timespec="seconds")
        store.record_run(result)
        return result
