
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

MAX_RECONNECT_DELAY = 30
INITIAL_RECONNECT_DELAY = 2


_connections: dict[int, set[WebSocket]] = {}

_eloc_company_map: dict[str, int] = {}

_internal_connections: set[WebSocket] = set()


def _connection_summary() -> str:
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
    eloc_id = str(state.get("elocId", ""))
    company_id = state.get("companyId", 0)
    workflow_step = state.get("workflowStep", "") or ""
    status = state.get("status", "Pending") or "Pending"
    pricing_direction = state.get("pricingDirection", "Forward") or "Forward"
    workflow_complete = bool(state.get("workflowComplete", False))
    modified_at = state.get("modifiedAt")
    company_symbol = state.get("companySymbol") or state.get("symbol")

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
    msg_type = data.get("type", "unknown")
    eloc_id = data.get("eloc_id") or (data.get("workflow") or {}).get("eloc_id", "")

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
        return_exceptions=False,
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
                break
    except Exception as exc:
        logger.warning("INTERNAL WS initial state: FAILED: %s", exc)

    logger.info(
        "INTERNAL WS initial state COMPLETE: sent=%d, hidden=%d, failures=%d",
        count, skipped_hidden, failures,
    )



@router.websocket("/workflows")
async def websocket_workflows(websocket: WebSocket, token: str = ""):
    client_host = websocket.client.host if websocket.client else "unknown"
    logger.info("WS /workflows: incoming connection from %s", client_host)

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

    try:
        await _send_initial_state(company_id, websocket)
    except Exception as exc:
        logger.warning("WS /workflows: failed to send initial state to company_id=%s: %s", company_id, exc)

    try:
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



def _build_workflow_message(state: dict, source: str = "dts") -> dict:
    eloc_id = str(state.get("elocId", ""))
    company_id = state.get("companyId", 0)
    workflow_step = state.get("workflowStep", "")
    status = state.get("status", "Pending")
    modified_at = state.get("modifiedAt")
    pricing_direction = state.get("pricingDirection", "Forward")
    workflow_complete = state.get("workflowComplete", False)

    steps, can_remove = build_workflow_steps(
        workflow_step, status, pricing_direction, workflow_complete)

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
    count = 0
    skipped_hidden = 0
    skipped_other = 0

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
    has_tenant = bool(_connections)
    has_internal = bool(_internal_connections)
    if not has_tenant and not has_internal:
        logger.info("DTS WS resync: no connected clients (tenant or internal), skipping")
        return

    logger.info(
        "DTS WS resync: resyncing tenant=[%s] internal=[%s]",
        _connection_summary(), _internal_connection_summary(),
    )

    try:
        portal_states = await onprem.get_portal_eloc_states_included()
        logger.info("DTS WS resync: fetched %d included portal states", len(portal_states))
        tenant_sent = 0
        internal_sent = 0
        for state in portal_states:
            if state.get("workflowVisible") is False:
                continue
            company_id = state.get("companyId")

            if has_tenant and company_id and company_id in _connections:
                tenant_msg = _build_workflow_message(state, source="portal")
                await _broadcast(company_id, tenant_msg)
                tenant_sent += 1

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



def _get_dts_ws_url() -> str:
    parsed = urlparse(settings.onprem_base_url)
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    url = f"{ws_scheme}://{parsed.netloc}/ws/eloc"
    logger.debug("DealTermsServer WS URL: %s", url)
    return url


async def connect_dealterms_ws():
    ws_url = _get_dts_ws_url()
    reconnect_delay = INITIAL_RECONNECT_DELAY

    while True:
        dts_ws = None
        try:
            logger.info("DTS WS: connecting to %s", ws_url)
            dts_ws = await websockets.connect(ws_url)

            welcome = await dts_ws.recv()
            logger.info("DTS WS: connected, welcome: %s", str(welcome)[:500])

            identify_msg = json.dumps({
                "action": "identify",
                "userName": "portal-backend",
                "machineName": "3i-portal",
            })
            await dts_ws.send(identify_msg)
            logger.info("DTS WS: sent identify")

            reconnect_delay = INITIAL_RECONNECT_DELAY

            await _resync_all_clients()

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



