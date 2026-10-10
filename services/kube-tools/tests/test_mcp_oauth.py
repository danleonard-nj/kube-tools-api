"""Journal MCP OAuth: consent, code and token lifecycle, and the HTTP surface.

Ported from plaid-sync's ``tests/test_mcp_oauth.py``. The authorization server
is exercised against an in-memory store; the full flow (discovery -> register
-> authorize -> consent -> token -> MCP call) runs over a Quart app carrying the
real consent page and MCP blueprint, at the gateway paths
(``/api/tools/journal/...``) the service actually serves.
"""

import base64
import hashlib
import json
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from mcp.server.auth.provider import AuthorizationParams, AuthorizeError, TokenError
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl
from quart import Quart

import data.mcp_oauth_repository as oauth_repository
from mcp_server.app import create_mcp_blueprint
from models.mcp_config import McpConfig
from routes.mcp_consent import create_mcp_consent_blueprint
from services.journal_service import JournalService
from services.mcp_auth_service import ConsentError, ConsentLockedOut, McpAuthService
from tests.mcp_fakes import FakeCacheClient, FakeOAuthRepository, FakeProvider
from utilities.provider import ContainerProvider

OWNER_PW = 'owner-secret-9WqLp2Zn4TxKb7Rd'
API_KEY = 'k' * 40
GATEWAY_HOST = 'kube-tools.kube-tools.svc.cluster.local'
CONFIG = McpConfig(
    enabled=True,
    api_key=API_KEY,
    extra_allowed_hosts=[GATEWAY_HOST],
    oauth={'owner_password': OWNER_PW},
)
READ = CONFIG.read_scope
WRITE = CONFIG.write_scope
BASE = 'http://localhost:5086'
ENDPOINT = f'{BASE}/api/tools/journal/mcp'
ISSUER = '/api/tools/journal/oauth'
CONSENT = f'{ISSUER}/consent'
REDIRECT = 'https://claude.ai/api/mcp/auth_callback'


@pytest.fixture
def store():
    return FakeOAuthRepository()


@pytest.fixture
def service(store):
    return McpAuthService(store, CONFIG)


def make_client(client_id='client-1'):
    return OAuthClientInformationFull(
        client_id=client_id,
        client_name='Claude',
        redirect_uris=[AnyUrl(REDIRECT)],
        grant_types=['authorization_code', 'refresh_token'],
        response_types=['code'],
        scope=f'{READ} {WRITE}',
    )


def make_params(resource=None, state='st-1'):
    return AuthorizationParams(
        state=state,
        scopes=[READ, WRITE],
        code_challenge='challenge',
        redirect_uri=AnyUrl(REDIRECT),
        redirect_uri_provided_explicitly=True,
        resource=resource,
    )


def txn_of(consent_url):
    return parse_qs(urlsplit(consent_url).query)['txn'][0]


async def pending_txn(service, **params):
    client = make_client()
    await service.register_client(client)
    return client, txn_of(await service.authorize(client, make_params(**params)))


async def approve(service, txn, password=OWNER_PW, allow_write=False):
    return await service.approve_consent(txn, password=password, attempt_key=txn, allow_write=allow_write)


async def authorized_code(service, *, resource=None, allow_write=False):
    client, txn = await pending_txn(service, resource=resource)
    redirect = await approve(service, txn, allow_write=allow_write)
    code = parse_qs(urlsplit(redirect).query)['code'][0]
    return client, await service.load_authorization_code(client, code)


# -- Configuration ---------------------------------------------------------------


def test_enabling_mcp_requires_an_owner_password():
    with pytest.raises(ValueError, match='owner_password'):
        McpConfig.from_section({'enabled': True})
    assert McpConfig.from_section(None).enabled is False


def test_config_errors_never_repeat_secret_values():
    # The app builds the config through from_section at import; its error ends
    # up in the startup logs, so it must name the problem without the values.
    secret = 'live-key-' + 'x' * 40
    with pytest.raises(ValueError) as excinfo:
        McpConfig.from_section({'enabled': True, 'api_key': secret, 'path': '/'})
    message = str(excinfo.value)
    assert 'owner_password' in message or 'path' in message
    assert secret not in message and 'live-key' not in message


def test_defaults_are_the_gateway_layout():
    config = McpConfig(public_host='https://api.dan-leonard.com/')
    assert config.resource_url == 'https://api.dan-leonard.com/api/tools/journal/mcp'
    assert config.issuer_url == 'https://api.dan-leonard.com/api/tools/journal/oauth'
    assert config.consent_path == '/api/tools/journal/oauth/consent'
    assert config.tool_name('list_tags') == 'journal_list_tags'


