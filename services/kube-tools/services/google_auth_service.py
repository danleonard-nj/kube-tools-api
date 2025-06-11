from datetime import datetime
import json

from framework.clients.cache_client import CacheClientAsync
from framework.exceptions.nulls import ArgumentNullException
from framework.logger.providers import get_logger
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from data.google.google_auth_repository import GoogleAuthRepository

logger = get_logger(__name__)

# 1 hour
CACHE_TTL_SECONDS = 60 * 60


class GoogleAuthService:
    def __init__(
        self,
        auth_repository: GoogleAuthRepository,
        cache_client: CacheClientAsync
    ):
        self._repo = auth_repository
        self._cache = cache_client

    async def save_client(
        self,
        client_name: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        token_uri: str = "https://oauth2.googleapis.com/token"
    ) -> bool:
        """Save client info and immediately fetch/store a token"""
        ArgumentNullException.if_none_or_whitespace(client_name, "client_name")
        ArgumentNullException.if_none_or_whitespace(client_id, "client_id")
        ArgumentNullException.if_none_or_whitespace(client_secret, "client_secret")
        ArgumentNullException.if_none_or_whitespace(refresh_token, "refresh_token")

        # Create credentials and fetch initial token
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=token_uri,
            client_id=client_id,
            client_secret=client_secret,
            scopes=[]  # Will be set per request
        )
        creds.refresh(Request())        # Store credentials as dict using Google's built-in serialization
        creds_dict = json.loads(creds.to_json())
        creds_dict["client_name"] = client_name
        creds_dict["updated_at"] = datetime.utcnow().isoformat()

        # Save to database
        await self._repo.set_client(creds_dict)
        # Clear any cached entries for this client
        cache_keys = [f"google_auth:{client_name}"]
        for key in cache_keys:
            await self._cache.client.delete(key)

        logger.info(f"Saved client '{client_name}' with fresh token")
        return True

    async def get_token(self, client_name: str, scopes: list[str]) -> str:
        """Get a token for the specified client and scopes"""
        ArgumentNullException.if_none_or_whitespace(client_name, "client_name")
        ArgumentNullException.if_none(scopes, "scopes")
        # Try cache first
        cache_key = f"google_auth:{client_name}:{'-'.join(sorted(scopes))}"
        cached_token = await self._cache.get_cache(key=cache_key)
        if cached_token:
            # Optionally, you could decode the JWT and check expiry, but Google tokens are opaque.
            # So, we rely on cache TTL. If you want to be extra safe, always refresh if in doubt.
            return cached_token

        # Get stored credentials from database
        stored_creds = await self._repo.get_client(client_name)
        if not stored_creds:
            raise Exception(f"No client found with name '{client_name}'. Please save client first.")

        # Remove only custom fields, keep all Google credential fields
        creds_data = {k: v for k, v in stored_creds.items()
                      if k not in ["client_name", "updated_at", "_id"]}

        # Ensure required fields are present
        required_fields = ["refresh_token", "token_uri", "client_id", "client_secret"]
        for field in required_fields:
            if field not in creds_data or not creds_data[field]:
                raise Exception(f"Stored credentials for '{client_name}' are missing required field: {field}")

        # Create credentials from stored data
        creds = Credentials.from_authorized_user_info(creds_data, scopes=scopes)

        # Always refresh if token is not valid or expires in <10min
        needs_refresh = not creds.valid or (creds.expiry and (creds.expiry - datetime.utcnow()).total_seconds() < 600)
        if needs_refresh:
            logger.info(f"[GoogleAuthService] Refreshing token for '{client_name}' (expired or expiring soon)")
            creds.refresh(Request())
            # Update stored credentials with new token/refresh_token
            updated_creds = json.loads(creds.to_json())
            updated_creds["client_name"] = client_name
            updated_creds["updated_at"] = datetime.utcnow().isoformat()
            await self._repo.set_client(updated_creds)
        else:
            logger.info(f"[GoogleAuthService] Using valid token from DB for '{client_name}' (first 8: {str(creds.token)[:8]})")

        # Cache the token for 50 minutes (10 min before expiry)
        await self._cache.set_cache(key=cache_key, value=creds.token, ttl=60)

        return creds.token
