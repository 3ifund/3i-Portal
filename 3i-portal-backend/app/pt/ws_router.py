import asyncio
import logging
from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import websockets

from app.auth.jwt import decode_access_token
from app.config import settings

logger = logging.getLogger("portal.pt.ws")
ws_router = APIRouter()

MAX_RECONNECT_DELAY = 30
INITIAL_RECONNECT_DELAY = 2


def _dts_ws_url() -> str:
    parsed = urlparse(settings.onprem_base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{parsed.netloc}/ws/pt"


@ws_router.websocket("/pt")
async def websocket_pt(websocket: WebSocket, token: str = ""):
    client_host = websocket.client.host if websocket.client else "unknown"
    logger.info("WS /pt connection from %s", client_host)

    if not token:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return
    try:
        payload = decode_access_token(token)
    except Exception as exc:
        logger.warning("WS /pt: JWT validation failed from %s: %s", client_host, exc)
        await websocket.close(code=4001, reason="Invalid or expired token")
        return
    if payload.get("role") != "admin":
        logger.warning("WS /pt: non-admin user=%s rejected", payload.get("user_id"))
        await websocket.close(code=4003, reason="Admin required")
        return

    await websocket.accept()
    logger.info("WS /pt: accepted for user=%s", payload.get("user_id"))
    ws_url = _dts_ws_url()

    client_disconnected = False

    async def listen_client():
        nonlocal client_disconnected
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            client_disconnected = True
        except Exception:
            client_disconnected = True

    client_task = asyncio.create_task(listen_client())

    reconnect_delay = INITIAL_RECONNECT_DELAY
    try:
        while not client_disconnected:
            onprem_ws = None
            try:
                logger.info("WS /pt: connecting to DTS at %s", ws_url)
                onprem_ws = await websockets.connect(ws_url)
                logger.info("WS /pt: DTS connected")
                reconnect_delay = INITIAL_RECONNECT_DELAY
                async for message in onprem_ws:
                    if client_disconnected:
                        break
                    await websocket.send_text(message)
                if not client_disconnected:
                    logger.warning("WS /pt: DTS WS closed, reconnecting in %ds", reconnect_delay)
            except (ConnectionRefusedError, OSError, websockets.exceptions.WebSocketException) as exc:
                if client_disconnected:
                    break
                logger.warning("WS /pt: DTS connect failed: %s (retry in %ds)", exc, reconnect_delay)
            except Exception as exc:
                if client_disconnected:
                    break
                logger.error("WS /pt: unexpected error: %s (retry in %ds)", exc, reconnect_delay, exc_info=True)
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
        pass
    finally:
        client_task.cancel()
        logger.info("WS /pt: session ended for user=%s", payload.get("user_id"))
