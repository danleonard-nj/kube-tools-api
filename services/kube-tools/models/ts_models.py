

from typing import Any, Optional
from pydantic import BaseModel


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
