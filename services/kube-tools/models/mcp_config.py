"""Typed settings for the journal MCP endpoint and its OAuth authorization server.

Read from the ``mcp`` section of config.json. The section is optional: without
it (or with ``enabled: false``) no MCP or OAuth routes are registered and the
service runs exactly as before.

Ported from plaid-sync's ``lib/mcp_config.py``. The difference is where the
endpoint lives: SpendYak and oura-sync each have a host of their own and serve
OAuth from its root, while this one is reached through the shared API gateway
(``api.dan-leonard.com``). So both the MCP endpoint (``path``) and the
authorization server (``issuer_path``) sit under ``/api/tools/journal``, and
the gateway maps those paths through unchanged.

Two names, deliberately separate:

* ``server_name`` is the machine identifier -- the MCP server name, the prefix
  on every tool and scope, and the request-state audience. Changing it renames
  every tool and invalidates every issued token's scopes, so pick it once.
* ``display_name`` is what a model and a person read: the server title, the
  instructions, and the consent page.
"""

from __future__ import annotations

from typing import Any, List, Mapping, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator, model_validator


def _normalise_path(value: str, name: str, *, allow_root: bool) -> str:
    path = '/' + value.strip().strip('/')
    if path == '/':
        if not allow_root:
            raise ValueError(f'mcp.{name} must not be the application root')
        return ''
    return path


