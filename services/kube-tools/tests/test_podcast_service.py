import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from services.podcast_service import PodcastService, PodcastServiceException
from domain.podcasts.podcasts import DownloadedEpisode, Episode, Feed, Show
from domain.drive import GoogleDriveUploadRequest
from domain.google import GoogleDriveDirectory


class DummyConfig:
    def __init__(self):
        self.random_delay = False
        self.feeds = []


def make_service():
    return PodcastService(
        podcast_repository=AsyncMock(),
        google_drive_client=AsyncMock(),
        email_gateway_client=MagicMock(),
        event_service=AsyncMock(),
        feature_client=AsyncMock(),
        configuration=MagicMock(),
        http_client=AsyncMock(),
        podcast_config=DummyConfig()
    )


@pytest.mark.asyncio
def test_get_podcasts_returns_shows():
    service = make_service()
    fake_entity = MagicMock()
    service._podcast_repository.get_all.return_value = [fake_entity]
    with patch('domain.podcasts.podcasts.Show.from_entity', return_value='show'):
        result = asyncio.run(service.get_podcasts())
        assert result == ['show']


@pytest.mark.asyncio
def test_sync_handles_all_feeds():
    service = make_service()
    feed = MagicMock()
    feed.name = 'Test Feed'
    service.get_feeds = MagicMock(return_value=[(feed, 'folder')])
    service.handle_feed = AsyncMock(return_value=['downloaded'])
    result = asyncio.run(service.sync())
    assert isinstance(result, dict)
    service.handle_feed.assert_awaited()


@pytest.mark.asyncio
def test_handle_feed_no_new_episodes():
    service = make_service()
    feed = MagicMock()
    feed.name = 'Test Feed'
    service._sync_feed = AsyncMock(return_value=([], MagicMock()))
    result = asyncio.run(service.handle_feed(feed))
    assert result is None


@pytest.mark.asyncio
def test_handle_feed_with_new_episodes():
    service = make_service()
    feed = MagicMock()
    feed.name = 'Test Feed'
    show = MagicMock()
    show.get_selector.return_value = 'selector'
    show.to_dict.return_value = {'foo': 'bar'}
    service._sync_feed = AsyncMock(return_value=([MagicMock()], show))
    service._podcast_repository.update = AsyncMock()
    service._send_email = AsyncMock()
    result = asyncio.run(service.handle_feed(feed))
    assert result is not None
    service._podcast_repository.update.assert_awaited()
    service._send_email.assert_awaited()


@pytest.mark.asyncio
def test_get_feeds_returns_tuples():
    service = make_service()
    service._rss_feeds = [MagicMock(folder_name='folder')]
    with patch('domain.podcasts.podcasts.Feed', side_effect=lambda x: x):
        feeds = service.get_feeds()
        assert isinstance(feeds, list)
        assert isinstance(feeds[0], tuple)


@pytest.mark.asyncio
def test__get_results_table():
    service = make_service()
    ep = MagicMock()
    ep.to_result.return_value = {'id': 1}
    result = service._get_results_table([ep])
    assert result == [{'id': 1}]


@pytest.mark.asyncio
def test__wait_random_delay_no_delay():
    service = make_service()
    service._random_delay = False
    asyncio.run(service._wait_random_delay())


@pytest.mark.asyncio
def test__wait_random_delay_with_delay(monkeypatch):
    service = make_service()
    service._random_delay = True
    monkeypatch.setattr('random.randint', lambda a, b: 1)
    monkeypatch.setattr('asyncio.sleep', AsyncMock())
    asyncio.run(service._wait_random_delay())


@pytest.mark.asyncio
def test__send_email_disabled():
    service = make_service()
    service._feature_client.is_enabled = AsyncMock(return_value=False)
    asyncio.run(service._send_email([MagicMock()]))


@pytest.mark.asyncio
def test__send_email_no_episodes():
    service = make_service()
    service._feature_client.is_enabled = AsyncMock(return_value=True)
    asyncio.run(service._send_email([]))


@pytest.mark.asyncio
def test__send_email_success():
    service = make_service()
    service._feature_client.is_enabled = AsyncMock(return_value=True)
    service._email_gateway_client.get_datatable_email_request.return_value = (MagicMock(to_dict=lambda: {}), 'endpoint')
    service._event_service.dispatch_email_event = AsyncMock()
    asyncio.run(service._send_email([MagicMock()]))
    service._event_service.dispatch_email_event.assert_awaited()


@pytest.mark.asyncio
def test__get_feed_request():
    service = make_service()
    feed = MagicMock(feed='url')
    with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
        mock_get.return_value = MagicMock()
        result = asyncio.run(service._get_feed_request(feed))
        assert mock_get.called


@pytest.mark.asyncio
def test_get_episode_audio():
    service = make_service()
    episode = MagicMock(audio='url', episode_title='title')
    service._http_client.stream = MagicMock(return_value='stream')
    result = service.get_episode_audio(episode)
    assert result == 'stream'


@pytest.mark.asyncio
def test__get_saved_show_found():
    service = make_service()
    show = MagicMock(show_id='id', show_title='title')
    entity = MagicMock()
    service._podcast_repository.get = AsyncMock(return_value=entity)
    with patch('domain.podcasts.podcasts.Show.from_entity', return_value=show):
        result, is_new = asyncio.run(service._get_saved_show(show))
        assert result == show
        assert not is_new


@pytest.mark.asyncio
def test__get_saved_show_not_found():
    service = make_service()
    show = MagicMock(show_id='id', show_title='title')
    service._podcast_repository.get = AsyncMock(return_value=None)
    service._podcast_repository.insert = AsyncMock(return_value=MagicMock(inserted_id='foo'))
    result, is_new = asyncio.run(service._get_saved_show(show))
    assert is_new


@pytest.mark.asyncio
def test__get_handler_acast():
    service = make_service()
    with patch('services.podcast_service.AcastFeedHandler', return_value='acast'):
        assert service._get_handler('rss-acast') == 'acast'


@pytest.mark.asyncio
def test__get_handler_generic():
    service = make_service()
    with patch('services.podcast_service.GenericFeedHandler', return_value='generic'):
        assert service._get_handler('rss-generic') == 'generic'


@pytest.mark.asyncio
def test__get_handler_invalid():
    service = make_service()
    with pytest.raises(Exception):
        service._get_handler('invalid')


@pytest.mark.asyncio
def test_upload_file_async_with_folder():
    service = make_service()
    downloaded_episode = MagicMock()
    downloaded_episode.get_filename.return_value = 'file.mp3'
    downloaded_episode.episode = MagicMock()
    downloaded_episode.show = MagicMock()
    service._google_drive_client.resolve_drive_folder_id = AsyncMock(return_value='folderid')
    service._google_drive_upload_helper.upload_episode = AsyncMock()
    asyncio.run(service.upload_file_async(downloaded_episode, drive_folder_path='folder'))
    service._google_drive_upload_helper.upload_episode.assert_awaited()


@pytest.mark.asyncio
def test_upload_file_async_no_folder():
    service = make_service()
    downloaded_episode = MagicMock()
    downloaded_episode.get_filename.return_value = 'file.mp3'
    downloaded_episode.episode = MagicMock()
    downloaded_episode.show = MagicMock()
    service._google_drive_upload_helper.upload_episode = AsyncMock()
    asyncio.run(service.upload_file_async(downloaded_episode))
    service._google_drive_upload_helper.upload_episode.assert_awaited()