async def _handle_state_changed(msg: dict):
    eloc_id = msg.get("elocId", "")
    source = msg.get("source", "dts")
    step = msg.get("step", "")
    msg_status = msg.get("status", "")
    logger.info("HANDLE state_changed: eloc_id=%s step=%s status=%s source=%s",
                eloc_id, step, msg_status, source)

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

    if not include:
        logger.info("HANDLE state_changed: eloc_id=%s include=false → triggering eloc_removed", eloc_id)
        await _handle_eloc_removed({"elocId": eloc_id})
        return

    if visible is False:
        logger.info("HANDLE state_changed: eloc_id=%s workflowVisible=false → suppressing broadcast", eloc_id)
        return

    if source == "portal":
        message = _build_workflow_message(state, source=source)
        logger.info("HANDLE state_changed: broadcasting workflow_update for portal ELOC %s to company_id=%s",
                     eloc_id, company_id)
        await _broadcast(int(company_id), message)

        internal_msg = _build_internal_workflow_message(state)
        await _internal_broadcast(internal_msg)
    else:
        logger.info("HANDLE state_changed: broadcasting shares_refresh for DTS ELOC %s to company_id=%s",
                     eloc_id, company_id)
        await _broadcast(int(company_id), {
            "type": "shares_refresh",
            "eloc_id": eloc_id,
            "source": "dts",
        })

    if source == "portal" and step == "VwapNotificationToCompany" and msg_status == "Pending":
        logger.info("HANDLE state_changed: VwapNotificationToCompany/Pending — triggering countersign SMS for %s", eloc_id)
        try:
            await _trigger_countersign_sms(eloc_id, state)
        except Exception as exc:
            logger.error("Countersign SMS trigger failed for %s: %s", eloc_id, exc, exc_info=True)


async def _trigger_countersign_sms(eloc_id: str, state: dict):
    from app.countersign.repository import has_pending_countersign, create_countersign_token, get_countersign_sms_enabled
    from app.countersign.sms import send_countersign_sms
    from app.users.repository import get_company_users_with_phone

    if await has_pending_countersign(eloc_id):
        logger.info("Countersign SMS already sent for %s, skipping", eloc_id)
        return

    company_id = state.get("companyId")
    company_name = state.get("companyName", "")
    if not company_id:
        logger.warning("No companyId in state for countersign SMS: %s", eloc_id)
        return

    sms_enabled = await get_countersign_sms_enabled(int(company_id))
    if not sms_enabled:
        logger.info("Countersign SMS not enabled for company %s (%s), skipping SMS",
                     company_id, company_name)
        return

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
    eloc_id = msg.get("elocId", "")
    company_id = msg.get("companyId")
    source = msg.get("source", "dts")
    logger.info("HANDLE eloc_added: eloc_id=%s company_id=%s source=%s", eloc_id, company_id, source)

    if eloc_id and company_id:
        _eloc_company_map[eloc_id] = int(company_id)
        logger.info("ELOC map: cached %s → company_id=%s (map size=%d)", eloc_id, company_id, len(_eloc_company_map))

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

    if source == "portal":
        internal_msg = _build_internal_workflow_message(state)
        await _internal_broadcast(internal_msg)


async def _handle_eloc_removed(msg: dict):
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
        all_companies = list(_connections.keys())
        logger.warning("HANDLE eloc_removed: no cached company_id for %s — broadcasting to ALL %d companies: %s",
                        eloc_id, len(all_companies), all_companies)
        for cid in all_companies:
            await _broadcast(cid, {
                "type": "workflow_removed",
                "eloc_id": eloc_id,
            })

    await _internal_broadcast({
        "type": "workflow_removed",
        "scope": "internal",
        "eloc_id": eloc_id,
    })


async def _handle_eloc_hidden(msg: dict):
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

    await _internal_broadcast({
        "type": "workflow_removed",
        "scope": "internal",
        "eloc_id": eloc_id,
    })
