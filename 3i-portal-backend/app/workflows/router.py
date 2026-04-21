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
from app.onprem import client as onprem
import uuid as _uuid

logger = logging.getLogger("portal.workflows")
router = APIRouter()

# Reconnect settings
MAX_RECONNECT_DELAY = 30  # seconds
INITIAL_RECONNECT_DELAY = 2  # seconds

# ---- Connection Manager (browser clients) ----

# Maps company_id → set of connected browser WebSockets
_connections: dict[int, set[WebSocket]] = {}

# Maps eloc_id → company_id for routing eloc_removed events
_eloc_company_map: dict[str, int] = {}


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
    Called when DealTermsServer WebSocket reconnects to catch any missed changes.
    """
    if not _connections:
        logger.info("DTS WS resync: no connected clients, skipping")
        return

    logger.info("DTS WS resync: resyncing %s", _connection_summary())

    # Portal-initiated workflows only — 12-step ELOCs are not workflow cards
    try:
        portal_states = await onprem.get_portal_eloc_states_included()
        logger.info("DTS WS resync: fetched %d included portal states", len(portal_states))
        sent = 0
        for state in portal_states:
            if state.get("workflowVisible") is False:
                continue
            company_id = state.get("companyId")
            if company_id and company_id in _connections:
                message = _build_workflow_message(state, source="portal")
                await _broadcast(company_id, message)
                sent += 1
        logger.info("DTS WS resync COMPLETE: sent %d workflow updates", sent)
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


async def connect_dealterms_ws():
    """
    Background task: connect to DealTermsServer's ws/eloc WebSocket.
    Receives state_changed, eloc_added, eloc_removed events and relays
    them to connected browser clients. Reconnects with exponential backoff.
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

    # Trigger countersign SMS when Portal ELOC reaches VwapNotificationToCompany/Pending
    if source == "portal" and step == "VwapNotificationToCompany" and msg_status == "Pending":
        logger.info("HANDLE state_changed: VwapNotificationToCompany/Pending — triggering countersign SMS for %s", eloc_id)
        try:
            await _trigger_countersign_sms(eloc_id, state)
        except Exception as exc:
            logger.error("Countersign SMS trigger failed for %s: %s", eloc_id, exc, exc_info=True)


async def _trigger_countersign_sms(eloc_id: str, state: dict):
    """Send SMS countersign links to company signatories with phone numbers."""
    from app.countersign.repository import has_pending_countersign, create_countersign_token, get_countersign_sms_enabled
    from app.countersign.sms import send_countersign_sms
    from app.purchase_notices.pg_repository import get_company_signatories

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

    # Get signatories with phone numbers
    signatories = await get_company_signatories(int(company_id))
    with_phone = [s for s in signatories if s.get("phone_number", "").strip()]

    if not with_phone:
        logger.info("No signatories with phone numbers for company %s, Portal UI countersign only", company_id)
        return

    group_id = str(_uuid.uuid4())
    logger.info("Sending countersign SMS for %s to %d signatories, group=%s",
                eloc_id, len(with_phone), group_id)

    for sig in with_phone:
        try:
            token_result = await create_countersign_token(
                group_id=group_id,
                signatory_id=sig["id"],
                signatory_name=sig["name"],
                signatory_phone=sig["phone_number"],
                company_name=company_name,
                eloc_id=eloc_id,
            )
            full_url = f"{settings.approval_base_url}{token_result['url']}"
            await send_countersign_sms(sig["phone_number"], company_name, full_url)
            logger.info("Countersign SMS sent to %s (%s) for %s",
                        sig["name"], sig["phone_number"], eloc_id)
        except Exception as sms_exc:
            logger.error("Countersign SMS failed for %s (%s): %s",
                         sig["name"], sig["phone_number"], sms_exc)


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
