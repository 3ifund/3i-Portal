"""
3i Fund Portal — Workflow WebSocket Relay
Connects to DealTermsServer's ws/eloc WebSocket for real-time workflow
state changes. Relays updates to connected frontend browser clients.
"""

import asyncio
import json
import logging
from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import websockets

from app.auth.jwt import decode_access_token
from app.config import settings
from app.elocs.models import build_workflow_steps
from app.internal_elocs.models import derive_workflow_steps as _internal_derive_steps
from app.onprem import client as onprem
import uuid as _uuid

logger = logging.getLogger("portal.workflows")
router = APIRouter()

# Reconnect settings
MAX_RECONNECT_DELAY = 30  # seconds
INITIAL_RECONNECT_DELAY = 2  # seconds

# ---- Connection Manager (browser clients) ----

# Maps company_id → set of connected browser WebSockets (client portal use)
_connections: dict[int, set[WebSocket]] = {}

# Maps eloc_id → company_id for routing eloc_removed events
_eloc_company_map: dict[str, int] = {}

# Internal/admin browser subscribers for the PRM-replica web app. No tenant
# scoping — every internal subscriber gets every Portal-flow ELOC event.
# Drives /api/internal/elocs and the position_risk_management web view.
_internal_connections: set[WebSocket] = set()


def _connection_summary() -> str:
    """Return a summary of connected companies and client counts for logging."""
    if not _connections:
        return "no connected clients"
    parts = [f"company_{cid}={len(clients)}" for cid, clients in _connections.items()]
    return f"{sum(len(c) for c in _connections.values())} clients across {len(_connections)} companies: {', '.join(parts)}"


def _register(company_id: int, ws: WebSocket):
    if company_id not in _connections:
        _connections[company_id] = set()
    _connections[company_id].add(ws)
    logger.info("WS client registered: company_id=%s (%d clients for this company, %s)",
                company_id, len(_connections[company_id]), _connection_summary())


def _unregister(company_id: int, ws: WebSocket):
    if company_id in _connections:
        _connections[company_id].discard(ws)
        if not _connections[company_id]:
            del _connections[company_id]
    logger.info("WS client unregistered: company_id=%s (%s)", company_id, _connection_summary())


async def _broadcast(company_id: int, data: dict):
    """Send a message to all connected browser clients for a company."""
    clients = _connections.get(company_id, set()).copy()
    msg_type = data.get("type", "unknown")
    eloc_id = data.get("eloc_id") or data.get("workflow", {}).get("eloc_id", "")

    if not clients:
        logger.warning("BROADCAST SKIPPED: type=%s eloc_id=%s company_id=%s — no connected clients (%s)",
                        msg_type, eloc_id, company_id, _connection_summary())
        return

    message = json.dumps(data)
    dead = []
    for ws in clients:
        try:
            await ws.send_text(message)
        except Exception as exc:
            logger.warning("BROADCAST FAILED to client: company_id=%s type=%s error=%s", company_id, msg_type, exc)
            dead.append(ws)

    for ws in dead:
        _unregister(company_id, ws)

    sent_count = len(clients) - len(dead)
    logger.info("BROADCAST SENT: type=%s eloc_id=%s company_id=%s → %d/%d clients (dead=%d)",
                msg_type, eloc_id, company_id, sent_count, len(clients), len(dead))


# ---- Internal (PRM-replica) fan-out -----------------------------------------
#
# The internal pool is fan-out to all admin subscribers regardless of company
# (PRM-WPF style — operators see every active workflow). The payload differs
# from the tenant fan-out above: internal subscribers receive the raw
# DTS-source enums plus a server-derived FULL step grid (10 forward / 4
# backward), not the 4-visible / 1-visible client subset.
#
# Important: NEVER share helpers/payloads between the two fan-outs. The client
# fan-out's `_build_workflow_message` filters and renames fields; reusing it
# here would silently downgrade the internal view.


def _internal_connection_summary() -> str:
    if not _internal_connections:
        return "no internal clients"
    return f"{len(_internal_connections)} internal client(s)"


def _internal_register(ws: WebSocket):
    _internal_connections.add(ws)
    logger.info("INTERNAL WS client registered (%s)", _internal_connection_summary())


def _internal_unregister(ws: WebSocket):
    _internal_connections.discard(ws)
    logger.info("INTERNAL WS client unregistered (%s)", _internal_connection_summary())


