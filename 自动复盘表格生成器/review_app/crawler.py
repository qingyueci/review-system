from datetime import date, datetime, timedelta
import json
import re
import time
from typing import Callable
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
import httpx

from .cleaning import content_hash, is_informative, normalize_text
from .config import (
    AUTHOR_BLOG_URL,
    AUTHOR_ID,
    AUTHOR_NAME,
    CRAWL_INTERVAL_SECONDS,
    CRAWL_MAX_COMMENT_PAGES,
    CRAWL_MAX_LIST_PAGES,
    CRAWL_MAX_RETRIES,
    CRAWL_TIMEOUT_SECONDS,
    COMMUNITY_MAX_PER_POST,
    COMMUNITY_MIN_LIKES,
)

ProgressCallback = Callable[[str, int, int], None]
USER_AGENT = "ReviewRAG/1.0 (+local personal research; public pages only)"
LAYOUT_KEYWORDS = (
    "首板", "出身", "任务", "地位", "主动性", "带动性", "独立性", "反推",
    "发酵", "身位", "锚点", "辨识度", "协同", "压制", "节点", "卡位",
)


def _number(text: str) -> int:
    match = re.search(r"([\d,.]+)", text or "")
    return int(match.group(1).replace(",", "").replace(".", "")) if match else 0


def _element_text(element) -> str:
    if element is None:
        return ""
    copy = BeautifulSoup(str(element), "html.parser")
    for br in copy.find_all("br"):
        br.replace_with("\n")
    for tag in copy.find_all(["p", "div"]):
        tag.append("\n")
    return normalize_text(copy.get_text("", strip=False))


def _sample_pages(total_pages: int, maximum: int) -> list[int]:
    if total_pages <= maximum:
        return list(range(1, total_pages + 1))
    fixed = {1, 2, 3, total_pages - 2, total_pages - 1, total_pages}
    remaining = max(0, maximum - len(fixed))
    if remaining:
        for index in range(1, remaining + 1):
            fixed.add(1 + round(index * (total_pages - 1) / (remaining + 1)))
    return sorted(page for page in fixed if 1 <= page <= total_pages)[:maximum]


