# Journal MCP server

kube-tools serves a [Model Context Protocol](https://modelcontextprotocol.io)
endpoint over the journal, so an MCP client (Claude's custom connectors, Claude
Code, ChatGPT) can answer questions about journal entries.

It is ported from plaid-sync's console MCP (SpendYak), itself modelled on
oura-sync: framework's `MCPBlueprint` serves the SDK's Streamable HTTP transport
from a Quart route, and the service hosts its own OAuth authorization server.
The one structural difference is that this one is reached **through the API
gateway** rather than on a host of its own, so everything lives under
`/api/tools/journal` on `api.dan-leonard.com`.

```
mcp_server/app.py              MCPServer + MCPBlueprint, OAuth wiring, model instructions
mcp_server/tools/              one module per area (+ common.py runner)
mcp_server/models.py           result models -- also the field allowlist
models/mcp_config.py           the `mcp` config section
services/mcp_auth_service.py   OAuth authorization server (SDK provider contract)
data/mcp_oauth_repository.py   clients/refresh tokens in Mongo, codes/access tokens in Redis
routes/mcp_consent.py          the consent page
```

## Tools

| Tool | Scope | What it does |
| --- | --- | --- |
| `journal_search_entries` | read | Entries newest first as short rows; filter by date range, tags (all must match) and literal text across title, transcripts and summaries, with a snippet; paged |
| `journal_get_entry` | read | One entry: transcript (cleaned when available), analysis, tags, attachment names |
| `journal_stats` | read | Over a range (default 30 days): entry and day counts, streaks, mood average and per day, top themes/people/stressors, action items and open loops with their entries. No LLM call |
| `journal_list_tags` | read | Every tag with its entry count |
| `journal_create_entry` | write | New text entry; title generated unless given; queued for analysis |
| `journal_set_title` | write | Sets a manual title, which auto-titling never replaces |
| `journal_update_tags` | write | Add/remove tags; reports added tags not used anywhere before |

Nothing deletes, rewrites transcripts, polishes or reprocesses. Dates in and
out are days in `mcp.time_zone` (default `America/New_York`): entries are
stored with UTC timestamps, so an entry dictated at 22:30 belongs to that
evening, not the next UTC day.

Results are built field by field (`mcp_server/views.py`) into the models in
`mcp_server/models.py`. Processing errors, LLM usage, pre-polish text,
segments, GridFS ids and the `risk_flags` classifier output never leave the
server; `tests/test_mcp_tools.py` checks the output of every tool for them and
fails if a result model gains a field named like them.

## Routes

All identical on the gateway and on the service; the gateway mapping
(`api-gateway/services/gateway/mapping/kube-tools.json`) passes them through
unchanged.

```
/api/tools/journal/mcp                                            MCP (streaming route)
/.well-known/oauth-protected-resource/api/tools/journal/mcp       RFC 9728 resource metadata
/.well-known/oauth-authorization-server/api/tools/journal/oauth   RFC 8414 AS metadata
/api/tools/journal/oauth/{authorize,token,register,revoke}        OAuth 2.1 + RFC 7591
/api/tools/journal/oauth/consent                                  the approval screen
```

Nothing is claimed at the root of `api.dan-leonard.com`: the issuer is
`https://api.dan-leonard.com/api/tools/journal/oauth`, and per RFC 8414 its
metadata sits at the well-known path with the issuer path appended.

## Enabling it

Add an `mcp` section to `config.json`. Without it, or with `enabled: false`,
no MCP or OAuth routes exist.

```json
"mcp": {
  "enabled": true,
  "public_host": "api.dan-leonard.com",
  "extra_allowed_hosts": ["kube-tools.kube-tools.svc.cluster.local"],
  "request_state_secrets": ["<at least 32 characters>"],
  "oauth": {
    "owner_password": "<python -c \"import secrets; print(secrets.token_urlsafe(48))\">"
  }
}
```

- `owner_password` approves an authorization on the consent page. It is
  compared directly, so generate it rather than choosing it. MCP refuses to
  start enabled without it.
- `extra_allowed_hosts` must include the cluster service name: the gateway
  replaces `Host` with it, and the transport's DNS-rebinding guard answers
  `421` to any host it does not know.
- `request_state_secrets` lets either uvicorn worker (`--workers 2`) open
  request state the other issued. Only elicitation uses it; harmless to set.
- `api_key` (optional) -- a static bearer key for clients configured by header
  (Claude Code). Not needed for Claude connectors or ChatGPT.
- `path`, `issuer_path`, `server_name` (`journal`, prefixes every tool and
  scope) and `display_name` (`Journal`) have defaults matching the layout
  above. **The issuer URL is stored by every connected client**, so changing
  `public_host` or `issuer_path` later means reconnecting each one.

## Deploy order

1. **api-gateway**: the `stream` branch must be deployed first. The gateway on
   `main` buffers responses and forwards upstream framing headers, which
   breaks the MCP transport. The journal routes are in `kube-tools.json` on that
   branch.
2. **kube-tools**: deploy with the `mcp` section above.
3. Connect a client (below) and check `tools/list` returns `journal_*` tools.

## Connecting a client

**Claude (custom connector) or ChatGPT:** add
`https://api.dan-leonard.com/api/tools/journal/mcp` as the server URL and
nothing else. The client discovers the authorization server from the `401`,
registers itself, and opens the consent page. Check the redirect host is the
client you expect, enter the owner password, and choose **Allow**. Tick
**Also allow changes** to grant `journal:write`; leave it unticked for a
read-only connection.

**Claude Code:** OAuth works the same way, or with `api_key` set:

```bash
claude mcp add --transport http journal https://api.dan-leonard.com/api/tools/journal/mcp --header "Authorization: Bearer <mcp.api_key>"
```

## How access works

| Credential | Read | Write |
| --- | --- | --- |
| OAuth token, approved without "Also allow changes" | yes | no |
| OAuth token, approved with it | yes | yes |
| `mcp.api_key` | yes | yes |

- Failed consent attempts are counted per authorization request and lock out
  after `consent_max_attempts`. The page refuses to be framed.
- Tokens are opaque and stored hashed: access tokens 1 hour in Redis, refresh
  tokens 30 days in Mongo (`Journals.McpOAuthClients`,
  `Journals.McpOAuthRefreshTokens`), rotated on every use. Every token is bound
  to the MCP endpoint (RFC 8707); a token for another path on the same gateway
  host is refused.
- Redis keys use the `journal:mcp:oauth:*` prefix. oura-sync uses `mcp:oauth:*`
  and plaid-sync `spendyak:mcp:oauth:*`; a shared prefix would make each service
  accept the other's tokens.
- Tool results are typed models: only declared fields leave the server.

## Revoking access

Claude and ChatGPT register as public clients, so `client_secret` is sent
empty; the SDK requires the field.

```bash
curl -sX POST https://api.dan-leonard.com/api/tools/journal/oauth/revoke -d "token=<access-or-refresh-token>" -d "client_id=<client_id>" -d "client_secret="
```

Or delete the client from `McpOAuthClients` and its rows from
`McpOAuthRefreshTokens`; access tokens expire within the hour.