def _build_internal_workflow_message(state: dict) -> dict:
    """
    Build a workflow_update message for the internal/PRM-replica subscribers.
    DTS returns camelCase JSON; this normalizes to snake_case and pre-derives
    the full 10/4 step grid so the browser can paint immediately.

    ⚠ Only call with PORTAL-FLOW states. 12-step / DTS-source ELOCs would
    pollute the shared `_eloc_company_map` cache used by the tenant
    eloc_removed routing — see the source check below.
    """
    eloc_id = str(state.get("elocId", ""))
    company_id = state.get("companyId", 0)
    workflow_step = state.get("workflowStep", "") or ""
    status = state.get("status", "Pending") or "Pending"
    pricing_direction = state.get("pricingDirection", "Forward") or "Forward"
    workflow_complete = bool(state.get("workflowComplete", False))
    modified_at = state.get("modifiedAt")
    company_symbol = state.get("companySymbol") or state.get("symbol")

    # Cache the eloc → company mapping ONLY when the source is explicitly
    # portal (or absent — REST state-by-id returns portal states without
    # an explicit source field, the caller wouldn't have routed it here
    # otherwise). If a DTS-source state ever flows through this builder
    # we refuse to touch the map so the tenant `eloc_removed` fallback
    # broadcast stays correct.
    source = state.get("source")
    if eloc_id and company_id and source in (None, "portal"):
        prev = _eloc_company_map.get(eloc_id)
        _eloc_company_map[eloc_id] = int(company_id)
        if prev is None:
            logger.info(
                "ELOC map (via internal build): cached %s → company_id=%s (map size=%d)",
                eloc_id, company_id, len(_eloc_company_map),
            )
    elif source not in (None, "portal"):
        logger.warning(
            "INTERNAL build: refusing to cache eloc=%s company_id=%s — source=%s is not portal",
            eloc_id, company_id, source,
        )

    steps = _internal_derive_steps(workflow_step, status, pricing_direction)

    logger.debug(
        "INTERNAL build: eloc=%s company=%s symbol=%s step=%s status=%s dir=%s steps=%d",
        eloc_id, company_id, company_symbol, workflow_step, status,
        pricing_direction, len(steps),
    )

    return {
        "type": "workflow_update",
        "scope": "internal",
        "workflow": {
            "eloc_id": eloc_id,
            "company_id": company_id,
            "company_symbol": company_symbol,
            "workflow_step": workflow_step,
            "status": status,
            "pricing_direction": pricing_direction,
            "workflow_complete": workflow_complete,
            "modified_at": str(modified_at) if modified_at else None,
            "steps": steps,
        },
    }


async def _internal_send_one(ws: WebSocket, message: str) -> bool:
    """Wrapper used by the parallel broadcast — returns True on success."""
    try:
        await ws.send_text(message)
        return True
    except Exception as exc:
        logger.warning(
            "INTERNAL BROADCAST FAILED to client: error=%s (%s)",
            exc, type(exc).__name__,
        )
        return False


async def _internal_broadcast(data: dict):
    """
    Send a message to every connected internal/admin subscriber.

    Sends are parallelized with asyncio.gather so a single stalled browser
    socket can't head-of-line block the DTS WS read loop (which awaits
    every broadcast pass before reading the next event). Without this, a
    slow operator's TCP receive window can throttle event delivery to
    everyone.
    """
    msg_type = data.get("type", "unknown")
    eloc_id = data.get("eloc_id") or (data.get("workflow") or {}).get("eloc_id", "")

    # Snapshot first; the underlying set may mutate while we await.
    snapshot = list(_internal_connections)
    if not snapshot:
        logger.info(
            "INTERNAL BROADCAST SKIPPED: type=%s eloc_id=%s — no internal clients",
            msg_type, eloc_id,
        )
        return

    message = json.dumps(data)
    logger.debug(
        "INTERNAL BROADCAST START: type=%s eloc_id=%s subscribers=%d bytes=%d",
        msg_type, eloc_id, len(snapshot), len(message),
    )

    results = await asyncio.gather(
        *(_internal_send_one(ws, message) for ws in snapshot),
        return_exceptions=False,  # _internal_send_one swallows already
    )

    dead = [ws for ws, ok in zip(snapshot, results) if not ok]
    for ws in dead:
        _internal_unregister(ws)

    sent = len(snapshot) - len(dead)
    logger.info(
        "INTERNAL BROADCAST SENT: type=%s eloc_id=%s → %d/%d clients (dead=%d)",
        msg_type, eloc_id, sent, len(snapshot), len(dead),
    )


