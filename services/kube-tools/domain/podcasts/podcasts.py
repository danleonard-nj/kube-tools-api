from ast import mod
import re
from typing import Callable, Dict, List, OrderedDict

from framework.logger import get_logger
from framework.serialization import Serializable
from framework.validators.nulls import none_or_whitespace

TITLE_FILENAME_REGEX = '[^A-Za-z0-9 ]+'

logger = get_logger(__name__)


class PodcastDownloadException(Exception):
    def __init__(
        self,
        message: str
    ):
        super().__init__(message)


class PodcastSyncException(Exception):
    pass


class Episode(Serializable):
    def __init__(
        self,
        episode_id: str,
        episode_title: str,
        audio: str
    ):
        self.episode_id = episode_id
        self.episode_title = episode_title
        self.audio = audio

    @classmethod
    def from_feed(
        cls,
        data,
        id_selector: Callable,
        title_selector: Callable,
        audio_selector: Callable
    ) -> 'Episode':
        '''
        Parse episode from RSS feed data
        '''

        episode_id = id_selector(data)
        episode_title = title_selector(data)

        # Verify that the episode data was parsed correctly
        if none_or_whitespace(episode_id) or none_or_whitespace(episode_title):
            raise PodcastSyncException(f'Failed to parse episode data: {data}')

        audio = audio_selector(data)

        if none_or_whitespace(audio):
            raise PodcastSyncException(f'Failed to parse audio data URL: {data}')

        return Episode(
            episode_id=episode_id,
            episode_title=episode_title,
            audio=audio)

    def get_filename(
        self,
        show_title
    ) -> str:
        show = re.sub(TITLE_FILENAME_REGEX, '', show_title)
        name = re.sub(TITLE_FILENAME_REGEX, '', self.episode_title)

        return (
            show.replace(' ', '_')
            + '_'
            + name.replace(' ', '_')
            + '.mp3'
        )


class Feed:
    def __init__(
        self,
        data
    ):
        self.name = data.get('name')
        self.feed = data.get('feed')
        self.type = data.get('type')


class Show(Serializable):
    @ property
    def episode_ids(
        self
    ) -> List[str]:

        return [
            episode.episode_id
            for episode in self.episodes
        ]

    def __init__(
        self,
        show_id,
        show_title,
        episodes,
        modified_date: int = None,
        **kwargs
    ):
        self.show_id = show_id
        self.show_title = show_title
        self.episodes = episodes
        self.modified_date = modified_date

    @ classmethod
    def from_entity(
        cls,
        entity: Dict
    ):
        return Show(
            show_id=entity.get('show_id'),
            show_title=entity.get('show_title'),
            modified_date=entity.get('modified_date'),
            episodes=cls.get_entity_episodes(
                episodes=entity.get('episodes')))

    @ classmethod
    def get_entity_episodes(
        cls,
        episodes
    ):
        if isinstance(episodes, OrderedDict):
            episodes = [episodes]

        return [Episode(
            episode_id=episode.get('episode_id'),
            episode_title=episode.get('episode_title'),
            audio=episode.get('audio'))
            for episode in episodes]

    def get_selector(
        self
    ) -> Dict:

        return {
            'show_id': self.show_id
        }

    def to_dict(
        self
    ) -> Dict:
        return super().to_dict() | {
            'episodes': [
                episode.to_dict() for
                episode in self.episodes]
        }

    def contains_episode(
        self,
        episode_id: str
    ):
        return episode_id in self.episode_ids


class DownloadedEpisode(Serializable):
    @property
    def size_mb(
        self
    ):
        mb = self.size / 1048576 if self.size != 0 else 0
        return round(mb, 2)

    def __init__(
        self,
        episode: Episode,
        show: Show,
        size: int = 0
    ):
        self.episode = episode
        self.show = show
        self.size = size

    def get_text(
        self
    ) -> str:
        return f'{self.show.show_title}: {self.episode.episode_title}: {self.size_mb}mb'

    def get_filename(
        self
    ) -> str:
        return self.episode.get_filename(
            show_title=self.show.show_title)

    def to_dict(self) -> Dict:
        return {
            'episode': self.episode.to_dict(),
            'show': self.show.to_dict(),
            'size': self.size_mb
        }

    def to_result(
        self
    ):
        return {
            'Show': self.show.show_title,
            'Episode': self.episode.episode_title,
            'Size': f'{self.size_mb} mb'
        }