def test_issuer_cannot_sit_under_the_mcp_path():
    with pytest.raises(ValueError, match='issuer_path'):
        McpConfig.from_section({'issuer_path': '/api/tools/journal/mcp/oauth'})


# -- Consent -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authorize_parks_the_request_and_issues_nothing(service, store):
    url = await service.authorize(make_client(), make_params())
    assert url.startswith(f'{BASE}{CONSENT}?txn=')
    assert not store.codes and not store.access


@pytest.mark.asyncio
async def test_wrong_password_is_refused_and_the_request_survives(service, store):
    _, txn = await pending_txn(service)
    with pytest.raises(ConsentError, match='Incorrect owner password'):
        await approve(service, txn, password='wrong')
    assert txn in store.pending and not store.codes
    # The right password still works afterwards.
    await approve(service, txn)
    assert store.codes


@pytest.mark.asyncio
async def test_repeated_wrong_passwords_lock_out(service):
    _, txn = await pending_txn(service)
    for _ in range(CONFIG.oauth.consent_max_attempts):
        with pytest.raises(ConsentError):
            await approve(service, txn, password='wrong')
    with pytest.raises(ConsentLockedOut):
        await approve(service, txn)


@pytest.mark.asyncio
async def test_approval_is_read_only_unless_changes_are_allowed(service):
    # The client asked for both scopes; only the consent page grants write.
    _, read_only = await authorized_code(service)
    _, read_write = await authorized_code(service, allow_write=True)
    assert read_only.scopes == [READ]
    assert read_write.scopes == [READ, WRITE]


@pytest.mark.asyncio
@pytest.mark.parametrize('requested', [
    None,
    ENDPOINT,
    f'{ENDPOINT}/',
    'http://LOCALHOST:5086',
    f'{BASE}/',
])
async def test_endpoint_or_origin_resource_binds_to_the_endpoint(service, requested):
    # Clients differ in which form they send.
    _, code = await authorized_code(service, resource=requested)
    assert code.resource == ENDPOINT


@pytest.mark.asyncio
@pytest.mark.parametrize('foreign', [
    # Same gateway host, someone else's endpoint: the shared origin must not
    # make a token for another service's MCP path acceptable.
    f'{BASE}/api/oura/mcp',
    f'{BASE}/api/tools/journal',
    'https://oura.dan-leonard.com/mcp',
])
async def test_foreign_resource_is_refused(service, store, foreign):
    with pytest.raises(AuthorizeError) as excinfo:
        await service.authorize(make_client(), make_params(resource=foreign))
    assert excinfo.value.error == 'invalid_target'
    assert not store.pending


@pytest.mark.asyncio
async def test_deny_returns_access_denied_and_consumes_the_request(service, store):
    _, txn = await pending_txn(service, state='abc')
    redirect = await service.deny_consent(txn)
    query = parse_qs(urlsplit(redirect).query)
    assert query['error'] == ['access_denied'] and query['state'] == ['abc']
    assert not store.pending


@pytest.mark.asyncio
async def test_consent_cannot_be_replayed(service):
    _, txn = await pending_txn(service)
    await approve(service, txn)
    with pytest.raises(ConsentError, match='expired or was already completed'):
        await approve(service, txn)


# -- Tokens ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_code_is_single_use(service):
    client, code = await authorized_code(service)
    await service.exchange_authorization_code(client, code)
    with pytest.raises(TokenError) as excinfo:
        await service.exchange_authorization_code(client, code)
    assert excinfo.value.error == 'invalid_grant'


@pytest.mark.asyncio
async def test_code_belongs_to_its_client(service):
    client, code = await authorized_code(service)
    assert await service.load_authorization_code(make_client(client_id='other'), code.code) is None


@pytest.mark.asyncio
async def test_tokens_carry_scopes_and_resource(service):
    client, code = await authorized_code(service, allow_write=True)
    tokens = await service.exchange_authorization_code(client, code)
    access = await service.load_access_token(tokens.access_token)
    assert access.scopes == [READ, WRITE]
    assert access.resource == ENDPOINT


@pytest.mark.asyncio
async def test_refresh_rotates_and_keeps_the_resource(service):
    client, code = await authorized_code(service)
    first = await service.exchange_authorization_code(client, code)
    refresh = await service.load_refresh_token(client, first.refresh_token)

    second = await service.exchange_refresh_token(client, refresh, [])
    assert await service.load_refresh_token(client, first.refresh_token) is None
    access = await service.load_access_token(second.access_token)
    assert access.resource == ENDPOINT


@pytest.mark.asyncio
async def test_expired_access_token_is_refused(service, store):
    client, code = await authorized_code(service)
    tokens = await service.exchange_authorization_code(client, code)
    store.access[tokens.access_token]['expires_at'] = int(time.time()) - 1
    assert await service.load_access_token(tokens.access_token) is None


