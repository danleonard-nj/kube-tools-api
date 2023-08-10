import enum
from datetime import datetime

from framework.serialization import Serializable

from utilities.utils import ValueConverter


class TorrentSource(enum.StrEnum):
    PirateBay = 'piratebay'
    L337X = '1337x'


class TorrentDetail(Serializable):
    def __init__(
        self,
        name,
        seeders,
        leechers,
        date,
        size,
        uploader,
        source,
        data=None
    ):
        self.name = name
        self.seeders = seeders
        self.leechers = leechers
        self.date = date
        self.size = size
        self.uploader = uploader
        self.source = source
        self.data = data

    @staticmethod
    def from_pirate_bay(data):
        created_date = datetime.fromtimestamp(
            int(data.get('added')))

        size = ValueConverter.bytes_to_megabytes(
            bytes=int(data.get('size') or 0))

        additional_data = {
            'info_hash': data.get('info_hash'),
            'imdb': data.get('imdb'),
            'id': data.get('id'),
        }

        return TorrentDetail(
            name=data.get('name'),
            seeders=data.get('seeders'),
            leechers=data.get('leechers'),
            size=f'{size} mb',
            uploader=data.get('username'),
            date=created_date,
            source=TorrentSource.PirateBay,
            data=additional_data)

    @staticmethod
    def from_1337x_to(data):
        additional_data = {
            'stub': data.get('stub')
        }

        return TorrentDetail(
            name=data.get('name'),
            seeders=data.get('seeders'),
            leechers=data.get('leechers'),
            size=data.get('size'),
            uploader=data.get('uploader'),
            date=data.get('date'),
            data=additional_data,
            source=TorrentSource.L337X)
