import asyncio
import logging
from typing import List
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from src.tcbs.ws_equity import ws_equity_client
from src.tcbs.ws_deriv import ws_deriv_client

logger = logging.getLogger("dominus-investor.api.ws")
router = APIRouter()

# Danh sach cac ket noi dang active
equity_connections: List[WebSocket] = []
deriv_connections: List[WebSocket] = []

# Callback de forward tin nhan tu TCBS WS sang Client
async def forward_equity_message(data: dict):
    # Gui tin nhan toi tat ca cac client dang connect
    for connection in equity_connections[:]:
        try:
            await connection.send_json(data)
        except Exception:
            equity_connections.remove(connection)

async def forward_deriv_message(data: dict):
    for connection in deriv_connections[:]:
        try:
            await connection.send_json(data)
        except Exception:
            deriv_connections.remove(connection)

# Dang ky callback voi TCBS WS Clients
ws_equity_client.register_callback(forward_equity_message)
ws_deriv_client.register_callback(forward_deriv_message)

@router.websocket("/ws/market/equity")
async def ws_market_equity(websocket: WebSocket):
    await websocket.accept()
    equity_connections.append(websocket)
    logger.info("Client connected to Equity market WS feed.")
    
    # Kich hoat connection toi TCBS WS neu day la client dau tien connect
    if len(equity_connections) == 1:
        await ws_equity_client.start()
        
    try:
        while True:
            # Giu ket noi va nhan ping/pong neu can
            await websocket.receive_text()
    except WebSocketDisconnect:
        equity_connections.remove(websocket)
        logger.info("Client disconnected from Equity market WS feed.")
        if not equity_connections:
            await ws_equity_client.stop()

@router.websocket("/ws/market/deriv")
async def ws_market_deriv(websocket: WebSocket):
    await websocket.accept()
    deriv_connections.append(websocket)
    logger.info("Client connected to Derivatives market WS feed.")
    
    if len(deriv_connections) == 1:
        await ws_deriv_client.start()
        
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        deriv_connections.remove(websocket)
        logger.info("Client disconnected from Derivatives market WS feed.")
        if not deriv_connections:
            await ws_deriv_client.stop()