async def _send_internal_initial_state(ws: WebSocket):
    """
    On internal-WS connect, push every currently-included Portal-flow ELOC
    as a workflow_update. No tenant filtering — mirrors PRM-WPF's full
    operator view.
    """
    count = 0
    skipped_hidden = 0
    failures = 0
    try:
        portal_states = await onprem.get_portal_eloc_states_included()
        logger.info(
            "INTERNAL WS initial state: fetched %d included portal states",
            len(portal_states),
        )
        for state in portal_states:
            if state.get("workflowVisible") is False:
                skipped_hidden += 1
                logger.debug(
                    "INTERNAL initial: skipping hidden eloc=%s",
                    state.get("elocId"),
                )
                continue
            message = _build_internal_workflow_message(state)
            try:
                await ws.send_text(json.dumps(message))
                count += 1
                logger.debug(
                    "INTERNAL initial: sent eloc=%s step=%s status=%s dir=%s",
                    state.get("elocId"),
                    state.get("workflowStep"),
                    state.get("status"),
                    state.get("pricingDirection"),
                )
            except Exception as send_exc:
                failures += 1
                logger.warning(
                    "INTERNAL initial: send FAILED for eloc=%s: %s",
                    state.get("elocId"), send_exc,
                )
                # Don't keep trying if the socket already failed once.
                break
    except Exception as exc:
        logger.warning("INTERNAL WS initial state: FAILED: %s", exc)

    logger.info(
        "INTERNAL WS initial state COMPLETE: sent=%d, hidden=%d, failures=%d",
        count, skipped_hidden, failures,
    )


# ---- WebSocket Endpoint (browser clients connect here) ----

@router.websocket("/workflows")
async def websocket_workflows(websocket: WebSocket, token: str = ""):
    """
    WebSocket for real-time workflow state updates.
    Frontend connects with ?token=JWT. Backend relays workflow_update
    and workflow_removed messages from DealTermsServer.
    """
    client_host = websocket.client.host if websocket.client else "unknown"
    logger.info("WS /workflows: incoming connection from %s", client_host)

    # Validate JWT token
    if not token:
        logger.warning("WS /workflows: REJECTED — no token provided from %s", client_host)
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    try:
        payload = decode_access_token(token)
        logger.info("WS /workflows: JWT valid — user_id=%s company_id=%s company_symbol=%s",
                     payload.get("user_id"), payload.get("company_id"), payload.get("company_symbol"))
    except Exception as exc:
        logger.warning("WS /workflows: REJECTED — JWT validation failed from %s: %s", client_host, exc)
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    company_id = payload.get("company_id")
    if not company_id:
        logger.warning("WS /workflows: REJECTED — no company_id in JWT for user=%s", payload.get("user_id"))
        await websocket.close(code=4002, reason="No company assigned")
        return

    company_id = int(company_id)
    await websocket.accept()
    _register(company_id, websocket)
    logger.info("WS /workflows: ACCEPTED — user=%s company_id=%s host=%s",
                payload.get("user_id"), company_id, client_host)

    # Send current workflow state on connect
    try:
        await _send_initial_state(company_id, websocket)
    except Exception as exc:
        logger.warning("WS /workflows: failed to send initial state to company_id=%s: %s", company_id, exc)

    try:
        # Keep connection alive — just wait for client disconnect
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("WS /workflows: client DISCONNECTED — company_id=%s user=%s",
                     company_id, payload.get("user_id"))
    except Exception as exc:
        logger.warning("WS /workflows: connection ERROR — company_id=%s user=%s: %s",
                        company_id, payload.get("user_id"), exc)
    finally:
        _unregister(company_id, websocket)


