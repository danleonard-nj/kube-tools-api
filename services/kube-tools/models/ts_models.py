from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class TruthSocialConfig(BaseModel):
    rss_feed: str
    recipients: list[str]


class FeedLink(BaseModel):
    href: str
    rel: Optional[str] = None
    type: Optional[str] = None


class FeedTitleDetail(BaseModel):
    type: str
    language: Optional[str]
    base: str
    value: str


class FeedSummaryDetail(BaseModel):
    type: str
    language: Optional[str]
    base: str
    value: str


class FeedEntry(BaseModel):
    title: str
    title_detail: FeedTitleDetail
    links: list[FeedLink]
    link: str
    summary: str
    summary_detail: FeedSummaryDetail
    authors: list[dict[str, Any]]
    author: str
    id: str
    guidislink: bool
    published: str
    published_parsed: Any  # You can use a custom type or leave as Any for struct_time


# ── Result / record models used by TruthSocialPushService ──


class SummaryResult(BaseModel):
    """Structured result from a GPT summarization call."""
    summary: str = "No summary available."
    model: Optional[str] = None
    tokens_used: int = 0
    generation_time_seconds: float = 0.0


class RepostMetadata(BaseModel):
    """Accumulated metadata from repost resolution."""
    original_link_mapping: dict[str, str] = Field(default_factory=dict)
    repost_ids: set[str] = Field(default_factory=set)


class PostRecord(BaseModel):
    """Typed database record for a Truth Social post."""
    post_id: str
    title: str
    link: str
    original_link: str
    content: str
    published_timestamp: int
    ai_summary: Optional[str] = None
    ai_model: Optional[str] = None
    ai_tokens_used: int = 0
    ai_generation_time_seconds: float = 0.0
    is_repost: bool = False
    created_at: datetime
    updated_at: datetime


class BackfillStats(BaseModel):
    """Statistics returned by the backfill operation."""
    total_entries: int = 0
    new_posts: int = 0
    skipped_posts: int = 0
    errors: int = 0
