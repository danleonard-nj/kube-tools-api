from clients.azure_gateway_client import AzureGatewayClient
from clients.chat_gpt_service_client import ChatGptServiceClient
from clients.coinbase_client import CoinbaseClient
from clients.email_gateway_client import EmailGatewayClient
from clients.event_client import EventClient
from clients.gmail_client import GmailClient
from clients.google_auth_client import GoogleAuthClient
from clients.google_drive_client import GoogleDriveClient
from clients.google_maps_client import GoogleMapsClient
from clients.identity_client import IdentityClient
from clients.open_weather_client import OpenWeatherClient
from clients.plaid_client import PlaidClient
from clients.storage_client import StorageClient
from clients.torrent_client import TorrentClient
from clients.twilio_gateway import TwilioGatewayClient
from clients.google_drive_client_async import GoogleDriveClientAsync
from data.api_event_repository import ApiEventRepository
from data.bank_repository import (BankBalanceRepository,
                                  BankTransactionsRepository,
                                  BankWebhooksRepository)
from data.chat_gpt_repository import ChatGptRepository
from data.google.google_auth_repository import GoogleAuthRepository
from data.google.google_calendar_repository import GooleCalendarEventRepository
from data.google.google_email_log_repository import GoogleEmailLogRepository
from data.google.google_email_rule_repository import GoogleEmailRuleRepository
from data.google.google_location_history_repository import \
    GoogleLocationHistoryRepository
from data.google.google_reverse_geocode_repository import \
    GoogleReverseGeocodingRepository
from data.location_repository import (WeatherStationRepository,
                                      ZipLatLongRepository)
from data.mongo_export_repository import MongoExportRepository
from data.podcast_repository import PodcastRepository
from data.conversation_repository import ConversationRepository
from data.weather_repository import WeatherRepository
from domain.auth import AdRole, AuthPolicy
from framework.abstractions.abstract_request import RequestContextProvider
from framework.auth.azure import AzureAd
from framework.auth.configuration import AzureAdConfiguration
from framework.caching.memory_cache import MemoryCache
from framework.clients.cache_client import CacheClientAsync
from framework.clients.feature_client import FeatureClientAsync
from framework.configuration.configuration import Configuration
from framework.di.service_collection import ServiceCollection
from framework.di.static_provider import ProviderBase
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient
from quart import Quart
from services.acr_purge_service import AcrPurgeService
from services.acr_service import AcrService
from services.api_event_service import ApiEventHistoryService
from services.bank_balance_service import BalanceSyncService
from services.bank_service import BankService
from services.bank_transaction_service import BankTransactionService
from services.calendar_service import CalendarService
from services.chat_gpt_service import ChatGptService
from services.coinbase_service import CoinbaseService
from services.event_service import EventService
from services.gmail_balance_sync_service import GmailBankSyncService
from services.gmail_rule_service import GmailRuleService
from services.gmail_service import GmailService
from services.google_auth_service import GoogleAuthService
from services.google_drive_service import GoogleDriveService
from services.location_history_service import LocationHistoryService
from services.mongo_backup_service import MongoBackupService
from services.podcast_service import PodcastService
from services.redis_service import RedisService
from services.reverse_geocoding_service import GoogleReverseGeocodingService
from services.conversation_service import ConversationService
from services.torrent_service import TorrentService
from services.usage_service import UsageService
from services.weather_service import WeatherService


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

    azure_ad.add_authorization_policy(
        name=AuthPolicy.Banking,
        func=lambda t: AdRole.Banking in t.get('roles'))

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


def register_clients(
    descriptors: ServiceCollection
):
    descriptors.add_singleton(IdentityClient)
    descriptors.add_singleton(MemoryCache)
    descriptors.add_singleton(CacheClientAsync)
    descriptors.add_singleton(TwilioGatewayClient)
    descriptors.add_singleton(GoogleDriveClient)
    descriptors.add_singleton(GoogleDriveClientAsync)
    descriptors.add_singleton(AzureGatewayClient)
    descriptors.add_singleton(FeatureClientAsync)
    descriptors.add_singleton(EmailGatewayClient)
    descriptors.add_singleton(StorageClient)
    descriptors.add_singleton(GoogleMapsClient)
    descriptors.add_singleton(EventClient)
    descriptors.add_singleton(GmailClient)
    descriptors.add_singleton(ChatGptServiceClient)
    descriptors.add_singleton(PlaidClient)
    descriptors.add_singleton(OpenWeatherClient)
    descriptors.add_singleton(TorrentClient)
    descriptors.add_singleton(GoogleAuthClient)
    descriptors.add_singleton(CoinbaseClient)


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
    descriptors.add_singleton(MongoExportRepository)
    descriptors.add_singleton(ChatGptRepository)
    descriptors.add_singleton(ApiEventRepository)
    descriptors.add_singleton(GoogleEmailLogRepository)
    descriptors.add_singleton(BankBalanceRepository)
    descriptors.add_singleton(BankTransactionsRepository)
    descriptors.add_singleton(BankWebhooksRepository)
    descriptors.add_singleton(WeatherRepository)
    descriptors.add_singleton(GooleCalendarEventRepository)
    descriptors.add_singleton(ConversationRepository)


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
    descriptors.add_singleton(GmailBankSyncService)
    descriptors.add_singleton(ApiEventHistoryService)
    descriptors.add_singleton(BankService)
    descriptors.add_singleton(WeatherService)
    descriptors.add_singleton(BankTransactionService)
    descriptors.add_singleton(BalanceSyncService)
    descriptors.add_singleton(TorrentService)
    descriptors.add_singleton(CalendarService)
    descriptors.add_singleton(RedisService)
    descriptors.add_singleton(GoogleDriveService)
    descriptors.add_singleton(ChatGptService)
    descriptors.add_singleton(ConversationService)
    descriptors.add_singleton(CoinbaseService)


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