@router.websocket("/elocs/internal")
async def websocket_elocs_internal(websocket: WebSocket, token: str = ""):
    """
    Internal WebSocket for the PRM-replica web app
    (position_risk_management). Pushes workflow_update / workflow_removed
    frames for EVERY Portal-flow ELOC across ALL companies — no tenant
    scoping, mirrors PRM-WPF's operator view.

    Requires a JWT with role=admin in the ?token= query parameter.
    """
    client_host = websocket.client.host if websocket.client else "unknown"
    logger.info("WS /elocs/internal: incoming connection from %s", client_host)

    if not token:
        logger.warning(
            "WS /elocs/internal: REJECTED — no token from %s", client_host,
        )
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    try:
        payload = decode_access_token(token)
    except Exception as exc:
        logger.warning(
            "WS /elocs/internal: REJECTED — JWT validation failed from %s: %s",
            client_host, exc,
        )
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    role = payload.get("role")
    user_id = payload.get("user_id")
    if role != "admin":
        logger.warning(
            "WS /elocs/internal: REJECTED — role=%s (need 'admin') for user=%s",
            role, user_id,
        )
        await websocket.close(code=4003, reason="Admin role required")
        return

    # Plan a hard-close at token expiration. JWT `exp` is unix-seconds.
    # We close 30s before expiry so a clock drift doesn't let a stale
    # token slip a final event through. The frontend already handles
    # close-code 4001 as "no reconnect" (matches the initial-auth reject
    # path), so the operator gets a single visible "re-sign in" prompt
    # instead of a reconnect loop hammering the backend.
    exp = payload.get("exp")
    exp_task: asyncio.Task | None = None
    if isinstance(exp, (int, float)):
        import time as _time
        ttl = max(0, float(exp) - _time.time() - 30)
        if ttl > 0:
            async def _close_at_exp():
                try:
                    await asyncio.sleep(ttl)
                    if websocket.client_state.name == "CONNECTED":
                        logger.info(
                            "WS /elocs/internal: closing on JWT exp for user=%s (ttl=%.1fs)",
                            user_id, ttl,
                        )
                        await websocket.close(code=4001, reason="Token expired")
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.warning(
                        "WS /elocs/internal: exp-close task error for user=%s: %s",
                        user_id, e,
                    )
            exp_task = asyncio.create_task(_close_at_exp())

    await websocket.accept()
    # Register BEFORE sending initial state so any concurrent broadcast
    # during the initial dump doesn't get lost (the client may receive a
    # workflow_update twice for the same eloc_id; client should dedupe by
    # modified_at).
    _internal_register(websocket)
    import time as _time
    logger.info(
        "WS /elocs/internal: ACCEPTED — user=%s host=%s exp_in_sec=%.0f",
        user_id, client_host,
        (float(exp) - _time.time()) if isinstance(exp, (int, float)) else -1,
    )

    try:
        await _send_internal_initial_state(websocket)
    except Exception as exc:
        logger.warning(
            "WS /elocs/internal: initial state failed for user=%s: %s",
            user_id, exc,
        )

    try:
        while True:
            # Read to surface disconnects and accept client pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info(
            "WS /elocs/internal: client DISCONNECTED — user=%s", user_id,
        )
    except Exception as exc:
        logger.warning(
            "WS /elocs/internal: connection ERROR — user=%s: %s", user_id, exc,
        )
    finally:
        if exp_task and not exp_task.done():
            exp_task.cancel()
        _internal_unregister(websocket)


# ---- Initial State & Resync via DealTermsServer REST ----

def _build_workflow_message(state: dict, source: str = "dts") -> dict:
    """
    Build a workflow_update message from a DealTermsServer state response.
    DealTermsServer returns camelCase JSON: elocId, companyId, workflowStep, status, modifiedAt.
    source: "dts" for upstream ELOCs, "portal" for portal-initiated ELOCs.
    """
    eloc_id = str(state.get("elocId", ""))
    company_id = state.get("companyId", 0)
    workflow_step = state.get("workflowStep", "")
    status = state.get("status", "Pending")
    modified_at = state.get("modifiedAt")
    pricing_direction = state.get("pricingDirection", "Forward")
    workflow_complete = state.get("workflowComplete", False)

    steps, can_remove = build_workflow_steps(
        workflow_step, status, pricing_direction, workflow_complete)

    # Cache the eloc→company mapping for routing eloc_removed events
    if eloc_id and company_id:
        prev = _eloc_company_map.get(eloc_id)
        _eloc_company_map[eloc_id] = int(company_id)
        if prev is None:
            logger.info("ELOC map: cached %s → company_id=%s (map size=%d)",
                        eloc_id, company_id, len(_eloc_company_map))

    return {
        "type": "workflow_update",
        "workflow": {
            "eloc_id": eloc_id,
            "company_id": company_id,
            "current_step": workflow_step,
            "step_status": status,
            "updated_at": str(modified_at) if modified_at else None,
            "can_remove": can_remove,
            "steps": steps,
            "source": source,
            "pricing_direction": pricing_direction,
            "workflow_complete": workflow_complete,
        },
    }


