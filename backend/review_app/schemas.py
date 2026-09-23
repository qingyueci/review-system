from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


MAX_TEXT_CHARS = 120_000


class AnalyzeRequest(BaseModel):
    filename: str = Field(default="每日复盘.txt", max_length=240)
    text: str = Field(default="", max_length=MAX_TEXT_CHARS)
    content_base64: str = ""
    source_title: str = Field(default="", max_length=300)
    source_url: str = Field(default="", max_length=2000)
    review_date: str = ""
    model: str = Field(default="", max_length=100)
    thinking_enabled: bool = True
    generate_excel: bool = True
    generate_word: bool = True
    input_is_excel: bool = False


class RetryGenerationRequest(BaseModel):
    branch: Literal["excel", "word"]
    model: str = Field(default="", max_length=100)
    thinking_enabled: bool = True


class FetchReviewRequest(BaseModel):
    review_date: str
