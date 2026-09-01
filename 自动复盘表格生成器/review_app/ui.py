from datetime import date
import json
import os

import pandas as pd
import streamlit as st

from .analysis import analyze_with_rag, review_data_to_text, workbook_to_text
from .crawler import TgbCrawler
from .docx_export import generate_analysis_docx
from .excel import generate_excel
from .knowledge import KnowledgeStore, sync_knowledge_incremental
from .llm import parse_with_deepseek
from .preprocessing import preprocess_text
from .validation import validate_data


def _preview(data: dict) -> dict[str, list[dict]]:
    day = data["meta"]["date"]
    return {
        "首板复盘": [{"日期": day, "板块": x.get("sector", ""), "个股": "、".join(x.get("stocks", [])), "分析": "；".join(x.get("analysis_points", []))} for x in data["first_boards"] if isinstance(x, dict)],
        "连板梯队": [{"日期": day, "板数": x.get("level", ""), "梯队思路": x.get("ladder_thought", "")} for x in data["ladders"] if isinstance(x, dict)],
        "高标情绪": [{"日期": day, "情绪标签": data["sentiment"]["mood_tag"], "强度": data["sentiment"]["mood_score"]}],
        "观察计划": [{"日期": day, "观察要点": x} for x in data["observation_plan"]],
        "竞价分析": [{"日期": day, "竞价逻辑": x} for x in data["bidding_analysis"]],
        "气质股": [{"日期": day, **x} for x in data["temperament_stocks"] if isinstance(x, dict)],
        "思考题": [{"日期": day, "问题": x} for x in data["thinking_questions"]],
    }


def _render_review_page() -> None:
    left, right = st.columns([2, 3])
    with left:
        mode = st.radio("原文来源", ["自动抓取公开复盘", "手动粘贴"], horizontal=True)
        selected_date = st.date_input("复盘日期", value=date.today(), max_value=date.today())
        if mode == "自动抓取公开复盘":
            fetch = st.button("🌐 获取该日公开复盘", width="stretch")
            if fetch:
                try:
                    with st.spinner("正在获取公开复盘正文..."):
                        with TgbCrawler() as crawler:
                            post = crawler.fetch_latest_review(selected_date)
                        st.session_state["raw_review_text"] = post["body"]
                        st.session_state["review_source_url"] = post["url"]
                    st.success(f"已获取：{post['title']}（{post['published_at'][:10]}）")
                except RuntimeError as exc:
                    st.error(str(exc))
        raw_text = st.text_area(
            "复盘原文",
            height=400,
            key="raw_review_text",
            placeholder="可自动抓取，也可在此手动修改",
        )
        source_url = st.session_state.get("review_source_url")
        if source_url:
            st.markdown(f"[查看原帖]({source_url})")
        api_key = st.text_input(
            "DeepSeek API Key",
            type="password",
            placeholder="已配置环境变量时可留空",
            key="review_api_key",
        )
        run = st.button("🔎 解析并生成 Excel", type="primary", width="stretch")
        if run:
            try:
                with st.spinner("正在解析并生成 Excel..."):
                    cleaned = preprocess_text(raw_text)
                    data = validate_data(parse_with_deepseek(api_key or os.getenv("DEEPSEEK_API_KEY", ""), cleaned))
                    content, filename = generate_excel(data)
                    st.session_state.update(
                        review_data=data,
                        excel_content=content,
                        excel_filename=filename,
                        analyzed_review_text=review_data_to_text(data),
                    )
                st.success("解析完成")
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))
            except Exception as exc:
                st.exception(exc)

    with right:
        if data := st.session_state.get("review_data"):
            previews = _preview(data)
            for tab, (name, rows) in zip(st.tabs(list(previews)), previews.items()):
                with tab:
                    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            st.download_button(
                "📥 下载复盘表格",
                st.session_state["excel_content"],
                st.session_state["excel_filename"],
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
            )
        else:
            st.info("抓取或粘贴复盘原文，解析结果将在这里预览。")