async def _send_initial_state(company_id: int, ws: WebSocket):
    """Send Portal-initiated workflows to a newly connected browser client.
    12-step ELOCs are not sent as workflow cards — they only affect shares available blocking."""
    count = 0
    skipped_hidden = 0
    skipped_other = 0

    # Portal-initiated workflows only
    try:
        portal_states = await onprem.get_portal_eloc_states_included()
        logger.info("WS initial state: fetched %d included portal states for company_id=%s",
                     len(portal_states), company_id)
        for state in portal_states:
            if state.get("companyId") == company_id:
                if state.get("workflowVisible") is False:
                    skipped_hidden += 1
                    logger.info("WS initial state: skipping hidden ELOC %s (workflowVisible=false)",
                                state.get("elocId"))
                    continue
                message = _build_workflow_message(state, source="portal")
                await ws.send_text(json.dumps(message))
                count += 1
                logger.info("WS initial state: sent workflow card for ELOC %s (step=%s, status=%s)",
                            state.get("elocId"), state.get("workflowStep"), state.get("status"))
            else:
                skipped_other += 1
    except Exception as exc:
        logger.warning("WS initial state: FAILED to fetch portal states for company_id=%s: %s",
                        company_id, exc)

    logger.info("WS initial state COMPLETE: company_id=%s — sent=%d, hidden=%d, other_companies=%d",
                company_id, count, skipped_hidden, skipped_other)


async def _resync_all_clients():
    """
    Broadcast current state to all connected browser clients.
    Called when DealTermsServer WebSocket reconnects to catch any missed
    changes. Fans out to BOTH the tenant-scoped client portal pool AND the
    no-tenant internal/PRM-replica pool with a single REST fetch.
    """
    has_tenant = bool(_connections)
    has_internal = bool(_internal_connections)
    if not has_tenant and not has_internal:
        logger.info("DTS WS resync: no connected clients (tenant or internal), skipping")
        return

    logger.info(
        "DTS WS resync: resyncing tenant=[%s] internal=[%s]",
        _connection_summary(), _internal_connection_summary(),
    )

    # Portal-initiated workflows only — 12-step ELOCs are not workflow cards
    try:
        portal_states = await onprem.get_portal_eloc_states_included()
        logger.info("DTS WS resync: fetched %d included portal states", len(portal_states))
        tenant_sent = 0
        internal_sent = 0
        for state in portal_states:
            if state.get("workflowVisible") is False:
                continue
            company_id = state.get("companyId")

            # Tenant fan-out (existing client portal pool)
            if has_tenant and company_id and company_id in _connections:
                tenant_msg = _build_workflow_message(state, source="portal")
                await _broadcast(company_id, tenant_msg)
                tenant_sent += 1

            # Internal fan-out (PRM-replica pool) — no tenant filter
            if has_internal:
                internal_msg = _build_internal_workflow_message(state)
                await _internal_broadcast(internal_msg)
                internal_sent += 1

        logger.info(
            "DTS WS resync COMPLETE: tenant_sent=%d internal_sent=%d",
            tenant_sent, internal_sent,
        )
    except Exception as exc:
        logger.warning("DTS WS resync FAILED: %s", exc)


# ---- DealTermsServer WebSocket Client ----

def _get_dts_ws_url() -> str:
    """Derive the DealTermsServer WebSocket URL from the HTTP base URL."""
    parsed = urlparse(settings.onprem_base_url)
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    url = f"{ws_scheme}://{parsed.netloc}/ws/eloc"
    logger.debug("DealTermsServer WS URL: %s", url)
    return url