@pytest.mark.asyncio
async def test_revoke(service):
    client, code = await authorized_code(service)
    tokens = await service.exchange_authorization_code(client, code)
    await service.revoke_token(await service.load_access_token(tokens.access_token))
    assert await service.load_access_token(tokens.access_token) is None


# -- Storage -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_keys_are_this_services_own_and_hold_no_raw_tokens():
    # oura-sync uses `mcp:oauth:*` and plaid-sync `spendyak:mcp:oauth:*`; a
    # shared prefix on the same Redis would make each accept the other's tokens.
    for prefix in (oauth_repository.PENDING_PREFIX, oauth_repository.CODE_PREFIX,
                   oauth_repository.ACCESS_PREFIX, oauth_repository.ATTEMPTS_PREFIX):
        assert prefix.startswith('journal:mcp:oauth:')

    cache = FakeCacheClient()
    repository = oauth_repository.McpOAuthRepository(client=None, cache_client=cache)
    await repository.put_access_token('raw-token', {'client_id': 'c'}, ttl=60)
    await repository.put_code('raw-code', {'client_id': 'c'}, ttl=60)
    assert not any('raw-' in key for key in cache.client.data)
    assert await repository.get_access_token('raw-token') == {'client_id': 'c'}
    assert await repository.take_code('raw-code') == {'client_id': 'c'}
    assert await repository.take_code('raw-code') is None


# -- Over HTTP -----------------------------------------------------------------------


class FakeJournalService:
    async def list_tag_counts(self):
        return [{'tag': 'work', 'entry_count': 4}, {'tag': 'family', 'entry_count': 2}]


@pytest.fixture
def app(monkeypatch, service):
    provider = FakeProvider({
        McpConfig: CONFIG,
        McpAuthService: service,
        JournalService: FakeJournalService(),
    })
    # The consent page and the tools resolve from the container per request,
    # as they do in the app.
    monkeypatch.setattr(ContainerProvider, 'get_service_provider', lambda *args: provider)

    app = Quart(__name__)
    app.register_blueprint(create_mcp_blueprint(CONFIG))
    app.register_blueprint(create_mcp_consent_blueprint(CONFIG))
    return app


async def register(client):
    response = await client.post(f'{ISSUER}/register', json={
        'redirect_uris': [REDIRECT], 'client_name': 'Claude', 'token_endpoint_auth_method': 'none',
        'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code'],
    })
    assert response.status_code == 201
    return await response.get_json()


async def authorize(client, client_id, verifier):
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    response = await client.get(f'{ISSUER}/authorize?' + urlencode({
        'response_type': 'code', 'client_id': client_id, 'redirect_uri': REDIRECT,
        'code_challenge': challenge, 'code_challenge_method': 'S256', 'state': 'st',
        'scope': f'{READ} {WRITE}', 'resource': ENDPOINT,
    }))
    assert response.status_code == 302
    location = urlsplit(response.headers['Location'])
    return f'{location.path}?{location.query}'


async def connect(client, allow_write=False):
    """Run the whole flow a connector runs; return the token response."""
    registered = await register(client)
    verifier = secrets.token_urlsafe(48)
    consent_path = await authorize(client, registered['client_id'], verifier)
    assert consent_path.startswith(f'{CONSENT}?')
    assert (await client.get(consent_path)).status_code == 200

    form = {'txn': txn_of(consent_path), 'password': OWNER_PW, 'action': 'approve'}
    if allow_write:
        form['allow_write'] = 'on'
    response = await client.post(CONSENT, form=form)
    code = parse_qs(urlsplit(response.headers['Location']).query)['code'][0]
    response = await client.post(f'{ISSUER}/token', form={
        'grant_type': 'authorization_code', 'code': code, 'redirect_uri': REDIRECT,
        'client_id': registered['client_id'], 'code_verifier': verifier,
    })
    assert response.status_code == 200
    return await response.get_json()


async def mcp_call(client, token, method, params=None, headers=None):
    return await client.post('/api/tools/journal/mcp', headers={
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json, text/event-stream',
        'MCP-Protocol-Version': '2025-11-25',
        **(headers or {}),
    }, json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}})


def sse_result(body):
    data = [line[len('data: '):] for line in body.splitlines() if line.startswith('data: ')]
    return json.loads(data[-1])