def _render_knowledge_page() -> None:
    st.subheader("增量知识库")
    st.caption("核心 20 篇固定保留；日常只检查昨日新增帖子，新进一篇时归档近期窗口中最旧的一篇。")
    with KnowledgeStore() as store:
        stats = store.stats()
    columns = st.columns(8)
    columns[0].metric("高阅读量核心帖", stats["core_posts"])
    columns[1].metric("近期问答补充帖", stats["supplemental_posts"])
    columns[2].metric("历史归档帖", stats["archived_posts"])
    columns[3].metric("刺大公开回复", stats["qa_pairs"])
    columns[4].metric("社区精选观点", stats["community_comments"])
    columns[5].metric("检索片段", stats["chunks"])
    columns[6].metric("人工体系文件", stats["manual_sources"])
    columns[7].metric("最近更新", stats["last_sync"].replace("T", " "))

    if st.button("🔄 检查昨日新增帖子", type="primary"):
        bar = st.progress(0)
        status = st.empty()

        def update_progress(message: str, current: int, total: int) -> None:
            status.write(message)
            bar.progress(min(1.0, current / max(total, 1)))

        try:
            result = sync_knowledge_incremental(update_progress)
            bar.progress(1.0)
            status.empty()
            if result["failed"]:
                st.warning(
                    f"完成：新抓取 {result['fetched']} 篇，复用 {result['reused']} 篇，"
                    f"失败 {result['failed']} 篇。"
                )
                with st.expander("查看失败详情"):
                    st.code("\n".join(result["errors"]))
            else:
                st.success(f"更新完成：新抓取 {result['fetched']} 篇，复用 {result['reused']} 篇。")
            manual = result.get("manual_source", {})
            if manual.get("error"):
                st.warning(manual["error"])
            elif manual.get("imported"):
                st.info(f"已更新人工体系文件，共 {manual['chunks']} 个检索片段。")
        except RuntimeError as exc:
            st.error(str(exc))

    with KnowledgeStore() as store:
        posts = store.list_posts()
    if posts:
        frame = pd.DataFrame(posts)
        frame["published_at"] = frame["published_at"].str[:10]
        frame["scanned_comment_pages"] = frame["scanned_comment_pages"].map(
            lambda value: "、".join(str(item) for item in json.loads(value))
        )
        frame["scope"] = frame["scope"].map({
            "top_year": "近一年浏览量前20",
            "recent_qa": "近期公开问答补充",
            "recent_archive": "历史问答归档",
        })
        for column in ("body_truncated", "comments_accessible"):
            frame[column] = frame[column].map({1: "是", 0: "否"})
        frame["capture_mode"] = frame["capture_mode"].map({
            "authenticated_browser": "登录浏览器完整抓取",
            "public_http": "公开程序抓取",
        })
        frame = frame.rename(columns={
            "title": "标题", "published_at": "日期", "views": "浏览",
            "reply_count": "评论", "likes": "点赞", "total_comment_pages": "评论总页数",
            "scope": "用途", "body_truncated": "正文为公开节选",
            "comments_accessible": "公开评论可抓",
            "useful_comment_count": "点赞榜评论",
            "capture_mode": "采集方式",
            "scanned_comment_pages": "已采样页", "url": "原帖",
        })
        st.dataframe(
            frame,
            width="stretch",
            hide_index=True,
            column_config={"原帖": st.column_config.LinkColumn("原帖")},
        )
    else:
        st.info("知识库尚未建立，点击上方按钮开始自动采集。")


def _render_analysis_page() -> None:
    st.subheader("刺大公开框架辅助分析")
    st.caption("分析优先级：首板出身 → 原始任务 → 布局关系 → 地位变化 → 任务完成/失败。技术指标只能作为验证。")

    source_mode = st.radio("每日复盘来源", ["当前已生成复盘", "上传复盘 Excel"], horizontal=True)
    review_text = ""
    review_date = date.today().isoformat()
    if source_mode == "当前已生成复盘":
        review_text = st.session_state.get("analyzed_review_text", "")
        data = st.session_state.get("review_data")
        if data:
            review_date = data["meta"]["date"]
            st.success(f"已载入 {review_date} 的结构化复盘")
        else:
            st.info("请先在“今日复盘”中生成复盘表格。")
    else:
        uploaded = st.file_uploader("上传 .xlsx 复盘文件", type=["xlsx"])
        if uploaded:
            try:
                review_text = workbook_to_text(uploaded.getvalue())
                st.success("已读取上传的复盘文件")
            except (ValueError, OSError) as exc:
                st.error(str(exc))

    api_key = st.text_input(
        "DeepSeek API Key",
        type="password",
        placeholder="已配置环境变量时可留空",
        key="analysis_api_key",
    )
    if st.button("🧭 按个股任务与布局分析", type="primary", width="stretch"):
        try:
            if not review_text:
                raise ValueError("请先生成或上传每日复盘")
            with KnowledgeStore() as store:
                sources = store.search(review_text, limit=12)
            with st.spinner("正在检索历史资料并分析个股任务..."):
                analysis = analyze_with_rag(
                    api_key or os.getenv("DEEPSEEK_API_KEY", ""),
                    review_text,
                    sources,
                )
                document, filename = generate_analysis_docx(
                    analysis,
                    sources,
                    review_date=review_date,
                )
            st.session_state.update(
                rag_analysis=analysis,
                rag_sources=sources,
                analysis_docx=document,
                analysis_docx_filename=filename,
            )
            st.success("分析完成")
        except (ValueError, RuntimeError) as exc:
            st.error(str(exc))
        except Exception as exc:
            st.exception(exc)

    if analysis := st.session_state.get("rag_analysis"):
        st.markdown(analysis)
        st.download_button(
            "📄 下载 Word 分析文档",
            st.session_state["analysis_docx"],
            st.session_state["analysis_docx_filename"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            width="stretch",
        )
        with st.expander("本次引用的公开历史资料"):
            for index, source in enumerate(st.session_state.get("rag_sources", []), 1):
                kind = {
                    "qa": "刺大公开回复",
                    "community": "社区精选评论（仅作辅助）",
                    "manual": "人工整理体系",
                    "post": "复盘主帖",
                }.get(source["source_type"], "公开资料")
                st.markdown(
                    f"{index}. [{source['title']}]({source['source_url']}) "
                    f"— {source['published_at'][:10]}，{kind}"
                )


def main() -> None:
    st.set_page_config(page_title="复盘布局分析器", page_icon="📊", layout="wide")
    st.title("复盘布局分析器")
    review_tab, knowledge_tab, analysis_tab = st.tabs(["今日复盘", "知识库", "刺大框架分析"])
    with review_tab:
        _render_review_page()
    with knowledge_tab:
        _render_knowledge_page()
    with analysis_tab:
        _render_analysis_page()
