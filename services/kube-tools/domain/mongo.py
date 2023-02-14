

class MongoBackupConstants:
    ContainerName = 'mongo-dumps'
    DateTimeFormat = '%Y_%m_%d_%H_%M_%S'


class MongoDatabase:
    Podcasts = 'Podcasts'
    WeatherStation = 'WeatherStation'
    OpenAi = 'OpenAi'
    WellnessCheck = 'WellnessCheck'
    Sms = 'SMS'


class MongoCollection:
    PodcastShows = 'Shows'
    WeatherStationCoordinate = 'StationCoordinate'
    WeatherStationZipLatLong = 'ZipLatLong'
    OpenAiRequest = 'OpenAiRequest'
    WellnessCheck = 'WellnessCheck'
    WellnessReply = 'WellnessReply'
    SmsConversations = 'SmsConversations'
