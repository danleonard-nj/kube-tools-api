"""Storage for the journal MCP's OAuth authorization server.

Ported from plaid-sync's ``lib/mcp_oauth_repository.py``. Split by lifetime:

* **Mongo** holds registered clients and refresh tokens. Both must survive a
  Redis flush and a restart -- a client that has to re-register, or a connector
  that silently logs out, is a bad experience.
* **Redis** holds pending authorizations, authorization codes, access tokens
  and failed consent attempts. All are short-lived and want a TTL rather than
  a sweeper. Authorization codes additionally need single-use semantics, which
  ``GETDEL`` gives atomically.

Codes and tokens are stored hashed: a leaked dump is not a set of working
bearer tokens.

The Redis prefix is this service's own. oura-sync uses ``mcp:oauth:*`` and
plaid-sync ``spendyak:mcp:oauth:*``; sharing a prefix on the same Redis would
make each service accept the other's access tokens.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from framework.clients.cache_client import CacheClientAsync
from pymongo import AsyncMongoClient

DATABASE = 'Journals'
OAUTH_CLIENTS_COLLECTION = 'McpOAuthClients'
OAUTH_REFRESH_TOKENS_COLLECTION = 'McpOAuthRefreshTokens'

KEY_PREFIX = 'journal:mcp:oauth'
PENDING_PREFIX = f'{KEY_PREFIX}:pending'
CODE_PREFIX = f'{KEY_PREFIX}:code'
ACCESS_PREFIX = f'{KEY_PREFIX}:access'
ATTEMPTS_PREFIX = f'{KEY_PREFIX}:attempts'


def fingerprint(token: str) -> str:
    """Hash a token for storage and lookup."""
    return hashlib.sha256(token.encode()).hexdigest()


def _loads(raw: Any) -> Optional[dict]:
    return json.loads(raw) if raw else None


class McpOAuthRepository:
    def __init__(self, client: AsyncMongoClient, cache_client: CacheClientAsync):
        self._mongo = client
        self._cache_client = cache_client

    @property
    def _redis(self):
        return self._cache_client.client

    @property
    def _clients(self):
        return self._mongo[DATABASE][OAUTH_CLIENTS_COLLECTION]

    @property
    def _refresh(self):
        return self._mongo[DATABASE][OAUTH_REFRESH_TOKENS_COLLECTION]

    async def ensure_indexes(self) -> None:
        await self._clients.create_index('client_id', unique=True)
        await self._refresh.create_index('token_hash', unique=True)
        # Expired refresh tokens are refused on read; this only sweeps them.
        await self._refresh.create_index('expires_at_dt', expireAfterSeconds=0)

    # -- Registered clients (durable) ------------------------------------

    async def save_client(self, client_id: str, document: dict[str, Any]) -> None:
        await self._clients.update_one(
            {'client_id': client_id},
            {'$set': {'client_id': client_id, 'document': document}},
            upsert=True,
        )

    async def get_client(self, client_id: str) -> Optional[dict[str, Any]]:
        record = await self._clients.find_one({'client_id': client_id})
        return record['document'] if record else None

    # -- Pending authorizations (ephemeral) ------------------------------

    async def put_pending(self, txn_id: str, payload: dict[str, Any], ttl: int) -> None:
        await self._redis.set(f'{PENDING_PREFIX}:{txn_id}', json.dumps(payload), ex=ttl)

    async def peek_pending(self, txn_id: str) -> Optional[dict[str, Any]]:
        """Read without consuming, to render the consent page."""
        return _loads(await self._redis.get(f'{PENDING_PREFIX}:{txn_id}'))

    async def take_pending(self, txn_id: str) -> Optional[dict[str, Any]]:
        return _loads(await self._redis.getdel(f'{PENDING_PREFIX}:{txn_id}'))

    # -- Authorization codes (ephemeral, single-use) ---------------------

    async def put_code(self, code: str, payload: dict[str, Any], ttl: int) -> None:
        await self._redis.set(f'{CODE_PREFIX}:{fingerprint(code)}', json.dumps(payload), ex=ttl)

    async def peek_code(self, code: str) -> Optional[dict[str, Any]]:
        return _loads(await self._redis.get(f'{CODE_PREFIX}:{fingerprint(code)}'))

    async def take_code(self, code: str) -> Optional[dict[str, Any]]:
        """Consume atomically. A replayed code finds nothing."""
        return _loads(await self._redis.getdel(f'{CODE_PREFIX}:{fingerprint(code)}'))

    # -- Access tokens (ephemeral) ---------------------------------------

    async def put_access_token(self, token: str, payload: dict[str, Any], ttl: int) -> None:
        await self._redis.set(f'{ACCESS_PREFIX}:{fingerprint(token)}', json.dumps(payload), ex=ttl)

    async def get_access_token(self, token: str) -> Optional[dict[str, Any]]:
        return _loads(await self._redis.get(f'{ACCESS_PREFIX}:{fingerprint(token)}'))

    async def delete_access_token(self, token: str) -> None:
        await self._redis.delete(f'{ACCESS_PREFIX}:{fingerprint(token)}')

    # -- Refresh tokens (durable) ----------------------------------------

    async def put_refresh_token(self, token: str, payload: dict[str, Any]) -> None:
        document = {'token_hash': fingerprint(token), **payload}
        if payload.get('expires_at'):
            document['expires_at_dt'] = datetime.fromtimestamp(payload['expires_at'], tz=timezone.utc)
        await self._refresh.update_one(
            {'token_hash': document['token_hash']},
            {'$set': document},
            upsert=True,
        )

    async def get_refresh_token(self, token: str) -> Optional[dict[str, Any]]:
        return await self._refresh.find_one(
            {'token_hash': fingerprint(token)},
            projection={'_id': False, 'expires_at_dt': False},
        )

    async def delete_refresh_token(self, token: str) -> bool:
        result = await self._refresh.delete_one({'token_hash': fingerprint(token)})
        return result.deleted_count > 0

    # -- Consent brute-force guard ----------------------------------------

    async def record_failed_attempt(self, key: str, ttl: int) -> int:
        """Count a failed consent attempt within a rolling window."""
        redis_key = f'{ATTEMPTS_PREFIX}:{key}'
        attempts = await self._redis.incr(redis_key)
        if attempts == 1:
            await self._redis.expire(redis_key, ttl)
        return int(attempts)

    async def failed_attempts(self, key: str) -> int:
        value = await self._redis.get(f'{ATTEMPTS_PREFIX}:{key}')
        return int(value) if value else 0

    async def clear_failed_attempts(self, key: str) -> None:
        await self._redis.delete(f'{ATTEMPTS_PREFIX}:{key}')
