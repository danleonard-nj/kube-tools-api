import base64
import json
import uuid
from hashlib import md5

from framework.serialization import Serializable
from pymongo import MongoClient


def convert(value):
    return value / 10000000


class Location(Serializable):
    def __init__(self, data):
        latitude = convert(data.get('latitudeE7'))
        longitude = convert(data.get('longitudeE7'))
        self.location = {
            'type': 'Point',
            'coordinates': [longitude, latitude]
        }
        self.device_tag = data.get('deviceTag')
        self.source = data.get('source')
        self.accuracy = data.get('accuracy')
        self.timestamp = data.get('timestamp')

        self.key = self.get_key()

    def get_key(self):
        key_data = {
            'location': self.location,
            'timestamp': self.timestamp
        }

        key_text = json.dumps(key_data).encode()
        digest = md5(key_text).hexdigest()
        return str(uuid.UUID(digest))


cnxn_string = ''

with open('Records.json') as file:
    data = json.loads(file.read())

locations = data.get('locations')

client = MongoClient(cnxn_string)
db = client.get_database('Google')
collection = db.get_collection('LocationHistory')

models = [Location(data=item) for item in locations]