#
# ┌─────────────────────────────────────────────────────────────────────┐
# │  ⚠ SINGLE-WORKER REQUIREMENT                                        │
# │                                                                     │
# │  This relay assumes uvicorn runs with ONE worker process. The       │
# │  module-level dicts above (_connections, _internal_connections,     │
# │  _eloc_company_map) plus the singleton task spawned by lifespan     │
# │  (asyncio.create_task(connect_dealterms_ws())) all live in a single │
# │  Python process. If uvicorn is launched with `--workers N` (or any  │
# │  process supervisor multiplies the app), each worker opens its own  │
# │  DTS WebSocket and holds its own browser pool. An event arriving on │
# │  worker A's DTS connection silently misses any browser parked on    │
# │  worker B — updates appear lost with no error.                      │
# │                                                                     │
# │  Current prod config (NSSM-wrapped portal-backend Windows service): │
# │      python -m uvicorn app.main:app --host 0.0.0.0 --port 8000      │
# │      → no --workers flag → uvicorn default = 1 worker. OK.          │
# │                                                                     │
# │  If you ever need to scale to multiple workers, replace the         │
# │  module-level fan-out with a Redis/Postgres pub-sub bus and have    │
# │  each worker subscribe to it instead of opening its own DTS WS.     │
# └─────────────────────────────────────────────────────────────────────┘
#
async def connect_dealterms_ws():
    """
    Background task: connect to DealTermsServer's ws/eloc WebSocket.
    Receives state_changed, eloc_added, eloc_removed events and relays
    them to connected browser clients. Reconnects with exponential backoff.

    ⚠ Must run in a single uvicorn worker — see banner above.
    """
    ws_url = _get_dts_ws_url()
    reconnect_delay = INITIAL_RECONNECT_DELAY

    while True:
        dts_ws = None
        try:
            logger.info("DTS WS: connecting to %s", ws_url)
            dts_ws = await websockets.connect(ws_url)

            # Read welcome message
            welcome = await dts_ws.recv()
            logger.info("DTS WS: connected, welcome: %s", str(welcome)[:500])

            # Identify ourselves
            identify_msg = json.dumps({
                "action": "identify",
                "userName": "portal-backend",
                "machineName": "3i-portal",
            })
            await dts_ws.send(identify_msg)
            logger.info("DTS WS: sent identify")

            # Reset backoff on successful connection
            reconnect_delay = INITIAL_RECONNECT_DELAY

            # Resync all browser clients to catch any changes missed during disconnect
            await _resync_all_clients()

            # Listen for events from DealTermsServer
            async for raw_message in dts_ws:
                try:
                    msg = json.loads(raw_message)
                except json.JSONDecodeError:
                    logger.warning("DTS WS: invalid JSON: %s", str(raw_message)[:500])
                    continue

                msg_type = msg.get("type", "")
                msg_eloc = msg.get("elocId", "")
                logger.info("DTS WS RECV: type=%s elocId=%s source=%s step=%s status=%s",
                            msg_type, msg_eloc, msg.get("source", ""), msg.get("step", ""), msg.get("status", ""))

                if msg_type == "state_changed":
                    await _handle_state_changed(msg)
                elif msg_type == "eloc_added":
                    await _handle_eloc_added(msg)
                elif msg_type == "eloc_removed":
                    await _handle_eloc_removed(msg)
                elif msg_type == "eloc_hidden":
                    await _handle_eloc_hidden(msg)
                # Ignore: welcome, identified, pong, lock_changed, lock_result, etc.

            # If we get here, the DTS WebSocket closed
            logger.warning("DTS WS: connection closed, will reconnect in %ds", reconnect_delay)

        except asyncio.CancelledError:
            logger.info("DTS WS: task cancelled")
            break
        except (ConnectionRefusedError, OSError, websockets.exceptions.WebSocketException) as exc:
            logger.warning("DTS WS: connection failed: %s (retry in %ds)", exc, reconnect_delay)
        except Exception as exc:
            logger.error("DTS WS: unexpected error: %s (retry in %ds)", exc, reconnect_delay, exc_info=True)
        finally:
            if dts_ws:
                try:
                    await dts_ws.close()
                except Exception:
                    pass

        await asyncio.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 2, MAX_RECONNECT_DELAY)


# ---- Event Handlers ----

