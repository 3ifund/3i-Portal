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


def _register(company_id: int, ws: WebSocket):
    if company_id not in _connections:
        _connections[company_id] = set()
    _connections[company_id].add(ws)
    logger.info("WS /workflows: registered client for company_id=%s (%d total)",
                company_id, len(_connections[company_id]))


def _unregister(company_id: int, ws: WebSocket):
    if company_id in _connections:
        _connections[company_id].discard(ws)
        if not _connections[company_id]:
            del _connections[company_id]
    logger.info("WS /workflows: unregistered client for company_id=%s", company_id)


async def _broadcast(company_id: int, data: dict):
    """Send a message to all connected browser clients for a company."""
    clients = _connections.get(company_id, set()).copy()
    if not clients:
        return

    message = json.dumps(data)
    dead = []
    for ws in clients:
        try:
            await ws.send_text(message)
        except Exception:
            dead.append(ws)

    for ws in dead:
        _unregister(company_id, ws)

    if clients:
        logger.debug("WS /workflows: broadcast to %d clients for company_id=%s",
                      len(clients) - len(dead), company_id)


# ---- WebSocket Endpoint (browser clients connect here) ----

@router.websocket("/workflows")
async def websocket_workflows(websocket: WebSocket, token: str = ""):
    """
    WebSocket for real-time workflow state updates.
    Frontend connects with ?token=JWT. Backend relays workflow_update
    and workflow_removed messages from DealTermsServer.
    """
    client_host = websocket.client.host if websocket.client else "unknown"
    logger.info("WS /workflows connection from %s", client_host)

    # Validate JWT token
    if not token:
        logger.warning("WS /workflows: no token provided from %s", client_host)
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    try:
        payload = decode_access_token(token)
        logger.info("WS /workflows: JWT valid, user_id=%s company_id=%s",
                     payload.get("user_id"), payload.get("company_id"))
    except Exception as exc:
        logger.warning("WS /workflows: JWT validation failed from %s: %s", client_host, exc)
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    company_id = payload.get("company_id")
    if not company_id:
        logger.warning("WS /workflows: no company_id in JWT for user=%s", payload.get("user_id"))
        await websocket.close(code=4002, reason="No company assigned")
        return

    company_id = int(company_id)
    await websocket.accept()
    _register(company_id, websocket)

    # Send current workflow state on connect
    try:
        await _send_initial_state(company_id, websocket)
    except Exception as exc:
        logger.warning("WS /workflows: failed to send initial state: %s", exc)

    try:
        # Keep connection alive — just wait for client disconnect
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("WS /workflows: client disconnected (company_id=%s)", company_id)
    except Exception as exc:
        logger.warning("WS /workflows: connection error: %s", exc)
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

    steps, can_remove = build_workflow_steps(workflow_step, status)

    # Cache the eloc→company mapping for routing eloc_removed events
    if eloc_id and company_id:
        _eloc_company_map[eloc_id] = int(company_id)

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
        },
    }


async def _send_initial_state(company_id: int, ws: WebSocket):
    """Send all included workflows (DTS + portal) to a newly connected browser client."""
    count = 0

    # DTS upstream workflows
    states = await onprem.get_included_eloc_states()
    for state in states:
        if state.get("companyId") == company_id:
            message = _build_workflow_message(state, source="dts")
            await ws.send_text(json.dumps(message))
            count += 1

    # Portal-initiated workflows
    try:
        portal_states = await onprem.get_portal_eloc_states_included()
        for state in portal_states:
            if state.get("companyId") == company_id:
                message = _build_workflow_message(state, source="portal")
                await ws.send_text(json.dumps(message))
                count += 1
    except Exception as exc:
        logger.warning("WS /workflows: failed to fetch portal states: %s", exc)

    logger.info("WS /workflows: sent %d initial workflows to company_id=%s", count, company_id)


