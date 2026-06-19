# Caddy reverse-proxy config

Single Caddyfile that routes everything coming in on `:8081` for the
on-prem Windows host. Three independent web apps share this proxy:

| Prefix                          | Static root                          | Backend proxy           |
| ------------------------------- | ------------------------------------ | ----------------------- |
| `/data-management/*`            | `C:\3i Fund\data-management-ui`      | `localhost:5000` (DTS)  |
| `/position_risk_management/*`   | `C:\portal\position_risk_management` | `:5000` and `:8000`     |
| (root)                          | health probe only                    | —                       |

Under `/position_risk_management/*` specifically:

| Subpath              | Upstream         | What it serves                                                       |
| -------------------- | ---------------- | -------------------------------------------------------------------- |
| `/api/internal/*`    | FastAPI `:8000`  | `app.internal_elocs` (PRM-replica ELOC REST routes)                  |
| `/api/*`             | DTS `:5000`      | Trader risk profiles, broker data — historical convention            |
| `/ws/*`              | FastAPI `:8000`  | `app.workflows` WS relay (incl. `/ws/elocs/internal` for PRM mirror) |
| everything else      | static SPA       | `index.html`, page bundles, `shared/*`                               |

The matchers are evaluated top-to-bottom inside `handle_path` — keep
the static `handle {}` block last so the proxies always win, and put
`/api/internal/*` ABOVE `/api/*` so the more-specific match wins.

## ⚠ CloudFront forwards only `/api/*` and `/ws/*`

The public host `3ifundportal.com` sits behind a CloudFront
distribution. CloudFront has explicit behaviors for `/api/*` and
`/ws/*` that forward to this Caddy. **Anything else falls through to
CloudFront's default behavior, which returns the SPA's `index.html`
with a 200 status — not a 404, not a proxy error.**

Practical consequence: **every new backend route the browser calls
must live under `/api/...` (or `/ws/...` for WebSockets).** A route
under any other prefix will silently return HTML to the browser, and
`res.json()` will explode with
`Unexpected token '<', "<!DOCTYPE..."`.

This is why `app.internal_elocs.router` is mounted at
`/api/internal/...` in `app/main.py`, not at `/internal/...`. The
Caddy `/api/internal/*` rule above sends those calls to FastAPI
while leaving the existing `/api/*` → DTS rule in place for the
historical use.

## Live location vs. this file

The Caddy process on the host loads its config from
**`C:\Caddy\Caddyfile`** (PID can be found with
`Get-Process caddy | Select-Object Id,Path`).

This repo copy is the **canonical source**. To apply a change:

1. Edit `ops/caddy/Caddyfile` here, commit, push.
2. On the host, copy or replace `C:\Caddy\Caddyfile` with the new
   contents, then graceful-reload:

   ```powershell
   Copy-Item C:\portal\3i-Portal\ops\caddy\Caddyfile C:\Caddy\Caddyfile -Force
   & C:\Caddy\caddy.exe validate --config C:\Caddy\Caddyfile
   & C:\Caddy\caddy.exe reload   --config C:\Caddy\Caddyfile
   ```

`caddy reload` is graceful — no in-flight requests are dropped. There
is currently no CI step that automates this; the host pulls from `git`
and the operator runs the sync command above.

## WebSocket notes

The `/ws/*` matcher sets `read_timeout 1h` / `write_timeout 1h` because
the `/ws/elocs/internal` connection is expected to stay open for an
operator's entire session. Caddy 2.x auto-handles the Upgrade headers
so no explicit `header_up` is needed.

## Single-worker reminder

The FastAPI singleton WS relay (`app/workflows/router.py`) assumes
one uvicorn worker. The NSSM-wrapped `portal-backend` Windows service
is configured without `--workers`. If that ever changes, the relay
breaks — see the banner above `connect_dealterms_ws` in
`3i-portal-backend/app/workflows/router.py`.
