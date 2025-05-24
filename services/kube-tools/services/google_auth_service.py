from datetime import datetime, timedelta
import json

from framework.clients.cache_client import CacheClientAsync
from framework.exceptions.nulls import ArgumentNullException
from framework.logger.providers import get_logger
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from data.google.google_auth_repository import GoogleAuthRepository
from domain.google import AuthClient
from utilities.utils import fire_task

logger = get_logger(__name__)

# 30 days
CACHE_TTL_SECONDS = 60 * 60 * 24 * 30


class GoogleAuthService:
    def __init__(
        self,
        auth_repository: GoogleAuthRepository,
        cache_client: CacheClientAsync
    ):
        self._repo = auth_repository
        self._cache = cache_client

    async def _fetch_or_cache(self, cache_key: str, db_coro):
        data = await self._cache.get_json(cache_key)
        if data:
            return data
        data = await db_coro()
        if data:
            await self._cache.set_json(cache_key, data, ttl=CACHE_TTL_SECONDS)
        return data

    # ---- DB access (always dict in/out) ----

    async def _get_client_info_db(self, client_name: str) -> dict | None:
        try:
            return await self._repo.get_client(client_name)
        except Exception:
            logger.exception(f"DB read failed for client '{client_name}'")
            raise

    async def _set_client_info_db(self, client_name: str, data: dict) -> None:
        try:
            # Parse to AuthClient for service logic, but only pass dict to repo
            client = AuthClient(
                client_name=client_name,
                token=data.get("token"),
                refresh_token=data.get("refresh_token"),
                token_url=data.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=data.get("client_id"),
                client_secret=data.get("client_secret"),
                expiry=data.get("expiry", datetime.utcnow().isoformat()),
                timestamp=data.get("timestamp", datetime.utcnow().isoformat()),
            )
            await self._repo.set_client(client.to_dict())
        except Exception:
            logger.exception(f"DB write failed for client '{client_name}': {json.dumps(data)}")
            raise

    async def _get_refresh_token_db(self, client_name: str) -> dict | None:
        try:
            data = await self._repo.get_client(client_name)
            if not data or "refresh_token" not in data:
                return None
            return {
                "refresh_token": data["refresh_token"],
                "token_uri": data.get("token_uri", "https://oauth2.googleapis.com/token"),
                "client_id": data.get("client_id"),
                "client_secret": data.get("client_secret"),
            }
        except Exception:
            logger.exception(f"DB read failed for refresh token '{client_name}'")
            raise

    async def _set_refresh_token_db(self, client_name: str, refresh_token: dict) -> None:
        try:
            await self._repo.update_refresh_token(
                client_name=client_name,
                refresh_token=refresh_token
            )
        except Exception:
            logger.exception(f"DB write failed for refresh token '{client_name}': {refresh_token}")
            raise

    # ---- Cached wrappers ----

    async def _get_client_info(self, client_name: str) -> dict | None:
        key = f"google_auth_client:{client_name}"
        return await self._fetch_or_cache(key, lambda: self._get_client_info_db(client_name))

    async def _get_refresh_token(self, client_name: str) -> dict | None:
        key = f"google_auth_refresh:{client_name}"
        return await self._fetch_or_cache(key, lambda: self._get_refresh_token_db(client_name))

    async def _set_client_info(self, client_name: str, data: dict) -> None:
        key = f"google_auth_client:{client_name}"
        await self._cache.set_json(key, data, ttl=CACHE_TTL_SECONDS)
        await self._set_client_info_db(client_name, data)

    async def _set_refresh_token(self, client_name: str, refresh_token: str) -> None:
        key = f"google_auth_refresh:{client_name}"
        await self._cache.set_json(key, refresh_token, ttl=CACHE_TTL_SECONDS)
        await self._set_refresh_token_db(client_name, refresh_token)

    # ---- Public API ----

    async def get_credentials(
        self,
        client_name: str,
        scopes: list[str]
    ) -> Credentials:
        ArgumentNullException.if_none_or_whitespace(client_name, "client_name")
        ArgumentNullException.if_none(scopes, "scopes")

        cache_key = f"google_auth:{client_name}:{'-'.join(scopes)}"
        token_data = await self._cache.get_json(cache_key) or {}

        if token_data.get("expiry"):
            expiry = datetime.fromisoformat(token_data["expiry"])
            if expiry > datetime.utcnow():
                return Credentials(
                    token=token_data["token"],
                    refresh_token=token_data["refresh_token"],
                    token_uri=token_data.get("token_uri"),
                    client_id=token_data.get("client_id"),
                    client_secret=token_data.get("client_secret"),
                    scopes=scopes,
                )

        refresh = await self._get_refresh_token(client_name)
        if not refresh or "refresh_token" not in refresh:
            raise Exception("No refresh token available. Please set it via the update_refresh_token endpoint.")

        # ensure valid scopes
        if not scopes:
            info = await self._get_client_info(client_name) or {}
            scopes = info.get("scopes", scopes)

        creds = Credentials(
            token=None,
            refresh_token=refresh["refresh_token"],
            token_uri=refresh["token_uri"],
            client_id=refresh["client_id"],
            client_secret=refresh["client_secret"],
            scopes=scopes,
        )
        creds.refresh(Request())

        new_expiry = creds.expiry.isoformat() if creds.expiry else (datetime.utcnow() + timedelta(minutes=55)).isoformat()
        new_token_data = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "expiry": new_expiry,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
        }

        # cache asynchronously
        fire_task(self._cache.set_json(key=cache_key, value=new_token_data, ttl=3600))

        # persist if refresh token rolled
        if creds.refresh_token != refresh.get("refresh_token"):
            fire_task(self._set_refresh_token(client_name, new_token_data))

        return creds

    async def get_token(self, client_name: str, scopes: list[str]) -> str:
        creds = await self.get_credentials(client_name, scopes)
        return creds.token

    async def save_client_info(
        self,
        client_name: str,
        client_id: str,
        client_secret: str,
        token_uri: str = "https://oauth2.googleapis.com/token",
        refresh_token: str | None = None
    ) -> bool:
        ArgumentNullException.if_none_or_whitespace(client_name, "client_name")
        ArgumentNullException.if_none_or_whitespace(client_id, "client_id")
        ArgumentNullException.if_none_or_whitespace(client_secret, "client_secret")

        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "token_uri": token_uri,
        }
        await self._set_client_info(client_name, data)
        logger.info(f"Saved client info for '{client_name}'")

        if refresh_token:
            rt_data = {
                "refresh_token": refresh_token,
                "token_uri": token_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            }
            await self._set_refresh_token(client_name, rt_data)
            logger.info(f"Saved refresh token for '{client_name}'")

        return True

    async def update_refresh_token(self, client_name: str, refresh_token: str) -> bool:
        ArgumentNullException.if_none_or_whitespace(client_name, "client_name")
        ArgumentNullException.if_none_or_whitespace(refresh_token, "refresh_token")

        info = await self._get_client_info(client_name)
        if not info:
            raise Exception("Client info not found. Please save client info first.")

        data = {
            "refresh_token": refresh_token,
            "token_uri": info.get("token_uri", "https://oauth2.googleapis.com/token"),
            "client_id": info["client_id"],
            "client_secret": info["client_secret"],
        }
        await self._set_refresh_token(client_name, data)
        logger.info(f"Updated refresh token for '{client_name}'")
        return True
