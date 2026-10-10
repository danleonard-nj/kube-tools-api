"""The journal MCP server: an ``MCPServer`` served by framework's MCPBlueprint.

Ported from plaid-sync's ``mcp_server/app.py``. ``create_mcp_blueprint`` builds
the server, registers the tools, and hosts the OAuth authorization server
(``with_oauth``) under ``mcp.issuer_path``: ``/authorize``, ``/token``,
``/register``, ``/revoke`` and the RFC 8414/9728 discovery documents, backed by
``McpAuthService``. The static ``mcp.api_key``, when configured, is accepted
alongside OAuth for clients that send a header.

Everything is reached through the API gateway, whose mapping passes these
paths through unchanged (``api-gateway/services/gateway/mapping/kube-tools.json``).

The blueprint runs the SDK's Streamable HTTP session manager for as long as
Quart is serving, so ``app.py`` has nothing MCP-specific to do beyond
registering it.

Moving to a shared authorization server later means replacing ``with_oauth``
with ``with_bearer(token_verifier=..., authorization_servers=[...])``; the tools
only ever read the caller from ``get_access_token()``.
"""

from __future__ import annotations

from typing import Optional

from framework.mcp import MCPBlueprint, shared_request_state
from mcp.server.auth.provider import OAuthAuthorizationServerProvider
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from mcp_server.tools import register_tools
from models.mcp_config import McpConfig
from services.mcp_auth_service import ContainerMcpAuthProvider

INSTRUCTIONS = """\
Access to the user's {display_name}: personal journal entries, mostly dictated
by voice and transcribed, each with an automatic summary, mood, themes, people,
action items and tags.

Entries are written in the first person by the user. Quote them sparingly and
only when the question calls for their own words.

Start with the search tool to find entries (by date, tags or text) and the
stats tool for questions about a period -- mood, recurring themes, people,
open action items. Read single entries with get_entry. Use the tag tool to
find valid tags before filtering on them.

Dates are YYYY-MM-DD days in the journal's time zone ({time_zone}), and ranges
are inclusive.

The write tools add entries and change titles and tags, only when the user
asks, and only when this connection was granted permission to make changes.
Nothing can be deleted or have its text rewritten through this connection.

This is private, personal and sometimes health-related writing. Do not repeat
it beyond what answering the question requires.\
"""

VERSION = '1.0.0'


def create_mcp_server(config: McpConfig) -> MCPServer:
    request_state_security = None
    if config.request_state_secrets:
        request_state_security = shared_request_state(
            [secret.get_secret_value() for secret in config.request_state_secrets],
            audience=config.server_name,
        )

    server = MCPServer(
        name=config.server_name,
        title=config.display_name,
        instructions=INSTRUCTIONS.format(display_name=config.display_name, time_zone=config.time_zone),
        version=VERSION,
        request_state_security=request_state_security,
    )
    register_tools(server, config)
    return server


def create_mcp_blueprint(
    config: McpConfig,
    auth_provider: Optional[OAuthAuthorizationServerProvider] = None,
) -> MCPBlueprint:
    """Build the blueprint serving MCP on ``config.path``.

    ``auth_provider`` defaults to the container's ``McpAuthService``, resolved
    on first use; tests pass a service directly.

    ``transport_security`` -- the SDK's DNS-rebinding guard defaults to a
    localhost-only allowlist. Requests arrive from the gateway with ``Host``
    set to this service's cluster name, so that has to be in
    ``mcp.extra_allowed_hosts`` or every request is rejected with a 421.

    ``stateless_http`` -- no session state lives in the process, so either
    uvicorn worker, a restart or a second replica needs nothing sticky.
    """
    blueprint = MCPBlueprint(
        'mcp',
        __name__,
        server=create_mcp_server(config),
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=config.allowed_hosts(),
            allowed_origins=config.allowed_origins(),
        ),
    )

    # Dynamic client registration is on because Claude and ChatGPT cannot be
    # pre-registered. Registration alone grants nothing: every authorization
    # still has to be approved on the consent page with the owner password.
    blueprint.with_oauth(
        config.path,
        provider=auth_provider or ContainerMcpAuthProvider(),  # type: ignore[arg-type]
        issuer_url=config.issuer_url,
        required_scopes=[config.read_scope],
        # A client registered without a scope gets both: registration only bounds
        # what a client may ask for. Whether a token can write is decided on the
        # consent page, where it is opt-in.
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=[config.read_scope, config.write_scope],
            default_scopes=[config.read_scope, config.write_scope],
        ),
        revocation_options=RevocationOptions(enabled=True),
        resource_server_url=config.resource_url,
        resource_name=config.display_name,
        api_key=config.api_key.get_secret_value() if config.api_key else None,
        validate_resource=True,
        realm=config.server_name,
    )
    return blueprint
