import json


class TestHelper:
    def __init__(self):
        self.show_entity = None

    def get_podcast_config(self):
        return {
            "random_delay": False,
            "feeds": [
                {
                    "name": "test",
                    "feed": "http://test"
                },
            ]
        }

    def get_xml_data(self, **kwargs):
        with open('./tests/resources/feed_data.json', 'r') as file:
            data = json.loads(file.read())
            return data | kwargs

    def get_show_entity(self, **kwargs):
        if self.show_entity is None:
            with open('./tests/resources/show_entity.json', 'r') as file:
                self.show_entity = json.loads(file.read())

        return self.show_entity | kwargs
