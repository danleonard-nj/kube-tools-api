"""Consent page for the journal MCP OAuth authorization flow.

Ported from plaid-sync's ``routes/mcp_consent.py``. A client sends the browser
to ``{issuer_path}/authorize``; the authorization server parks the request and
redirects here, to ``{issuer_path}/consent``. Approving with the owner password
mints the authorization code and sends the browser back to the client; denying
sends ``access_denied``.

Deliberately plain HTML with no external assets: it handles a secret and grants
access to journal entries, so it loads nothing it does not control and refuses
to be framed.
"""

import html

from quart import Blueprint, Response, redirect, request

from models.mcp_config import McpConfig
from services.mcp_auth_service import ConsentError, ConsentLockedOut, McpAuthService
from utilities.provider import ContainerProvider


def _provider():
    return ContainerProvider.get_service_provider()


def create_mcp_consent_blueprint(config: McpConfig) -> Blueprint:
    """The consent routes, at ``config.consent_path``.

    Built from the config rather than declared at import, because the path is
    configurable. Services are still resolved per request: the container is
    built inside the serving loop (see ``app.py``).
    """
    blueprint = Blueprint('mcp_consent', __name__)
    blueprint.add_url_rule(config.consent_path, view_func=show_consent, methods=['GET'])
    blueprint.add_url_rule(config.consent_path, view_func=submit_consent, methods=['POST'])
    return blueprint


async def show_consent():
    config = _provider().resolve(McpConfig)
    service = _provider().resolve(McpAuthService)

    txn = request.args.get('txn', '')
    pending = await service.pending_request(txn)
    if pending is None:
        return _page(config, 'Request expired', _expired_message(), status=400)

    return _page(config, 'Allow access?', None, status=200, body=_form(config, txn, pending))


async def submit_consent():
    config = _provider().resolve(McpConfig)
    service = _provider().resolve(McpAuthService)

    form = await request.form
    txn = str(form.get('txn', ''))

    if form.get('action') == 'deny':
        target = await service.deny_consent(txn)
        if target is None:
            return _page(config, 'Request expired', _expired_message(), status=400)
        return redirect(target, 302)

    # Rate limiting is keyed on the authorization request, not the client
    # address: behind the gateway every request shares a source IP, so per-IP
    # counting would lock out everyone at once or nobody.
    try:
        target = await service.approve_consent(
            txn_id=txn,
            password=str(form.get('password', '')),
            attempt_key=txn,
            allow_write=form.get('allow_write') == 'on',
        )
    except ConsentLockedOut as exc:
        return _page(config, 'Locked out', str(exc), status=429)
    except ConsentError as exc:
        pending = await service.pending_request(txn)
        if pending is None:
            return _page(config, 'Request expired', str(exc), status=400)
        return _page(config, 'Allow access?', None, status=401,
                     body=_form(config, txn, pending, error=str(exc)))

    return redirect(target, 302)


def _expired_message() -> str:
    return ('This authorization request has expired or was already completed. '
            'Start again from your MCP client.')


def _form(config: McpConfig, txn: str, pending: dict, error=None) -> str:
    app_name = html.escape(config.display_name)
    client = html.escape(pending.get('client_name') or pending['client_id'])
    redirect_host = html.escape(pending['redirect_host'])
    redirect_uri = html.escape(pending['redirect_uri'])
    banner = f'<p class="error">{html.escape(error)}</p>' if error else ''

    return f"""
      {banner}
      <p><strong>{client}</strong> wants to read your {app_name}: entries,
        transcripts, summaries, moods and tags.</p>
      <dl>
        <dt>Sends you back to</dt><dd><strong>{redirect_host}</strong></dd>
        <dt>Full redirect</dt><dd><code>{redirect_uri}</code></dd>
      </dl>
      <p class="warn">
        Only continue if you started this from a client you trust. Access lasts
        until you revoke it.
      </p>
      <form method="post" action="{html.escape(config.consent_path)}">
        <input type="hidden" name="txn" value="{html.escape(txn)}">
        <label class="check">
          <input type="checkbox" name="allow_write">
          Also allow changes: adding entries and editing their titles and tags
        </label>
        <label for="password">Owner password</label>
        <input type="password" id="password" name="password" autocomplete="current-password"
               autofocus required>
        <div class="actions">
          <button type="submit" name="action" value="approve">Allow</button>
          <button type="submit" name="action" value="deny" class="secondary" formnovalidate>Deny</button>
        </div>
      </form>
    """


def _page(config: McpConfig, title: str, message, *, status: int, body: str = '') -> Response:
    content = body or f'<p>{html.escape(message or "")}</p>'
    return Response(
        f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{html.escape(title)} - {html.escape(config.display_name)}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
         max-width: 34rem; margin: 4rem auto; padding: 0 1.25rem; }}
  h1 {{ font-size: 1.35rem; margin-bottom: 1.25rem; }}
  dl {{ display: grid; grid-template-columns: auto 1fr; gap: .35rem 1rem; margin: 1.25rem 0; }}
  dt {{ font-weight: 600; }}
  dd {{ margin: 0; overflow-wrap: anywhere; }}
  code {{ font-size: .85em; }}
  label {{ display: block; font-weight: 600; margin: 1.5rem 0 .35rem; }}
  input[type=password] {{ width: 100%; padding: .6rem; font-size: 1rem; box-sizing: border-box; }}
  .check {{ display: flex; gap: .6rem; align-items: flex-start; font-weight: normal; }}
  .check input {{ margin-top: .3rem; }}
  .actions {{ display: flex; gap: .75rem; margin-top: 1.25rem; }}
  button {{ padding: .6rem 1.25rem; font-size: 1rem; cursor: pointer; }}
  .secondary {{ opacity: .75; }}
  .warn {{ font-size: .9rem; opacity: .8; }}
  .error {{ padding: .6rem .8rem; border-left: 3px solid currentColor; font-weight: 600; }}
</style>
</head><body>
<h1>{html.escape(title)}</h1>
{content}
</body></html>""",
        status=status,
        content_type='text/html; charset=utf-8',
        headers={
            'Cache-Control': 'no-store',
            'X-Frame-Options': 'DENY',
            # No form-action: browsers apply it to the redirect that follows the
            # POST, which would block the hand-back to the client.
            'Content-Security-Policy': (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "frame-ancestors 'none'; base-uri 'none'"
            ),
            'Referrer-Policy': 'no-referrer',
        },
    )