async def _handle_state_changed(msg: dict):
    """
    Handle state_changed from DealTermsServer.
    Fetch full state via REST, then broadcast to browser clients.
    Routes to portal or DTS REST endpoint based on source field.
    """
    eloc_id = msg.get("elocId", "")
    source = msg.get("source", "dts")
    step = msg.get("step", "")
    msg_status = msg.get("status", "")
    logger.info("HANDLE state_changed: eloc_id=%s step=%s status=%s source=%s",
                eloc_id, step, msg_status, source)

    # Fetch full state — use portal endpoint if source is portal
    if source == "portal":
        state = await onprem.get_portal_eloc_state_by_id(eloc_id)
    else:
        state = await onprem.get_eloc_state_by_id(eloc_id)

    if not state:
        logger.warning("HANDLE state_changed: REST fetch returned null for eloc_id=%s (source=%s)", eloc_id, source)
        return

    company_id = state.get("companyId")
    include = state.get("include", True)
    visible = state.get("workflowVisible")
    logger.info("HANDLE state_changed: eloc_id=%s — REST state: company_id=%s include=%s workflowVisible=%s step=%s status=%s",
                eloc_id, company_id, include, visible, state.get("workflowStep"), state.get("status"))

    if not company_id:
        logger.warning("HANDLE state_changed: no companyId in REST state for eloc_id=%s", eloc_id)
        return

    # Check if still included
    if not include:
        logger.info("HANDLE state_changed: eloc_id=%s include=false → triggering eloc_removed", eloc_id)
        await _handle_eloc_removed({"elocId": eloc_id})
        return

    # Check if hidden from client UI
    if visible is False:
        logger.info("HANDLE state_changed: eloc_id=%s workflowVisible=false → suppressing broadcast", eloc_id)
        return

    # Only broadcast Portal-initiated workflows as workflow cards.
    # 12-step (DTS) ELOCs are managed in PRM — Portal clients only need
    # to know they exist for the "ELOC Currently Pricing" blocking check.
    if source == "portal":
        message = _build_workflow_message(state, source=source)
        logger.info("HANDLE state_changed: broadcasting workflow_update for portal ELOC %s to company_id=%s",
                     eloc_id, company_id)
        await _broadcast(int(company_id), message)

        # Tee to internal subscribers — they want the full 10/4 step grid
        # for every Portal-flow ELOC regardless of company.
        internal_msg = _build_internal_workflow_message(state)
        await _internal_broadcast(internal_msg)
    else:
        # For 12-step ELOCs, notify clients to refresh shares available
        # (the pending ELOC status may have changed)
        logger.info("HANDLE state_changed: broadcasting shares_refresh for DTS ELOC %s to company_id=%s",
                     eloc_id, company_id)
        await _broadcast(int(company_id), {
            "type": "shares_refresh",
            "eloc_id": eloc_id,
            "source": "dts",
        })
        # No internal broadcast — PRM-WPF view doesn't show 12-step ELOCs
        # as workflow cards (mirrors GetPortalIncludedStates behavior).

    # Trigger countersign SMS when Portal ELOC reaches VwapNotificationToCompany/Pending
    if source == "portal" and step == "VwapNotificationToCompany" and msg_status == "Pending":
        logger.info("HANDLE state_changed: VwapNotificationToCompany/Pending — triggering countersign SMS for %s", eloc_id)
        try:
            await _trigger_countersign_sms(eloc_id, state)
        except Exception as exc:
            logger.error("Countersign SMS trigger failed for %s: %s", eloc_id, exc, exc_info=True)


async def _trigger_countersign_sms(eloc_id: str, state: dict):
    """Send SMS countersign links to company users with phone numbers."""
    from app.countersign.repository import has_pending_countersign, create_countersign_token, get_countersign_sms_enabled
    from app.countersign.sms import send_countersign_sms
    from app.users.repository import get_company_users_with_phone

    # Prevent duplicate sends on WebSocket reconnect
    if await has_pending_countersign(eloc_id):
        logger.info("Countersign SMS already sent for %s, skipping", eloc_id)
        return

    company_id = state.get("companyId")
    company_name = state.get("companyName", "")
    if not company_id:
        logger.warning("No companyId in state for countersign SMS: %s", eloc_id)
        return

    # Check if countersign SMS is enabled for this company
    sms_enabled = await get_countersign_sms_enabled(int(company_id))
    if not sms_enabled:
        logger.info("Countersign SMS not enabled for company %s (%s), skipping SMS",
                     company_id, company_name)
        return

    # Get company users with phone numbers
    users_with_phone = await get_company_users_with_phone(int(company_id))

    if not users_with_phone:
        logger.info("No users with phone numbers for company %s, Portal UI countersign only", company_id)
        return

    group_id = str(_uuid.uuid4())
    logger.info("Sending countersign SMS for %s to %d users, group=%s",
                eloc_id, len(users_with_phone), group_id)

    for u in users_with_phone:
        try:
            token_result = await create_countersign_token(
                group_id=group_id,
                signatory_id=u["user_id"],
                signatory_name=u["signatory_name"],
                signatory_phone=u["signatory_phone_number"],
                company_name=company_name,
                eloc_id=eloc_id,
            )
            full_url = f"{settings.approval_base_url}{token_result['url']}"
            await send_countersign_sms(u["signatory_phone_number"], company_name, full_url)
            logger.info("Countersign SMS sent to %s (%s) for %s",
                        u["signatory_name"], u["signatory_phone_number"], eloc_id)
        except Exception as sms_exc:
            logger.error("Countersign SMS failed for %s (%s): %s",
                         u["signatory_name"], u["signatory_phone_number"], sms_exc)


