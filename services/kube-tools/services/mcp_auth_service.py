"""OAuth 2.1 authorization server for the journal MCP endpoint.

Ported unchanged in behaviour from plaid-sync's ``lib/mcp_auth_service.py``,
itself modelled on oura-sync's ``McpAuthService``; only where it lives differs.
The endpoints sit under ``mcp.issuer_path`` rather than the host root, because
this service is reached through the shared API gateway.

MCP clients such as Claude's custom connectors and ChatGPT offer only OAuth
discovery, with no field for a static header, so this service issues its own
tokens. The SDK provides the protocol surface (``/authorize``, ``/token``,
``/register``, ``/revoke`` and the two discovery documents); this module
supplies the behaviour behind them.

**There is no user database.** This deployment serves one person. An
authorization is approved by entering an owner secret on a consent screen.
``mcp.oauth.owner_password`` is compared directly, so it must be high-entropy --
generate it like an API key. Failed attempts are counted per authorization
request and lock out after ``consent_max_attempts``.

**Dynamic client registration is open**, because ChatGPT and Claude cannot be
pre-registered. That is per RFC 7591 and safe here because registration alone
grants nothing: every authorization still has to be approved with the owner
secret.

**Write access is opt-in per authorization.** Every token carries the read
scope; the write scope only when the approver ticks it on the consent page.

**Refresh keeps the resource**, and a request without one (or naming this
server's origin) is bound to this endpoint, so ``validate_resource`` can be on.

**A reused authorization code is an OAuth error** (``invalid_grant``), not a 500.

Token values are random and opaque rather than JWTs: a JWT saves a lookup, but
revocation then needs a denylist that costs the same lookup, and an opaque
token cannot leak claims.
"""

from __future__ import annotations

import hmac
import secrets
import time
from typing import Any, Optional
from urllib.parse import urlsplit

from framework.logger import get_logger
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from data.mcp_oauth_repository import McpOAuthRepository
from models.mcp_config import McpConfig

logger = get_logger(__name__)


class ConsentError(Exception):
    """The consent step could not be completed."""


class ConsentLockedOut(ConsentError):
    """Too many failed owner-password attempts."""


