import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

API_BASE_URL = os.getenv("KIMI_BASE_URL", "https://api.kimi.com/coding/v1")
MODEL_NAME = os.getenv("KIMI_MODEL", "kimi-for-coding")
API_TIMEOUT_SECONDS = float(os.getenv("KIMI_TIMEOUT", "300"))
API_MAX_RETRIES = int(os.getenv("KIMI_MAX_RETRIES", "0"))
MAX_INPUT_CHARS = 100_000

AUTHOR_ID = os.getenv("TGB_AUTHOR_ID", "5894557")
AUTHOR_NAME = os.getenv("TGB_AUTHOR_NAME", "延边刺客")
AUTHOR_BLOG_URL = os.getenv("TGB_BLOG_URL", f"https://m.tgb.cn/blog/{AUTHOR_ID}")
CRAWL_TIMEOUT_SECONDS = float(os.getenv("TGB_TIMEOUT", "20"))
CRAWL_INTERVAL_SECONDS = float(os.getenv("TGB_INTERVAL", "0.35"))
CRAWL_MAX_RETRIES = int(os.getenv("TGB_MAX_RETRIES", "3"))
CRAWL_MAX_LIST_PAGES = int(os.getenv("TGB_MAX_LIST_PAGES", "60"))
CRAWL_MAX_COMMENT_PAGES = int(os.getenv("TGB_MAX_COMMENT_PAGES", "12"))
CRAWL_TOP_POST_LIMIT = int(os.getenv("TGB_TOP_POST_LIMIT", "20"))
COMMUNITY_MIN_LIKES = int(os.getenv("TGB_COMMUNITY_MIN_LIKES", "5"))
COMMUNITY_MAX_PER_POST = int(os.getenv("TGB_COMMUNITY_MAX_PER_POST", "20"))

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("REVIEW_DATA_DIR", PROJECT_DIR / "data"))
KNOWLEDGE_DB_PATH = Path(os.getenv("REVIEW_KNOWLEDGE_DB", DATA_DIR / "review_knowledge.db"))
JOB_DB_PATH = Path(os.getenv("REVIEW_JOB_DB", DATA_DIR / "review_jobs.db"))
_manual_system_docx = os.getenv("REVIEW_MANUAL_SYSTEM_DOCX", "").strip()
MANUAL_SYSTEM_DOCX = (
    Path(_manual_system_docx)
    if _manual_system_docx
    else PROJECT_DIR.parent / "延边刺客短线打板体系.docx"
)

SHEET_NAMES = ["首板复盘", "连板梯队", "高标情绪", "观察计划", "竞价分析", "气质股", "思考题"]

SECTOR_COLORS = {
    "算力": "D6E4F0", "芯片": "D6E4F0", "科技": "D6E4F0",
    "医药": "D4EDDA", "医疗": "D4EDDA",
    "有色": "FFF3CD", "金属": "FFF3CD", "稀土": "FFF3CD",
}
