from framework.abstractions.abstract_request import RequestContextProvider
from framework.auth.azure import AzureAd
from framework.auth.configuration import AzureAdConfiguration
from framework.clients.cache_client import CacheClientAsync
from framework.clients.feature_client import FeatureClientAsync
from framework.configuration.configuration import Configuration
from framework.di.service_collection import ServiceCollection
from framework.di.static_provider import ProviderBase
from motor.motor_asyncio import AsyncIOMotorClient
from quart import Quart

from clients.azure_gateway_client import AzureGatewayClient
from clients.email_gateway_client import EmailGatewayClient
from clients.event_client import EventClient
from clients.google_drive_client import GoogleDriveClient
from clients.google_maps_client import GoogleMapsClient
from clients.identity_client import IdentityClient
from clients.reverb_client import ReverbClient
from clients.storage_client import StorageClient
from clients.twilio_gateway import TwilioGatewayClient
from data.google.google_auth_repository import GoogleAuthRepository
from data.google.google_location_history_repository import \
    GoogleLocationHistoryRepository
from data.google.google_reverse_geocode_repository import \
    GoogleReverseGeocodingRepository
from data.location_repository import (WeatherStationRepository,
                                      ZipLatLongRepository)
from data.podcast_repository import PodcastRepository
from data.reverb_service_repositories import (ProcessorListingRepository,
                                              ProductConditionRepository,
                                              ProductMakeRepository,
                                              ProductRepository,
                                              ProductTransactionRepository)
from domain.auth import AdRole
from services.acr_service import AcrService
from services.event_service import EventService
from services.google_auth_service import GoogleAuthService
from services.location_history_service import LocationHistoryService
from services.location_service import LocationService
from services.mongo_backup_service import MongoBackupService
from services.podcast_service import PodcastService
from services.reverb.condition_service import ReverbProductConditionService
from services.reverb.listing_service import ReverbListingService
from services.reverb.product_make_service import ReverbProductMakeService
from services.reverb.product_service import ReverbProductService
from services.reverb.transaction_comparison_service import \
    ReverbTransactionComparisonService
from services.reverb_service import ReverbListingProcessor, ReverbListingService, ReverbListingSyncService
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
        name='default',
        func=lambda t: True)

    azure_ad.add_authorization_policy(
        name='execute',
        func=lambda t: AdRole.EXECUTE in t.get('roles'))

    return azure_ad


def configure_mongo_client(container):
    configuration = container.resolve(Configuration)

    connection_string = configuration.mongo.get('connection_string')
    client = AsyncIOMotorClient(connection_string)

    return client


class ContainerProvider(ProviderBase):
    @classmethod
    def configure_container(cls):
        container = ServiceCollection()
        container.add_singleton(Configuration)

        container.add_singleton(
            dependency_type=AzureAd,
            factory=configure_azure_ad)

        container.add_singleton(
            dependency_type=AsyncIOMotorClient,
            factory=configure_mongo_client)

        # Repositories
        container.add_singleton(PodcastRepository)
        container.add_singleton(GoogleAuthRepository)
        container.add_singleton(ZipLatLongRepository)
        container.add_singleton(WeatherStationRepository)
        container.add_singleton(GoogleLocationHistoryRepository)
        container.add_singleton(GoogleReverseGeocodingRepository)
        container.add_singleton(ProductMakeRepository)
        container.add_singleton(ProductRepository)
        container.add_singleton(ProcessorListingRepository)
        container.add_singleton(ProductConditionRepository)

        # Clients
        container.add_singleton(IdentityClient)
        container.add_singleton(CacheClientAsync)
        container.add_singleton(TwilioGatewayClient)
        container.add_transient(GoogleDriveClient)
        container.add_singleton(AzureGatewayClient)
        container.add_singleton(FeatureClientAsync)
        container.add_singleton(EmailGatewayClient)
        container.add_singleton(StorageClient)
        # container.add_transient(GmailClient)
        # container.add_singleton(HttpClient)
        container.add_singleton(GoogleMapsClient)
        container.add_singleton(ReverbClient)
        container.add_singleton(EventClient)

        # Services
        container.add_transient(PodcastService)
        container.add_transient(AcrService)
        container.add_transient(UsageService)
        container.add_transient(GoogleAuthService)
        container.add_transient(MongoBackupService)
        container.add_singleton(LocationService)
        container.add_singleton(LocationHistoryService)
        container.add_singleton(GoogleReverseGeocodingService)
        container.add_singleton(ReverbListingService)
        container.add_singleton(ReverbProductMakeService)
        container.add_singleton(ReverbProductService)
        container.add_singleton(ReverbListingSyncService)
        container.add_singleton(ReverbTransactionComparisonService)
        container.add_singleton(ProductTransactionRepository)
        container.add_singleton(ReverbProductConditionService)
        container.add_singleton(ReverbListingProcessor)
        container.add_singleton(EventService)

        return container


def add_container_hook(app: Quart):
    def inject_container():
        RequestContextProvider.initialize_provider(
            app=app)

    app.before_request_funcs.setdefault(
        None, []).append(
            inject_container)