class McpAuthService:
    """Implements the SDK's ``OAuthAuthorizationServerProvider`` contract."""

    def __init__(self, repository: McpOAuthRepository, config: McpConfig):
        self._repository = repository
        self._config = config
        self._oauth = config.oauth
        self._owner_password = (
            config.oauth.owner_password.get_secret_value()
            if config.oauth.owner_password else None
        )

    @property
    def resource_url(self) -> str:
        """The MCP endpoint's public URL: the resource every token is bound to."""
        return self._config.resource_url

    # -- Client registration ---------------------------------------------

    async def get_client(self, client_id: str) -> Optional[OAuthClientInformationFull]:
        document = await self._repository.get_client(client_id)
        if document is None:
            return None
        return OAuthClientInformationFull.model_validate(document)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        await self._repository.save_client(
            client_info.client_id,
            client_info.model_dump(mode='json', exclude_none=True),
        )
        logger.info(
            'MCP OAuth client registered: client_id=%s name=%s',
            client_info.client_id, client_info.client_name)

    # -- Authorization -----------------------------------------------------

    def _bound_resource(self, requested: Optional[str]) -> str:
        """The resource a token is bound to: always this MCP endpoint.

        RFC 8707's resource parameter is optional, and clients differ in what
        they send -- the endpoint URL or just the server's origin. Tokens from
        this server are only ever for this endpoint, so either form (or none)
        binds to it; anything else is refused rather than issued as a token
        that would then fail on every call.
        """
        if not requested:
            return self.resource_url
        if _comparable(requested) in (_comparable(self.resource_url), _comparable(self._config.public_base_url)):
            return self.resource_url
        raise AuthorizeError('invalid_target', f'This server only issues tokens for {self.resource_url}.')

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        """Park the request and send the browser to the consent page.

        Nothing is issued here; the code is minted once the owner secret is
        accepted.
        """
        txn_id = secrets.token_urlsafe(32)
        await self._repository.put_pending(
            txn_id,
            {
                'client_id': client.client_id,
                'client_name': client.client_name,
                'redirect_uri': str(params.redirect_uri),
                'redirect_uri_provided_explicitly': params.redirect_uri_provided_explicitly,
                'code_challenge': params.code_challenge,
                'state': params.state,
                'requested_scopes': params.scopes or [],
                'resource': self._bound_resource(params.resource),
            },
            ttl=self._oauth.consent_ttl_seconds,
        )

        logger.info('MCP OAuth authorization pending consent: client_id=%s', client.client_id)
        return f'{self._config.public_base_url}{self._config.consent_path}?txn={txn_id}'

    async def pending_request(self, txn_id: str) -> Optional[dict[str, Any]]:
        """Details for rendering the consent page. No secrets in the result."""
        pending = await self._repository.peek_pending(txn_id)
        if pending is None:
            return None
        return {
            'client_id': pending['client_id'],
            'client_name': pending.get('client_name'),
            'redirect_uri': pending['redirect_uri'],
            'redirect_host': urlsplit(pending['redirect_uri']).hostname or '',
            'requested_scopes': pending.get('requested_scopes') or [],
        }

    async def approve_consent(self, txn_id: str, password: str, attempt_key: str, allow_write: bool) -> str:
        """Validate the owner secret and mint an authorization code.

        Returns the redirect URL back to the client, carrying ``code`` and the
        original ``state``.
        """
        if self._owner_password is None:
            raise ConsentError('MCP OAuth is not configured on this server.')

        attempts = await self._repository.failed_attempts(attempt_key)
        if attempts >= self._oauth.consent_max_attempts:
            raise ConsentLockedOut(
                'Too many failed attempts. Wait '
                f'{self._oauth.consent_lockout_seconds // 60} minutes and try again.')

        pending = await self._repository.peek_pending(txn_id)
        if pending is None:
            raise ConsentError(
                'This authorization request has expired or was already completed. '
                'Start again from your MCP client.')

        if not hmac.compare_digest(password.encode(), self._owner_password.encode()):
            count = await self._repository.record_failed_attempt(
                attempt_key, ttl=self._oauth.consent_lockout_seconds)
            logger.warning(
                'MCP OAuth consent rejected: client_id=%s attempt=%s', pending['client_id'], count)
            raise ConsentError('Incorrect owner password.')

        # Correct: consume the pending request so the page cannot be replayed.
        pending = await self._repository.take_pending(txn_id)
        if pending is None:  # pragma: no cover - lost a race with another tab
            raise ConsentError('This authorization request was already completed.')
        await self._repository.clear_failed_attempts(attempt_key)

        scopes = [self._config.read_scope]
        if allow_write:
            scopes.append(self._config.write_scope)

        code = secrets.token_urlsafe(32)
        await self._repository.put_code(
            code,
            {
                'client_id': pending['client_id'],
                'redirect_uri': pending['redirect_uri'],
                'redirect_uri_provided_explicitly': pending['redirect_uri_provided_explicitly'],
                'code_challenge': pending['code_challenge'],
                'scopes': scopes,
                'resource': pending.get('resource'),
                'expires_at': time.time() + self._oauth.authorization_code_ttl_seconds,
            },
            ttl=self._oauth.authorization_code_ttl_seconds,
        )

        logger.info(
            'MCP OAuth consent granted: client_id=%s scopes=%s',
            pending['client_id'], scopes)
        return construct_redirect_uri(pending['redirect_uri'], code=code, state=pending.get('state'))

    async def deny_consent(self, txn_id: str) -> Optional[str]:
        """Abandon an authorization and send the client an ``access_denied``."""
        pending = await self._repository.take_pending(txn_id)
        if pending is None:
            return None
        logger.info('MCP OAuth consent denied: client_id=%s', pending['client_id'])
        return construct_redirect_uri(
            pending['redirect_uri'], error='access_denied', state=pending.get('state'))

    # -- Authorization code exchange ---------------------------------------

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> Optional[AuthorizationCode]:
        record = await self._repository.peek_code(authorization_code)
        if record is None or record['client_id'] != client.client_id:
            return None
        return AuthorizationCode(
            code=authorization_code,
            scopes=record['scopes'],
            expires_at=record['expires_at'],
            client_id=record['client_id'],
            code_challenge=record['code_challenge'],
            redirect_uri=record['redirect_uri'],
            redirect_uri_provided_explicitly=record['redirect_uri_provided_explicitly'],
            resource=record.get('resource'),
            subject=record.get('subject'),
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        # Consume the code here, not at load time: the SDK verifies PKCE
        # between the two, and a code that fails verification must not have
        # been silently spent.
        consumed = await self._repository.take_code(authorization_code.code)
        if consumed is None:
            # TokenError, not ValueError: the SDK turns only TokenError into an
            # RFC 6749 error response; anything else is a 500.
            raise TokenError('invalid_grant', 'Authorization code has already been used or has expired.')

        return await self._issue_tokens(
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            resource=authorization_code.resource,
            subject=authorization_code.subject,
        )

    # -- Refresh -----------------------------------------------------------

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> Optional[RefreshToken]:
        record = await self._repository.get_refresh_token(refresh_token)
        if record is None or record['client_id'] != client.client_id:
            return None
        if record.get('expires_at') and record['expires_at'] < time.time():
            await self._repository.delete_refresh_token(refresh_token)
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=record['client_id'],
            scopes=record['scopes'],
            expires_at=int(record['expires_at']) if record.get('expires_at') else None,
            resource=record.get('resource'),
            subject=record.get('subject'),
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """Rotate the refresh token along with the access token.

        The old one is deleted before the new pair is returned, so a replayed
        refresh finds nothing. A refresh may narrow the scopes, never widen
        them -- the SDK enforces that before calling here.
        """
        await self._repository.delete_refresh_token(refresh_token.token)
        return await self._issue_tokens(
            client_id=client.client_id,
            scopes=scopes or refresh_token.scopes,
            resource=refresh_token.resource,
            subject=refresh_token.subject,
        )

    # -- Access tokens -----------------------------------------------------

    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        record = await self._repository.get_access_token(token)
        if record is None:
            return None
        if record.get('expires_at') and record['expires_at'] < time.time():
            await self._repository.delete_access_token(token)
            return None
        return AccessToken(
            token=token,
            client_id=record['client_id'],
            scopes=record['scopes'],
            expires_at=int(record['expires_at']) if record.get('expires_at') else None,
            resource=record.get('resource'),
            subject=record.get('subject'),
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, AccessToken):
            await self._repository.delete_access_token(token.token)
        else:
            await self._repository.delete_refresh_token(token.token)
        logger.info('MCP OAuth token revoked: client_id=%s', token.client_id)

    async def _issue_tokens(
        self,
        *,
        client_id: str,
        scopes: list[str],
        resource: Optional[str],
        subject: Optional[str],
    ) -> OAuthToken:
        now = int(time.time())
        access_token = secrets.token_urlsafe(48)
        refresh_token = secrets.token_urlsafe(48)
        access_ttl = self._oauth.access_token_ttl_seconds

        await self._repository.put_access_token(
            access_token,
            {
                'client_id': client_id,
                'scopes': scopes,
                'resource': resource,
                'subject': subject,
                'expires_at': now + access_ttl,
            },
            ttl=access_ttl,
        )
        await self._repository.put_refresh_token(
            refresh_token,
            {
                'client_id': client_id,
                'scopes': scopes,
                'resource': resource,
                'subject': subject,
                # Whole seconds: RefreshToken.expires_at is typed int.
                'expires_at': now + self._oauth.refresh_token_ttl_seconds,
            },
        )

        return OAuthToken(
            access_token=access_token,
            token_type='Bearer',
            expires_in=access_ttl,
            scope=' '.join(scopes),
            refresh_token=refresh_token,
        )


class ContainerMcpAuthProvider:
    """``McpAuthService`` resolved from the DI container on each use.

    The MCP blueprint is built when ``app.py`` is imported, but the container
    is built inside the serving loop, because its Mongo and Redis clients bind
    to the loop they are first used on. The SDK's OAuth handlers only call the
    provider while serving, so this stands in for the service until then.
    """

    def __getattr__(self, name: str) -> Any:
        from utilities.provider import ContainerProvider
        return getattr(ContainerProvider.get_service_provider().resolve(McpAuthService), name)


def _comparable(url: str) -> str:
    """A URL with case-insensitive parts lowered and any trailing slash dropped."""
    parts = urlsplit(url.strip())
    return f'{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path.rstrip("/")}'