async def _resync_all_clients():
    """
    Broadcast current state to all connected browser clients.
    Called when DealTermsServer WebSocket reconnects to catch any missed changes.
    """
    if not _connections:
        return

    logger.info("DTS WS: resyncing all connected clients (%d companies)", len(_connections))

    # DTS upstream workflows
    states = await onprem.get_included_eloc_states()
    for state in states:
        company_id = state.get("companyId")
        if company_id and company_id in _connections:
            message = _build_workflow_message(state, source="dts")
            await _broadcast(company_id, message)

    # Portal-initiated workflows
    try:
        portal_states = await onprem.get_portal_eloc_states_included()
        for state in portal_states:
            company_id = state.get("companyId")
            if company_id and company_id in _connections:
                message = _build_workflow_message(state, source="portal")
                await _broadcast(company_id, message)
    except Exception as exc:
        logger.warning("DTS WS: failed to fetch portal states during resync: %s", exc)


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
                logger.debug("DTS WS: received %s: %s", msg_type, str(raw_message)[:500])

                if msg_type == "state_changed":
                    await _handle_state_changed(msg)
                elif msg_type == "eloc_added":
                    await _handle_eloc_added(msg)
                elif msg_type == "eloc_removed":
                    await _handle_eloc_removed(msg)
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
    logger.info("DTS WS: state_changed eloc_id=%s step=%s status=%s source=%s",
                eloc_id, msg.get("step"), msg.get("status"), source)

    # Fetch full state — use portal endpoint if source is portal
    if source == "portal":
        state = await onprem.get_portal_eloc_state_by_id(eloc_id)
    else:
        state = await onprem.get_eloc_state_by_id(eloc_id)

    if not state:
        logger.warning("DTS WS: could not fetch state for eloc_id=%s (source=%s)", eloc_id, source)
        return

    company_id = state.get("companyId")
    if not company_id:
        return

    # Check if still included
    if not state.get("include", True):
        await _handle_eloc_removed({"elocId": eloc_id})
        return

    message = _build_workflow_message(state, source=source)
    await _broadcast(int(company_id), message)


async def _handle_eloc_added(msg: dict):
    """
    Handle eloc_added from DealTermsServer.
    Fetch full state via REST, then broadcast to browser clients.
    Routes to portal or DTS REST endpoint based on source field.
    """
    eloc_id = msg.get("elocId", "")
    company_id = msg.get("companyId")
    source = msg.get("source", "dts")
    logger.info("DTS WS: eloc_added eloc_id=%s company_id=%s source=%s", eloc_id, company_id, source)

    # Cache the mapping
    if eloc_id and company_id:
        _eloc_company_map[eloc_id] = int(company_id)

    # Fetch full state — use portal endpoint if source is portal
    if source == "portal":
        state = await onprem.get_portal_eloc_state_by_id(eloc_id)
    else:
        state = await onprem.get_eloc_state_by_id(eloc_id)

    if not state:
        logger.warning("DTS WS: could not fetch state for new eloc_id=%s (source=%s)", eloc_id, source)
        return

    company_id = state.get("companyId", company_id)
    if not company_id:
        return

    message = _build_workflow_message(state, source=source)
    await _broadcast(int(company_id), message)


async def _handle_eloc_removed(msg: dict):
    """
    Handle eloc_removed from DealTermsServer.
    Broadcast removal to browser clients.
    """
    eloc_id = msg.get("elocId", "")
    company_id = _eloc_company_map.pop(eloc_id, None)
    logger.info("DTS WS: eloc_removed eloc_id=%s company_id=%s", eloc_id, company_id)

    if company_id:
        await _broadcast(company_id, {
            "type": "workflow_removed",
            "eloc_id": eloc_id,
        })
    else:
        # No cached company_id — broadcast to all companies
        logger.warning("DTS WS: no cached company_id for removed eloc_id=%s, broadcasting to all", eloc_id)
        for cid in list(_connections.keys()):
            await _broadcast(cid, {
                "type": "workflow_removed",
                "eloc_id": eloc_id,
            })
