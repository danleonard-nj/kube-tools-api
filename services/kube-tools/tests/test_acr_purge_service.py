import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch
from services.acr_purge_service import AcrPurgeService
from services.acr_service import AcrImage


class DummyConfig:
    def __init__(self, exclusions=None):
        self.acr_purge = {'exclusions': exclusions or []}


def make_service(exclusions=None):
    config = DummyConfig(exclusions)
    email_client = MagicMock()
    event_service = AsyncMock()
    azure_gateway_client = AsyncMock()
    acr_service = AsyncMock()
    return AcrPurgeService(
        configuration=config,
        email_client=email_client,
        event_service=event_service,
        azure_gateway_client=azure_gateway_client,
        acr_service=acr_service
    ), email_client, event_service, azure_gateway_client, acr_service


@pytest.mark.asyncio
async def test_purge_images_basic(monkeypatch):
    service, email_client, event_service, azure_gateway_client, acr_service = make_service()
    acr_service.get_acr_repo_names.return_value = ['repo1']
    azure_gateway_client.get_pod_images.return_value = {'pods': [{'active_image': 'azureks.azurecr.io/repo1:tag1'}]}
    service._is_excluded = MagicMock(return_value=False)
    service.purge_repo = AsyncMock(return_value=[AcrImage(id='id1', tag='tag1', created_date='2024-01-01T00:00:00Z', image_size=123)])
    email_client.get_datatable_email_request.return_value = (MagicMock(to_dict=lambda: {}), 'endpoint')
    event_service.dispatch_email_event.return_value = AsyncMock()

    result = await service.purge_images(days_back=3, top_count=2)
    assert isinstance(result, list)
    assert service.purge_repo.await_count == 1
    event_service.dispatch_email_event.assert_awaited()


@pytest.mark.asyncio
async def test_purge_images_excluded_repo():
    service, _, _, azure_gateway_client, acr_service = make_service()
    acr_service.get_acr_repo_names.return_value = ['repo1']
    azure_gateway_client.get_pod_images.return_value = {'pods': []}
    service._is_excluded = MagicMock(return_value=True)
    service.purge_repo = AsyncMock()

    result = await service.purge_images(days_back=3, top_count=2)
    assert result == []
    service.purge_repo.assert_not_awaited()


@pytest.mark.asyncio
async def test_purge_repo_filters(monkeypatch):
    service, *_ = make_service()
    repo_name = 'repo1'
    now = pd.Timestamp.utcnow()
    images = [AcrImage(id='id1', tag='tag1', created_date=(now - pd.Timedelta(days=10)).isoformat(), image_size=123)]
    service._acr_service.get_manifests = AsyncMock(return_value=images)
    active_images = pd.DataFrame([{'active_image': 'azureks.azurecr.io/repo1:othertag'}])
    service._acr_service.purge_image = AsyncMock()
    result = await service.purge_repo(repo_name, active_images, days_back=3, top_count=0)
    assert isinstance(result, list)
    service._acr_service.purge_image.assert_awaited()


@pytest.mark.asyncio
async def test_purge_repo_no_images_to_purge():
    service, *_ = make_service()
    repo_name = 'repo1'
    service._acr_service.get_manifests = AsyncMock(return_value=[])
    active_images = pd.DataFrame([])
    service._acr_service.purge_image = AsyncMock()
    result = await service.purge_repo(repo_name, active_images, days_back=3, top_count=0)
    assert result == []
    service._acr_service.purge_image.assert_not_awaited()


def test_is_excluded_true():
    exclusion = "repository_name == 'repo1'"
    service, *_ = make_service([exclusion])
    assert service._is_excluded('repo1') is True


def test_is_excluded_false():
    exclusion = "repository_name == 'repo2'"
    service, *_ = make_service([exclusion])
    assert service._is_excluded('repo1') is False
