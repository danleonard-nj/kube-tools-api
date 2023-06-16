from abc import abstractmethod

import xmltodict

from domain.podcasts.podcasts import Episode, Show
from utilities.utils import KeyUtils


class FeedHandler:
    @abstractmethod
    def get_show(
        self,
        feed: str
    ):
        pass


class AcastFeedHandler(FeedHandler):
    def get_show(
        self,
        feed: str
    ):
        dct = xmltodict.parse(xml_input=feed)
        channel = dct.get('rss').get('channel')

        episodes = []
        for episode in channel.get('item', []):
            parsed = Episode.from_feed(
                data=episode,
                id_selector=(lambda data: data.get('acast:episodeId')),
                title_selector=(lambda data: data.get('title')),
                audio_selector=(lambda data: data.get('enclosure').get('@url')))

            episodes.append(parsed)

        return Show(
            show_id=channel.get('acast:showId'),
            show_title=channel.get('title'),
            episodes=episodes)


class GenericFeedHandler(FeedHandler):
    def get_show(
        self,
        feed: str
    ):
        dct = xmltodict.parse(xml_input=feed)
        channel = dct.get('rss').get('channel')

        show_title = channel.get('title')
        show_id = KeyUtils.create_uuid(
            show_title=show_title)

        episodes = []
        for episode in channel.get('item', []):
            parsed = Episode.from_feed(
                data=episode,
                id_selector=lambda x: x.get('guid', dict()).get('#text'),
                title_selector=lambda x: x.get('title'),
                audio_selector=lambda x: x.get('enclosure', dict()).get('@url'))

            episodes.append(parsed)

        return Show(
            show_id=show_id,
            show_title=show_title,
            episodes=episodes)