@pytest.mark.asyncio
async def test_unauthenticated_mcp_points_to_discovery_under_the_gateway_paths(app):
    async with app.test_app() as test_app:
        client = test_app.test_client()
        response = await client.post('/api/tools/journal/mcp', json={})
        assert response.status_code == 401
        resource_metadata = f'{BASE}/.well-known/oauth-protected-resource/api/tools/journal/mcp'
        assert f'resource_metadata="{resource_metadata}"' in response.headers['WWW-Authenticate']

        metadata = await (await client.get(urlsplit(resource_metadata).path)).get_json()
        assert metadata['resource'] == ENDPOINT
        assert metadata['authorization_servers'] == [f'{BASE}{ISSUER}']
        assert metadata['resource_name'] == CONFIG.display_name

        # RFC 8414: the well-known segment goes before the issuer's path.
        server = await (await client.get(f'/.well-known/oauth-authorization-server{ISSUER}')).get_json()
        assert server['issuer'] == f'{BASE}{ISSUER}'
        assert server['authorization_endpoint'] == f'{BASE}{ISSUER}/authorize'
        assert server['token_endpoint'] == f'{BASE}{ISSUER}/token'
        assert server['registration_endpoint'] == f'{BASE}{ISSUER}/register'
        assert server['revocation_endpoint'] == f'{BASE}{ISSUER}/revoke'
        assert 'S256' in server['code_challenge_methods_supported']

        # Nothing is claimed at the shared host's root.
        assert (await client.get('/.well-known/oauth-authorization-server')).status_code == 404
        assert (await client.post('/register', json={})).status_code == 404


@pytest.mark.asyncio
async def test_full_flow_issues_a_working_read_only_token(app):
    async with app.test_app() as test_app:
        client = test_app.test_client()
        tokens = await connect(client)
        assert tokens['scope'] == READ

        response = await mcp_call(client, tokens['access_token'], 'tools/list')
        assert response.status_code == 200
        names = [tool['name'] for tool in sse_result(await response.get_data(as_text=True))['result']['tools']]
        assert 'journal_list_tags' in names

        response = await mcp_call(client, tokens['access_token'], 'tools/call',
                                  {'name': 'journal_list_tags', 'arguments': {}})
        result = sse_result(await response.get_data(as_text=True))['result']
        assert not result.get('isError')
        assert result['structuredContent'] == {'tags': [
            {'tag': 'work', 'entry_count': 4}, {'tag': 'family', 'entry_count': 2}]}


@pytest.mark.asyncio
async def test_ticking_allow_changes_grants_write(app):
    async with app.test_app() as test_app:
        tokens = await connect(test_app.test_client(), allow_write=True)
        assert tokens['scope'] == f'{READ} {WRITE}'


@pytest.mark.asyncio
async def test_requests_relayed_by_the_gateway_are_accepted(app):
    # The gateway replaces Host with the cluster-internal service name.
    async with app.test_app() as test_app:
        response = await mcp_call(test_app.test_client(), API_KEY, 'tools/list',
                                  headers={'Host': GATEWAY_HOST})
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_unknown_hosts_are_rejected(app):
    async with app.test_app() as test_app:
        response = await mcp_call(test_app.test_client(), API_KEY, 'tools/list',
                                  headers={'Host': 'attacker.example'})
        assert response.status_code == 421


@pytest.mark.asyncio
async def test_wrong_password_on_the_page_issues_nothing(app, store):
    async with app.test_app() as test_app:
        client = test_app.test_client()
        registered = await register(client)
        consent_path = await authorize(client, registered['client_id'], 'v' * 50)
        response = await client.post(CONSENT, form={
            'txn': txn_of(consent_path), 'password': 'wrong', 'action': 'approve'})
        assert response.status_code == 401
        assert 'Incorrect owner password' in await response.get_data(as_text=True)
        assert not store.codes


@pytest.mark.asyncio
async def test_deny_needs_no_password(app):
    async with app.test_app() as test_app:
        client = test_app.test_client()
        registered = await register(client)
        consent_path = await authorize(client, registered['client_id'], 'v' * 50)
        response = await client.post(CONSENT, form={'txn': txn_of(consent_path), 'action': 'deny'})
        assert response.status_code == 302
        assert 'error=access_denied' in response.headers['Location']


@pytest.mark.asyncio
async def test_api_key_is_accepted_alongside_oauth(app):
    async with app.test_app() as test_app:
        response = await mcp_call(test_app.test_client(), API_KEY, 'tools/list')
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_foreign_token_is_rejected(app):
    async with app.test_app() as test_app:
        response = await mcp_call(test_app.test_client(), 'some-other-services-token', 'tools/list')
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_consent_page_refuses_framing_and_shows_the_redirect_host(app):
    async with app.test_app() as test_app:
        client = test_app.test_client()
        registered = await register(client)
        response = await client.get(await authorize(client, registered['client_id'], 'v' * 50))
        assert response.headers['X-Frame-Options'] == 'DENY'
        assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
        body = await response.get_data(as_text=True)
        assert '<strong>claude.ai</strong>' in body
        assert f'action="{CONSENT}"' in body