class TgbCrawler:
    """只抓取无需登录即可访问的淘股吧公开页面。"""

    def __init__(self) -> None:
        headers = {"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"}
        self.client = httpx.Client(
            headers=headers,
            timeout=CRAWL_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
        self._last_request_at = 0.0
        self._robots = RobotFileParser()
        self._robots_ready = False

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def _load_robots(self) -> None:
        if self._robots_ready:
            return
        try:
            response = self.client.get("https://www.tgb.cn/robots.txt")
            response.raise_for_status()
            self._robots.set_url("https://www.tgb.cn/robots.txt")
            self._robots.parse(response.text.splitlines())
        except httpx.HTTPError:
            # robots.txt 临时不可用时仍限制在已确认的公开路径。
            self._robots.parse(["User-agent: *", "Disallow: /Reply/", "Disallow: /topic/"])
        self._robots_ready = True

    def _get(self, url: str) -> str:
        self._load_robots()
        parsed = urlparse(url)
        robots_url = f"https://www.tgb.cn{parsed.path}"
        if parsed.query:
            robots_url += f"?{parsed.query}"
        if not self._robots.can_fetch(USER_AGENT, robots_url):
            raise RuntimeError(f"robots.txt 不允许抓取该地址：{url}")

        wait_seconds = CRAWL_INTERVAL_SECONDS - (time.monotonic() - self._last_request_at)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        last_error: Exception | None = None
        for attempt in range(CRAWL_MAX_RETRIES):
            try:
                response = self.client.get(url)
                self._last_request_at = time.monotonic()
                response.raise_for_status()
                if "sso.tgb.cn" in str(response.url):
                    raise RuntimeError("该页面需要登录，采集器不会绕过登录限制")
                return response.text
            except (httpx.HTTPError, RuntimeError) as exc:
                last_error = exc
                if attempt + 1 < CRAWL_MAX_RETRIES:
                    time.sleep(0.8 * (2 ** attempt))
        raise RuntimeError(f"抓取失败：{url}；{last_error}") from last_error

    @staticmethod
    def _parse_listing(html_text: str) -> list[dict]:
        soup = BeautifulSoup(html_text, "html.parser")
        posts: list[dict] = []
        for item in soup.select(".indexContentItem"):
            link = item.select_one("a.contentTitle[href*='/a/']")
            date_node = item.select_one(".content_time span")
            if not link or not date_node:
                continue
            try:
                published_at = datetime.strptime(date_node.get_text(strip=True), "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            hidden = item.select_one("[contentid]")
            posts.append({
                "topic_id": hidden.get("contentid", "") if hidden else "",
                "title": link.get_text(" ", strip=True) or link.get("title", ""),
                "url": urljoin("https://www.tgb.cn", link["href"]),
                "published_at": published_at.isoformat(timespec="minutes"),
                "views": _number(item.select_one(".viewBtn").get_text(" ", strip=True) if item.select_one(".viewBtn") else ""),
                "reply_count": _number(item.select_one(".plBtn").get_text(" ", strip=True) if item.select_one(".plBtn") else ""),
                "likes": _number(item.select_one(".zanBtn").get_text(" ", strip=True) if item.select_one(".zanBtn") else ""),
                "summary": normalize_text(item.select_one(".content_text").get_text(" ", strip=True) if item.select_one(".content_text") else ""),
            })
        return posts

    def discover_top_posts(
        self,
        *,
        days: int = 365,
        limit: int = 30,
        progress: ProgressCallback | None = None,
    ) -> list[dict]:
        cutoff = datetime.combine(date.today() - timedelta(days=days), datetime.min.time())
        found: list[dict] = []
        for page in range(1, CRAWL_MAX_LIST_PAGES + 1):
            if progress:
                progress(f"正在扫描近一年主帖，第 {page} 页", page, CRAWL_MAX_LIST_PAGES)
            rows = self._parse_listing(self._get(f"{AUTHOR_BLOG_URL}?pageNo={page}"))
            if not rows:
                break
            in_range = [row for row in rows if datetime.fromisoformat(row["published_at"]) >= cutoff]
            found.extend(in_range)
            if len(in_range) < len(rows):
                break
        unique = {row["url"]: row for row in found}
        return sorted(unique.values(), key=lambda row: (row["views"], row["reply_count"]), reverse=True)[:limit]

    def discover_recent_posts(self, *, limit: int = 10) -> list[dict]:
        """仅供首次建立近期窗口；日常同步改用昨日新增发现。"""
        found: list[dict] = []
        page = 1
        while len(found) < limit and page <= CRAWL_MAX_LIST_PAGES:
            rows = self._parse_listing(self._get(f"{AUTHOR_BLOG_URL}?pageNo={page}"))
            if not rows:
                break
            found.extend(rows)
            page += 1
        return found[:limit]

    def discover_posts_for_date(self, *, target_date: date) -> list[dict]:
        """按发布日期发现帖子；列表进入更早日期后立即停止。"""
        found: list[dict] = []
        for page in range(1, CRAWL_MAX_LIST_PAGES + 1):
            rows = self._parse_listing(self._get(f"{AUTHOR_BLOG_URL}?pageNo={page}"))
            if not rows:
                break
            row_dates = [datetime.fromisoformat(row["published_at"]).date() for row in rows]
            found.extend(
                row for row, published_on in zip(rows, row_dates, strict=True)
                if published_on == target_date
            )
            if min(row_dates) < target_date:
                break
        unique = {row["url"]: row for row in found}
        return sorted(unique.values(), key=lambda row: row["published_at"], reverse=True)

    @staticmethod
    def _parse_comment(item, post: dict, page: int) -> dict | None:
        user_node = item.select_one(".user-name[data-user-id]")
        text_node = item.select_one(".comment-data-text[id^='reply']")
        if not user_node or not text_node:
            return None
        reply_id = text_node.get("id", "").replace("reply", "")
        floor_text = item.select_one(".comment-data-button > span")
        floor_match = re.search(r"第\s*(\d+)\s*楼", floor_text.get_text(" ", strip=True) if floor_text else "")
        quote = item.select_one(".comment-data-quote")
        quote_user = quote.select_one("[data-user-id]") if quote else None
        quote_text = quote.select_one(".data-quote-text") if quote else None
        likes_node = item.select_one("[data-useful-num]")
        time_node = item.select_one(".pcyclspan")
        answer = _element_text(text_node)
        question = _element_text(quote_text)
        return {
            "reply_id": reply_id or content_hash(post["url"], str(page), answer)[:20],
            "post_url": post["url"],
            "post_title": post["title"],
            "post_date": post["published_at"][:10],
            "page": page,
            "floor": int(floor_match.group(1)) if floor_match else 0,
            "author_id": user_node.get("data-user-id", ""),
            "author_name": user_node.get_text(" ", strip=True),
            "published_at": time_node.get_text(" ", strip=True) if time_node else "",
            "answer": answer,
            "question": question,
            "question_author": quote_user.get_text(" ", strip=True) if quote_user else "",
            "question_author_id": quote_user.get("data-user-id", "") if quote_user else "",
            "likes": int(likes_node.get("data-useful-num", 0)) if likes_node else 0,
            "source_url": f"{post['url']}-{page}#reply{reply_id}" if reply_id else f"{post['url']}-{page}",
        }

    @staticmethod
    def _parse_useful_comment(item: dict, post: dict) -> dict | None:
        """解析点赞榜接口返回的评论。"""
        reply_id = str(item.get("replyID") or item.get("newReplyID") or "")
        answer = _element_text(BeautifulSoup(str(item.get("body") or ""), "html.parser"))
        if not reply_id or not answer:
            return None
        page = int(item.get("pageNo") or 0)
        quote = _element_text(
            BeautifulSoup(str(item.get("quoteContent") or ""), "html.parser")
        )
        source_url = post["url"]
        if page:
            source_url += f"-{page}"
        source_url += f"#reply{reply_id}"
        return {
            "reply_id": reply_id,
            "post_url": post["url"],
            "post_title": post["title"],
            "post_date": post["published_at"][:10],
            "page": page,
            "floor": int(item.get("floor") or 0),
            "author_id": str(item.get("userID") or ""),
            "author_name": normalize_text(str(item.get("userName") or "")),
            "published_at": normalize_text(str(
                item.get("datetime") or item.get("postDate") or item.get("timeMiaosu") or ""
            )),
            "answer": answer,
            "question": quote,
            "question_author": normalize_text(str(item.get("quoteUserName") or "")),
            "question_author_id": str(item.get("quoteUserID") or ""),
            "likes": int(item.get("usefulNum") or 0),
            "source_url": source_url,
            "from_useful_list": True,
        }

    def fetch_useful_comments(self, post: dict) -> list[dict]:
        """读取公开点赞榜，补充高赞评论和作者回复。"""
        topic_id = str(post.get("topic_id") or "")
        if not topic_id:
            return []
        url = (
            "https://www.tgb.cn/topic/getUsefulList"
            f"?topicID={topic_id}&topicUserID={AUTHOR_ID}"
        )
        try:
            payload = json.loads(self._get(url))
        except (json.JSONDecodeError, RuntimeError):
            return []
        if not payload.get("status"):
            return []
        comments = [
            self._parse_useful_comment(item, post)
            for item in (payload.get("dto") or [])
            if isinstance(item, dict)
        ]
        return [item for item in comments if item]

    @staticmethod
    def _select_community_comments(comments: list[dict]) -> list[dict]:
        """按点赞、布局相关度和信息量筛选社区观点。"""
        candidates: list[dict] = []
        for comment in comments:
            text = normalize_text(comment.get("answer", ""))
            if not is_informative(text, minimum=20):
                continue
            likes = int(comment.get("likes", 0))
            keyword_hits = sum(keyword in text for keyword in LAYOUT_KEYWORDS)
            # 高赞直接保留；低赞但高度贴合布局框架的评论也允许进入候选。
            if not (
                likes >= COMMUNITY_MIN_LIKES
                or (likes >= 2 and keyword_hits >= 2)
                or (likes >= 1 and keyword_hits >= 4)
            ):
                continue
            item = dict(comment)
            item["selection_score"] = round(
                likes * 5 + min(len(text), 240) / 20 + keyword_hits * 3,
                2,
            )
            candidates.append(item)
        candidates.sort(
            key=lambda item: (
                item["selection_score"],
                item.get("likes", 0),
                len(item.get("answer", "")),
            ),
            reverse=True,
        )
        unique = {item["reply_id"]: item for item in candidates}
        return list(unique.values())[:COMMUNITY_MAX_PER_POST]

    def fetch_post(self, post: dict, *, max_comment_pages: int = CRAWL_MAX_COMMENT_PAGES) -> dict:
        first_url = f"{post['url']}-1"
        first_html = self._get(first_url)
        first_soup = BeautifulSoup(first_html, "html.parser")
        body_node = first_soup.select_one(".p_coten")
        body = _element_text(body_node)
        if not body:
            raise RuntimeError(f"未找到帖子正文，网页结构可能已变化：{post['url']}")

        page_input = first_soup.select_one(".tp_input02[data-page-num]")
        comments_visible = bool(
            first_soup.select_one(".comment-content")
            or first_soup.select_one(".comment-data")
        )
        total_pages = int(page_input.get("data-page-num", 1)) if page_input else (1 if comments_visible else 0)
        pages = _sample_pages(total_pages, max_comment_pages) if total_pages else []
        author_replies: list[dict] = []
        community_candidates: list[dict] = []
        useful_comments = self.fetch_useful_comments(post)
        for reply in useful_comments:
            if reply["author_id"] == AUTHOR_ID:
                if is_informative(reply["answer"], minimum=4):
                    author_replies.append(reply)
            else:
                community_candidates.append(reply)
        for page in pages:
            soup = first_soup if page == 1 else BeautifulSoup(
                self._get(f"{post['url']}-{page}"), "html.parser"
            )
            for item in soup.select(".comment-data"):
                reply = self._parse_comment(item, post, page)
                if not reply or not is_informative(reply["answer"], minimum=4):
                    continue
                if reply["question"] and not is_informative(reply["question"], minimum=6):
                    reply["question"] = ""
                    reply["question_author"] = ""
                if reply["author_id"] == AUTHOR_ID:
                    author_replies.append(reply)
                else:
                    community_candidates.append(reply)

        result = dict(post)
        parent_text = body_node.parent.get_text(" ", strip=True) if body_node and body_node.parent else ""
        result.update({
            "body": body,
            "body_hash": content_hash(body),
            "body_truncated": "登录可查看全文" in parent_text,
            "comments_accessible": bool(total_pages or useful_comments),
            "useful_comment_count": len(useful_comments),
            "total_comment_pages": total_pages,
            "scanned_comment_pages": pages,
            "author_replies": list({item["reply_id"]: item for item in author_replies}.values()),
            "community_comments": self._select_community_comments(community_candidates),
        })
        return result

    def fetch_latest_review(self, target_date: date | None = None) -> dict:
        target = target_date or date.today()
        for page in range(1, CRAWL_MAX_LIST_PAGES + 1):
            rows = self._parse_listing(self._get(f"{AUTHOR_BLOG_URL}?pageNo={page}"))
            if not rows:
                break
            for post in rows:
                published = datetime.fromisoformat(post["published_at"]).date()
                if published == target or target_date is None:
                    html_text = self._get(f"{post['url']}-1")
                    body = _element_text(BeautifulSoup(html_text, "html.parser").select_one(".p_coten"))
                    if not body:
                        raise RuntimeError("找到了帖子，但没有解析到复盘正文")
                    return {**post, "body": body, "body_hash": content_hash(body)}
                if published < target:
                    raise RuntimeError(f"{target.isoformat()} 没有找到公开复盘帖")
        raise RuntimeError("没有找到可抓取的公开复盘帖")


def author_label() -> str:
    return f"{AUTHOR_NAME}（公开内容）"
