from typing import List, Optional
from pydantic import BaseModel


class PodcastFeedConfig(BaseModel):
    name: str
    feed: str
    type: str
    folder_name: Optional[str] = None


class PodcastConfig(BaseModel):
    random_delay: bool
    feeds: List[PodcastFeedConfig]