class _Section(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class McpOAuthConfig(_Section):
    """``mcp.oauth``: this service as an OAuth 2.1 authorization server."""

    # Typed on the consent screen to approve an authorization, as in oura-sync.
    # Compared directly, so its entropy is its strength -- generate it like an
    # API key. Required when MCP is enabled.
    owner_password: Optional[SecretStr] = None
    access_token_ttl_seconds: int = Field(default=3600, ge=300, le=86400)
    refresh_token_ttl_seconds: int = Field(default=2592000, ge=3600)
    authorization_code_ttl_seconds: int = Field(default=60, ge=30, le=600)
    consent_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    consent_max_attempts: int = Field(default=5, ge=1, le=50)
    consent_lockout_seconds: int = Field(default=900, ge=60)


class McpConfig(_Section):
    """``mcp``: the MCP endpoint, its names and its auth."""

    enabled: bool = False

    # Public paths, identical on the gateway and on this service: the gateway
    # mapping passes them through unchanged, so the URLs the service builds
    # are the URLs clients reach.
    path: str = '/api/tools/journal/mcp'
    # The authorization server's path. /authorize, /token, /register, /revoke
    # and the consent page sit under it; its RFC 8414 metadata is served at
    # /.well-known/oauth-authorization-server{issuer_path}.
    issuer_path: str = '/api/tools/journal/oauth'

    server_name: str = 'journal'
    display_name: str = 'Journal'

    # Entries are stored with UTC timestamps; tools read and report dates as
    # days in this zone, so an entry recorded late in the evening belongs to
    # that evening rather than to the next UTC day.
    time_zone: str = 'America/New_York'

    # Public origin, e.g. api.dan-leonard.com. Every URL in the OAuth discovery
    # documents is built from it, and clients follow what they are told, so it
    # must be the host they actually reach.
    public_host: str = ''
    # Only ever http for local development; an http issuer would have OAuth
    # clients sending tokens in the clear.
    public_scheme: str = 'https'
    # Used only for the local fallback of `public_base_url`.
    port: int = 5086

    # Optional static bearer key for clients configured by header (Claude
    # Code). OAuth is always on; this is accepted alongside it.
    api_key: Optional[SecretStr] = None

    # Seal MCP request state (elicitation round trips) so any worker can open
    # what another issued. Empty means a key generated per process. Each at
    # least 32 characters.
    request_state_secrets: List[SecretStr] = Field(default_factory=list)

    # Extra Host header values the transport accepts. Every entry widens the
    # DNS-rebinding allowlist. Behind the gateway this must include the
    # cluster-internal service name: the gateway replaces Host with it.
    extra_allowed_hosts: List[str] = Field(default_factory=list)

    oauth: McpOAuthConfig = Field(default_factory=McpOAuthConfig)

    @field_validator('path')
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return _normalise_path(value, 'path', allow_root=False)

    @field_validator('issuer_path')
    @classmethod
    def _validate_issuer_path(cls, value: str) -> str:
        return _normalise_path(value, 'issuer_path', allow_root=True)

    @field_validator('server_name')
    @classmethod
    def _validate_server_name(cls, value: str) -> str:
        name = value.strip().lower()
        if not name or not name.replace('_', '').isalnum():
            raise ValueError('mcp.server_name must be letters, digits and underscores')
        return name

    @field_validator('time_zone')
    @classmethod
    def _validate_time_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f'mcp.time_zone must be an IANA zone name, got {value!r}') from None
        return value

    @field_validator('public_scheme')
    @classmethod
    def _validate_scheme(cls, value: str) -> str:
        scheme = value.strip().lower()
        if scheme not in ('http', 'https'):
            raise ValueError(f'mcp.public_scheme must be http or https, got {value!r}')
        return scheme

    @field_validator('public_host')
    @classmethod
    def _strip_scheme(cls, value: str) -> str:
        return value.strip().removeprefix('https://').removeprefix('http://').rstrip('/')

    @field_validator('request_state_secrets')
    @classmethod
    def _validate_request_state_secrets(cls, value: List[SecretStr]) -> List[SecretStr]:
        if any(len(secret.get_secret_value()) < 32 for secret in value):
            raise ValueError('mcp.request_state_secrets must each be at least 32 characters')
        return value

    @field_validator('extra_allowed_hosts')
    @classmethod
    def _strip_hosts(cls, value: List[str]) -> List[str]:
        return [host.strip() for host in value if host.strip()]

    @field_validator('api_key')
    @classmethod
    def _validate_api_key(cls, value: Optional[SecretStr]) -> Optional[SecretStr]:
        if value is not None and not value.get_secret_value().strip():
            raise ValueError('mcp.api_key must not be empty; remove it to use OAuth only')
        return value

    @model_validator(mode='after')
    def _require_owner_password(self) -> 'McpConfig':
        password = self.oauth.owner_password
        if self.enabled and (password is None or not password.get_secret_value().strip()):
            raise ValueError(
                'mcp.oauth.owner_password must be set when mcp.enabled is true; '
                'without it no authorization could ever be approved')
        return self

    @model_validator(mode='after')
    def _paths_must_not_overlap(self) -> 'McpConfig':
        # The OAuth routes are app-level rules; under the MCP path they would
        # be shadowed by, or shadow, the transport.
        if self.issuer_path and (self.issuer_path == self.path or self.issuer_path.startswith(f'{self.path}/')):
            raise ValueError('mcp.issuer_path must not be the MCP path or sit under it')
        return self

    @classmethod
    def from_section(cls, section: Optional[Mapping[str, Any]]) -> 'McpConfig':
        """Validate the ``mcp`` section, reporting problems without their values.

        A plain ``ValidationError`` repeats the input it rejected, which here
        includes ``api_key`` and ``owner_password`` -- and it lands in the
        startup logs.
        """
        try:
            return cls.model_validate(section or {})
        except ValidationError as exc:
            problems = '; '.join(
                f"{'.'.join(str(part) for part in error['loc']) or 'mcp'}: {error['msg']}"
                for error in exc.errors(include_input=False, include_url=False))
            raise ValueError(f'Invalid mcp configuration: {problems}') from None

    @property
    def public_base_url(self) -> str:
        """The externally reachable origin."""
        if self.public_host:
            return f'{self.public_scheme}://{self.public_host}'
        return f'http://localhost:{self.port}'

    @property
    def resource_url(self) -> str:
        """The MCP endpoint's public URL: the resource every token is bound to."""
        return f'{self.public_base_url}{self.path}'

    @property
    def issuer_url(self) -> str:
        return f'{self.public_base_url}{self.issuer_path}'

    @property
    def consent_path(self) -> str:
        return f'{self.issuer_path}/consent'

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.time_zone)

    @property
    def read_scope(self) -> str:
        return f'{self.server_name}:read'

    @property
    def write_scope(self) -> str:
        return f'{self.server_name}:write'

    def tool_name(self, name: str) -> str:
        return f'{self.server_name}_{name}'

    def allowed_hosts(self) -> List[str]:
        """Host header values the MCP transport will accept."""
        hosts = ['127.0.0.1:*', 'localhost:*', '[::1]:*', '127.0.0.1', 'localhost']
        for host in [self.public_host, *self.extra_allowed_hosts]:
            if host:
                hosts.extend([host, f'{host}:*'])
        return hosts

    def allowed_origins(self) -> List[str]:
        origins = ['http://127.0.0.1:*', 'http://localhost:*', 'http://[::1]:*']
        for host in [self.public_host, *self.extra_allowed_hosts]:
            if host:
                origins.extend([f'https://{host}', f'http://{host}'])
        return origins
