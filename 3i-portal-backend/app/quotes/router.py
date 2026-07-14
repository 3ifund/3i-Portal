
import asyncio
import json
import logging
from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import websockets

from app.auth.jwt import decode_access_token
from app.config import settings

logger = logging.getLogger("portal.quotes")
router = APIRouter()

MAX_RECONNECT_DELAY = 30
INITIAL_RECONNECT_DELAY = 2


def _get_onprem_ws_url() -> str:
    parsed = urlparse(settings.onprem_base_url)
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    url = f"{ws_scheme}://{parsed.netloc}/ws/quotes"
    logger.debug("On-prem WS URL: %s", url)
    return url


async def _connect_and_subscribe(ws_url: str, symbol: str):
    onprem_ws = await websockets.connect(ws_url)
    welcome = await onprem_ws.recv()
    logger.info("WS /quotes: received welcome from on-prem: %s", welcome[:500])
    subscribe_msg = json.dumps({"symbol": symbol})
    logger.info("WS /quotes: subscribing to symbol=%s", symbol)
    await onprem_ws.send(subscribe_msg)
    return onprem_ws, welcome


@router.websocket("/quotes")
async def websocket_quotes(websocket: WebSocket, token: str = "", symbol: str = ""):
    client_host = websocket.client.host if websocket.client else "unknown"
    logger.info("WS /quotes connection from %s", client_host)

    if not token:
        logger.warning("WS /quotes: no token provided from %s", client_host)
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    try:
        payload = decode_access_token(token)
        logger.info("WS /quotes: JWT valid, user_id=%s company_id=%s",
                     payload.get("user_id"), payload.get("company_id"))
    except Exception as exc:
        logger.warning("WS /quotes: JWT validation failed from %s: %s", client_host, exc)
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    requested = (symbol or "").strip().upper()
    role = payload.get("role")
    jwt_symbol = payload.get("company_symbol")
    symbol = requested if (requested and role == "admin") else jwt_symbol
    if not symbol:
        logger.warning("WS /quotes: no symbol resolved (requested=%s, role=%s, jwt_symbol=%s) for user=%s",
                       requested, role, jwt_symbol, payload.get("user_id"))
        await websocket.close(code=4002, reason="No symbol")
        return

    logger.info("WS /quotes: streaming symbol=%s (requested=%s, role=%s, user=%s)",
                symbol, requested or "none", role, payload.get("user_id"))

    await websocket.accept()
    logger.info("WS /quotes: connection accepted for symbol=%s", symbol)

    ws_url = _get_onprem_ws_url()
    client_disconnected = False

    client_msg_queue = asyncio.Queue()

    async def listen_client():
        nonlocal client_disconnected
        try:
            while True:
                data = await websocket.receive_text()
                logger.debug("WS /quotes: client→on-prem: %s", data[:500])
                await client_msg_queue.put(data)
        except WebSocketDisconnect:
            client_disconnected = True
            logger.info("WS /quotes: client disconnected (symbol=%s)", symbol)
        except Exception as exc:
            client_disconnected = True
            logger.warning("WS /quotes: client listener error: %s", exc)

    client_task = asyncio.create_task(listen_client())

    try:
        reconnect_delay = INITIAL_RECONNECT_DELAY

        while not client_disconnected:
            onprem_ws = None
            try:
                logger.info("WS /quotes: connecting to on-prem at %s", ws_url)
                onprem_ws, welcome = await _connect_and_subscribe(ws_url, symbol)
                logger.info("WS /quotes: on-prem WS connected for symbol=%s", symbol)

                reconnect_delay = INITIAL_RECONNECT_DELAY

                await websocket.send_text(welcome)

                msg_count = 0
                async for message in onprem_ws:
                    if client_disconnected:
                        break

                    msg_count += 1
                    if msg_count <= 5 or msg_count % 100 == 0:
                        logger.debug("WS /quotes: on-prem→client msg #%d: %s", msg_count, message[:500])
                    await websocket.send_text(message)

                    while not client_msg_queue.empty():
                        client_data = client_msg_queue.get_nowait()
                        await onprem_ws.send(client_data)

                if not client_disconnected:
                    logger.warning("WS /quotes: on-prem WS closed for symbol=%s, will reconnect in %ds",
                                   symbol, reconnect_delay)
                    try:
                        await websocket.send_text(json.dumps({
                            "type": "status",
                            "message": "Quote feed reconnecting...",
                            "connected": False,
                        }))
                    except Exception:
                        break

            except (ConnectionRefusedError, OSError, websockets.exceptions.WebSocketException) as exc:
                if client_disconnected:
                    break
                logger.warning("WS /quotes: on-prem connection failed for symbol=%s: %s (retry in %ds)",
                               symbol, exc, reconnect_delay)
                try:
                    await websocket.send_text(json.dumps({
                        "type": "status",
                        "message": "Quote feed unavailable, retrying...",
                        "connected": False,
                    }))
                except Exception:
                    break

            except Exception as exc:
                if client_disconnected:
                    break
                logger.error("WS /quotes: unexpected error for symbol=%s: %s (retry in %ds)",
                             symbol, exc, reconnect_delay, exc_info=True)

            finally:
                if onprem_ws:
                    try:
                        await onprem_ws.close()
                    except Exception:
                        pass

            if client_disconnected:
                break

            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, MAX_RECONNECT_DELAY)

    except WebSocketDisconnect:
        logger.info("WS /quotes: client disconnected during reconnect loop (symbol=%s)", symbol)
    except Exception as exc:
        logger.error("WS /quotes: fatal error for symbol=%s: %s", symbol, exc, exc_info=True)
    finally:
        client_task.cancel()
        logger.info("WS /quotes: session ended for symbol=%s", symbol)
