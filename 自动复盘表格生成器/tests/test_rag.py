from io import BytesIO

from docx import Document

from review_app.analysis import ANALYSIS_SYSTEM_PROMPT
from review_app.cleaning import is_greeting_or_noise, normalize_text
from review_app.crawler import TgbCrawler, _sample_pages
from review_app.docx_export import generate_analysis_docx
from review_app.knowledge import KnowledgeStore


def test_cleaning_filters_greetings_but_keeps_layout_questions():
    assert is_greeting_or_noise("先赞后看，刺大发财！")
    assert not is_greeting_or_noise("恒尚首板出身决定了它今天应该完成什么任务？")
    assert normalize_text("正文\u200b\n\n\n下载淘股吧APP") == "正文"


def test_sample_comment_pages_covers_beginning_middle_and_end():
    pages = _sample_pages(39, 12)
    assert len(pages) == 12
    assert pages[:3] == [1, 2, 3]
    assert pages[-3:] == [37, 38, 39]
    assert any(10 < page < 30 for page in pages)


def test_mobile_listing_parser_reads_metrics():
    html = """
    <div class="indexContentItem">
      <span contentid="123" subject="摘要"></span>
      <span class="content_time"><span>2026-07-18 16:20</span></span>
      <a class="contentTitle" href="/a/demo">718</a>
      <a class="content_text">[摘要] 今日复盘</a>
      <div class="viewBtn"><span>浏览(123,456)</span></div>
      <div class="plBtn"><span>评论(789)</span></div>
      <div class="zanBtn"><span>赞(66)</span></div>
    </div>
    """
    posts = TgbCrawler._parse_listing(html)
    assert posts[0]["topic_id"] == "123"
    assert posts[0]["views"] == 123456
    assert posts[0]["reply_count"] == 789
    assert posts[0]["url"] == "https://www.tgb.cn/a/demo"


def test_community_comments_use_likes_and_layout_relevance():
    comments = [
        {"reply_id": "1", "answer": "这只票首板出身决定任务，今天主动性也完成了板块反推。", "likes": 2},
        {"reply_id": "2", "answer": "写得不错，感谢分享，继续学习，祝老师天天发财。", "likes": 12},
        {"reply_id": "3", "answer": "首板出身、任务、地位、主动性和板块协同都应该放在一起理解。", "likes": 1},
        {"reply_id": "4", "answer": "普通长评论但没有足够点赞，也没有布局相关信息。", "likes": 0},
    ]
    selected = TgbCrawler._select_community_comments(comments)
    assert [item["reply_id"] for item in selected] == ["1", "3"]


def test_useful_comment_parser_keeps_author_and_quote_context():
    post = {
        "url": "https://www.tgb.cn/a/test",
        "title": "测试",
        "published_at": "2026-07-18T16:00",
    }
    item = TgbCrawler._parse_useful_comment({
        "replyID": 123,
        "userID": 5894557,
        "userName": "延边刺客",
        "body": "首板出身决定了它的任务。<br/>不是只看报价。",
        "quoteContent": "它今天承担什么任务？",
        "quoteUserID": 8,
        "quoteUserName": "提问者",
        "usefulNum": 66,
        "pageNo": 5,
    }, post)
    assert item["reply_id"] == "123"
    assert item["author_id"] == "5894557"
    assert "首板出身" in item["answer"]
    assert item["question_author"] == "提问者"
    assert item["likes"] == 66
    assert item["source_url"].endswith("-5#reply123")


def test_knowledge_store_keeps_question_and_answer_together(tmp_path):
    post = {
        "url": "https://www.tgb.cn/a/test",
        "topic_id": "1",
        "title": "测试复盘",
        "published_at": "2026-07-18T16:20",
        "views": 100,
        "reply_count": 10,
        "likes": 5,
        "summary": "摘要",
        "body": "机器人首板出身，任务是为科技方向做发酵确认。",
        "body_hash": "hash",
        "total_comment_pages": 1,
        "scanned_comment_pages": [1],
        "author_replies": [{
            "reply_id": "99",
            "question": "这只股票今天在布局里承担什么任务？",
            "answer": "先看首板出身，它的任务是反推机器人方向，而不是只看报价。",
            "question_author": "测试用户",
            "published_at": "2026-07-18 18:00",
            "floor": 20,
            "likes": 8,
            "source_url": "https://www.tgb.cn/a/test-1#reply99",
        }],
        "community_comments": [{
            "reply_id": "100",
            "author_name": "社区用户",
            "question": "",
            "answer": "这个首板出身对应的是板块发酵任务，需要观察主动性。",
            "published_at": "2026-07-18 18:10",
            "floor": 21,
            "likes": 10,
            "source_url": "https://www.tgb.cn/a/test-1#reply100",
        }],
    }
    with KnowledgeStore(tmp_path / "knowledge.db") as store:
        store.upsert_post(post)
        results = store.search("首板出身 个股任务 机器人", limit=5)
        assert results
        combined = "\n".join(item["content"] for item in results)
        assert "用户问题" in combined
        assert "刺大回复" in combined
        assert store.stats()["community_comments"] == 1


def test_manual_system_docx_is_imported_as_rag_source(tmp_path):
    source_path = tmp_path / "延边刺客短线打板体系.docx"
    document = Document()
    document.add_heading("首板出身与任务", level=1)
    document.add_paragraph("首板出身决定初始地位，个股需要完成板块发酵和反推任务。")
    document.save(source_path)
    with KnowledgeStore(tmp_path / "knowledge.db") as store:
        result = store.import_manual_docx(source_path)
        sources = store.search("首板出身 初始地位 反推任务", limit=5)
        assert result["imported"]
        assert result["chunks"] == 1
        assert sources[0]["source_type"] == "manual"
        assert store.stats()["manual_sources"] == 1


def test_analysis_prompt_prioritizes_tasks_over_technical_indicators():
    assert "首板出身 -> 原始任务" in ANALYSIS_SYSTEM_PROMPT
    assert "禁止把普通技术分析写成主线" in ANALYSIS_SYSTEM_PROMPT
    assert "个股不是孤立报价" in ANALYSIS_SYSTEM_PROMPT
    assert "社区精选评论" in ANALYSIS_SYSTEM_PROMPT
    assert "人工整理体系" in ANALYSIS_SYSTEM_PROMPT


def test_analysis_docx_contains_sources_and_disclaimer():
    content, filename = generate_analysis_docx(
        "# 今日核心判断\n个股任务优先。\n## 个股任务表\n- 测试股：完成发酵任务",
        [{
            "title": "历史复盘",
            "published_at": "2026-07-01T16:20",
            "source_type": "qa",
            "source_url": "https://www.tgb.cn/a/test",
        }],
        review_date="2026-07-18",
    )
    document = Document(BytesIO(content))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "不代表原作者本人观点" in text
    assert "个股任务优先" in text
    assert filename == "刺大框架复盘分析_2026-07-18.docx"
