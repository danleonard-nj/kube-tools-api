import re
from typing import Dict, List, OrderedDict

import xmltodict
from framework.logger import get_logger
from framework.serialization import Serializable

from domain.exceptions import InvalidSchemaException

logger = get_logger(__name__)


class Episode(Serializable):
    Acast = 'acast:episodeId'

    def __init__(
        self,
        episode_id,
        episode_title,
        audio
    ):
        self.episode_id = episode_id
        self.episode_title = episode_title
        self.audio = audio

    @classmethod
    def from_feed(
        cls,
        data
    ) -> 'Episode':
        '''
        Parse episode from RSS feed data
        '''

        if cls.Acast in data:
            # Parse acast tags
            return Episode(
                episode_id=data.get('acast:episodeId'),
                episode_title=data.get('itunes:title'),
                audio=data.get('enclosure').get('@url'))

        else:
            # Log if the schema changes and notify
            logger.info(f'RSS schema is not known: {data}')
            raise InvalidSchemaException(data)

    def get_filename(
        self,
        show_title
    ) -> str:
        show = re.sub('[^A-Za-z0-9 ]+', '', show_title)
        name = re.sub('[^A-Za-z0-9 ]+', '', self.episode_title)
        return show.replace(' ', '_') + '_' + name.replace(' ', '_') + '.mp3'


class Feed:
    def __init__(
        self,
        data
    ):
        self.name = data.get('name')
        self.feed = data.get('feed')


class Show(Serializable):
    @property
    def episode_ids(
        self
    ) -> List[str]:

        return [episode.episode_id
                for episode in self.episodes]

    def __init__(
        self,
        show_id,
        show_title,
        episodes,
        **kwargs
    ):
        self.show_id = show_id
        self.show_title = show_title

        self.episodes = episodes

    @classmethod
    def from_entity(
        cls,
        entity: Dict
    ):
        return Show(
            show_id=entity.get('show_id'),
            show_title=entity.get('show_title'),
            episodes=cls.get_entity_episodes(
                episodes=entity.get('episodes')))

    @classmethod
    def get_entity_episodes(
        cls,
        episodes
    ):
        if isinstance(episodes, OrderedDict):
            episodes = [episodes]

        return [Episode(
            episode_id=episode.get('episode_id'),
            episode_title=episode.get('title'),
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


class FeedHandler:
    @classmethod
    def get_show(
        cls,
        feed: str
    ) -> Show:

        dct = xmltodict.parse(xml_input=feed)
        channel = dct.get('rss').get('channel')

        episodes = [
            Episode.from_feed(data=episode)
            for episode in channel.get('item')
        ]

        return Show(
            show_id=channel.get('acast:showId'),
            show_title=channel.get('title'),
            episodes=episodes)


class DownloadedEpisode:
    def __init__(
        self,
        episode: Episode,
        show: Show,
        size: int
    ):
        self.episode = episode
        self.show = show
        self.size = round(size / 1048576)

    def get_text(
        self
    ) -> str:
        return f'{self.show.show_title}: {self.episode.episode_title}: {self.size}mb'

    def get_filename(
        self
    ) -> str:
        return self.episode.get_filename(
            show_title=self.show.show_title)
