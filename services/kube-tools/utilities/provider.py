import openai
from framework.abstractions.abstract_request import RequestContextProvider
from framework.auth.azure import AzureAd
from framework.auth.configuration import AzureAdConfiguration
from framework.clients.cache_client import CacheClientAsync
from framework.clients.feature_client import FeatureClientAsync
from framework.configuration.configuration import Configuration
from framework.di.service_collection import ServiceCollection
from framework.di.static_provider import ProviderBase
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient
from quart import Quart

from clients.azure_gateway_client import AzureGatewayClient
from clients.email_gateway_client import EmailGatewayClient
from clients.event_client import EventClient
from clients.gmail_client import GmailClient, GmailRuleService
from clients.google_drive_client import GoogleDriveClient
from clients.google_maps_client import GoogleMapsClient
from clients.identity_client import IdentityClient
from clients.nest_client import NestClient
from clients.storage_client import StorageClient
from clients.twilio_gateway import TwilioGatewayClient
from data.chat_gpt_repository import ChatGptRepository
from data.dead_man_switch_repository import DeadManSwitchRepository
from data.google.google_auth_repository import GoogleAuthRepository
from data.google.google_email_rule_repository import GoogleEmailRuleRepository
from data.google.google_location_history_repository import \
    GoogleLocationHistoryRepository
from data.google.google_reverse_geocode_repository import \
    GoogleReverseGeocodingRepository
from data.location_repository import (WeatherStationRepository,
                                      ZipLatLongRepository)
from data.mongo_export_repository import MongoExportRepository
from data.nest_repository import NestDeviceRepository, NestLogRepository, NestSensorRepository
from data.podcast_repository import PodcastRepository
from domain.auth import AdRole, AuthPolicy
from services.acr_purge_service import AcrPurgeService
from services.acr_service import AcrService
from services.chat_gpt_proxy_service import ChatGptProxyService
from services.dead_man_switch_service import DeadManSwitchService
from services.event_service import EventService
from services.gmail_service import GmailService
from services.google_auth_service import GoogleAuthService
from services.location_history_service import LocationHistoryService
from services.mongo_backup_service import MongoBackupService
from services.nest_command_service import NestCommandService
from services.nest_service import NestService
from services.podcast_service import PodcastService
from services.reverse_geocoding_service import GoogleReverseGeocodingService
from services.usage_service import UsageService


def configure_azure_ad(container):
    configuration = container.resolve(Configuration)

    # Hook the Azure AD auth config into the service
    # configuration
    ad_auth: AzureAdConfiguration = configuration.ad_auth
    azure_ad = AzureAd(
        tenant=ad_auth.tenant_id,
        audiences=ad_auth.audiences,
        issuer=ad_auth.issuer)

    azure_ad.add_authorization_policy(
        name=AuthPolicy.Default,
        func=lambda t: True)

    azure_ad.add_authorization_policy(
        name=AuthPolicy.Execute,
        func=lambda t: AdRole.Execute in t.get('roles'))

    # TODO: Remove default auth policy

    return azure_ad


def configure_http_client(
    container: ServiceCollection
):
    return AsyncClient(timeout=None)


def configure_mongo_client(
    container: ServiceCollection
):
    configuration = container.resolve(Configuration)

    connection_string = configuration.mongo.get('connection_string')
    client = AsyncIOMotorClient(connection_string)

    return client


def configure_openai(
    container: ServiceCollection
):
    configuration = container.resolve(Configuration)

    api_key = configuration.openai.get('api_key')
    openai.api_key = api_key

    return openai.Image


def register_factories(
    descriptors: ServiceCollection
):
    descriptors.add_singleton(
        dependency_type=AsyncClient,
        factory=configure_http_client)

    descriptors.add_singleton(
        dependency_type=AzureAd,
        factory=configure_azure_ad)

    descriptors.add_singleton(
        dependency_type=AsyncIOMotorClient,
        factory=configure_mongo_client)

    descriptors.add_singleton(
        dependency_type=openai.Image,
        factory=configure_openai)


def register_clients(
    descriptors: ServiceCollection
):
    descriptors.add_singleton(IdentityClient)
    descriptors.add_singleton(CacheClientAsync)
    descriptors.add_singleton(TwilioGatewayClient)
    descriptors.add_transient(GoogleDriveClient)
    descriptors.add_singleton(AzureGatewayClient)
    descriptors.add_singleton(FeatureClientAsync)
    descriptors.add_singleton(EmailGatewayClient)
    descriptors.add_singleton(StorageClient)
    descriptors.add_singleton(GoogleMapsClient)
    descriptors.add_singleton(EventClient)
    descriptors.add_singleton(GmailClient)
    descriptors.add_singleton(DeadManSwitchService)
    descriptors.add_singleton(NestClient)


def register_repositories(
    descriptors: ServiceCollection
):
    descriptors.add_singleton(PodcastRepository)
    descriptors.add_singleton(GoogleAuthRepository)
    descriptors.add_singleton(ZipLatLongRepository)
    descriptors.add_singleton(WeatherStationRepository)
    descriptors.add_singleton(GoogleLocationHistoryRepository)
    descriptors.add_singleton(GoogleReverseGeocodingRepository)
    descriptors.add_singleton(GoogleEmailRuleRepository)
    descriptors.add_singleton(DeadManSwitchRepository)
    descriptors.add_singleton(NestSensorRepository)
    descriptors.add_singleton(NestDeviceRepository)
    descriptors.add_singleton(MongoExportRepository)
    descriptors.add_singleton(ChatGptRepository)
    descriptors.add_singleton(NestLogRepository)


def register_services(
    descriptors: ServiceCollection
):
    descriptors.add_transient(PodcastService)
    descriptors.add_transient(AcrService)
    descriptors.add_transient(UsageService)
    descriptors.add_singleton(GoogleAuthService)
    descriptors.add_transient(MongoBackupService)
    descriptors.add_transient(AcrPurgeService)
    descriptors.add_transient(AcrService)
    descriptors.add_singleton(LocationHistoryService)
    descriptors.add_singleton(GoogleReverseGeocodingService)
    descriptors.add_singleton(EventService)
    descriptors.add_singleton(GmailRuleService)
    descriptors.add_singleton(GmailService)
    descriptors.add_singleton(NestService)
    descriptors.add_singleton(NestCommandService)
    descriptors.add_singleton(ChatGptProxyService)


class ContainerProvider(ProviderBase):
    @classmethod
    def configure_container(cls):
        descriptors = ServiceCollection()
        descriptors.add_singleton(Configuration)

        register_factories(
            descriptors=descriptors)

        # Repositories
        register_repositories(
            descriptors=descriptors)

        # Clients
        register_clients(
            descriptors=descriptors)

        # Services
        register_services(
            descriptors=descriptors)

        return descriptors


def add_container_hook(app: Quart):
    def inject_container():
        RequestContextProvider.initialize_provider(
            app=app)

    app.before_request_funcs.setdefault(
        None, []).append(
            inject_container)