async def _handle_eloc_added(msg: dict):
    """
    Handle eloc_added from DealTermsServer.
    Fetch full state via REST, then broadcast to browser clients.
    Routes to portal or DTS REST endpoint based on source field.
    """
    eloc_id = msg.get("elocId", "")
    company_id = msg.get("companyId")
    source = msg.get("source", "dts")
    logger.info("HANDLE eloc_added: eloc_id=%s company_id=%s source=%s", eloc_id, company_id, source)

    # Cache the mapping
    if eloc_id and company_id:
        _eloc_company_map[eloc_id] = int(company_id)
        logger.info("ELOC map: cached %s → company_id=%s (map size=%d)", eloc_id, company_id, len(_eloc_company_map))

    # Fetch full state — use portal endpoint if source is portal
    if source == "portal":
        state = await onprem.get_portal_eloc_state_by_id(eloc_id)
    else:
        state = await onprem.get_eloc_state_by_id(eloc_id)

    if not state:
        logger.warning("HANDLE eloc_added: REST fetch returned null for new eloc_id=%s (source=%s)", eloc_id, source)
        return

    company_id = state.get("companyId", company_id)
    if not company_id:
        logger.warning("HANDLE eloc_added: no companyId in REST state for eloc_id=%s", eloc_id)
        return

    logger.info("HANDLE eloc_added: building workflow message for %s (company_id=%s, step=%s, status=%s)",
                eloc_id, company_id, state.get("workflowStep"), state.get("status"))
    message = _build_workflow_message(state, source=source)
    await _broadcast(int(company_id), message)

    # Tee Portal-source adds to internal subscribers. Skip 12-step (source=dts)
    # additions because PRM-WPF's view shows Portal-flow ELOCs only.
    if source == "portal":
        internal_msg = _build_internal_workflow_message(state)
        await _internal_broadcast(internal_msg)


async def _handle_eloc_removed(msg: dict):
    """
    Handle eloc_removed from DealTermsServer.
    Broadcast removal to browser clients.
    """
    eloc_id = msg.get("elocId", "")
    company_id = _eloc_company_map.pop(eloc_id, None)
    logger.info("HANDLE eloc_removed: eloc_id=%s company_id=%s (from map=%s, map size=%d)",
                eloc_id, company_id, company_id is not None, len(_eloc_company_map))

    if company_id:
        logger.info("HANDLE eloc_removed: broadcasting workflow_removed for %s to company_id=%s", eloc_id, company_id)
        await _broadcast(company_id, {
            "type": "workflow_removed",
            "eloc_id": eloc_id,
        })
    else:
        # No cached company_id — broadcast to all companies
        all_companies = list(_connections.keys())
        logger.warning("HANDLE eloc_removed: no cached company_id for %s — broadcasting to ALL %d companies: %s",
                        eloc_id, len(all_companies), all_companies)
        for cid in all_companies:
            await _broadcast(cid, {
                "type": "workflow_removed",
                "eloc_id": eloc_id,
            })

    # Tee to internal subscribers — they don't care about company scoping,
    # they just want the eloc_id removed from their grid.
    await _internal_broadcast({
        "type": "workflow_removed",
        "scope": "internal",
        "eloc_id": eloc_id,
    })


async def _handle_eloc_hidden(msg: dict):
    """
    Handle eloc_hidden from DealTermsServer.
    Client clicked Remove — hide from Portal UI only (workflow continues).
    Broadcast workflow_removed to browser clients so the card disappears.
    """
    eloc_id = msg.get("elocId", "")
    company_id = msg.get("companyId")
    logger.info("HANDLE eloc_hidden: eloc_id=%s company_id=%s (from DTS msg)", eloc_id, company_id)

    if company_id:
        logger.info("HANDLE eloc_hidden: broadcasting workflow_removed for %s to company_id=%s", eloc_id, company_id)
        await _broadcast(int(company_id), {
            "type": "workflow_removed",
            "eloc_id": eloc_id,
        })
    else:
        # Try cached mapping
        cached_company_id = _eloc_company_map.get(eloc_id)
        if cached_company_id:
            logger.info("HANDLE eloc_hidden: using cached company_id=%s for %s", cached_company_id, eloc_id)
            await _broadcast(cached_company_id, {
                "type": "workflow_removed",
                "eloc_id": eloc_id,
            })
        else:
            all_companies = list(_connections.keys())
            logger.warning("HANDLE eloc_hidden: no company_id for %s — broadcasting to ALL %d companies: %s",
                            eloc_id, len(all_companies), all_companies)
            for cid in all_companies:
                await _broadcast(cid, {
                    "type": "workflow_removed",
                    "eloc_id": eloc_id,
                })

    # Internal subscribers (PRM-replica) mirror PRM-WPF: a hide is treated
    # the same as a remove — the card disappears from the operator's grid.
    await _internal_broadcast({
        "type": "workflow_removed",
        "scope": "internal",
        "eloc_id": eloc_id,
    })
