import asyncio
import logging
import json
from typing import List
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from src.tcbs.socket_manager import socket_manager
from src.data_pipeline.big_order_tracker import big_order_tracker

logger = logging.getLogger("dominus-investor.api.ws")
router = APIRouter()

# Danh sach cac ket noi dang active
equity_connections: List[WebSocket] = []
deriv_connections: List[WebSocket] = []

# 1. FORWARD THESIS (Bảng giá & Khớp lệnh thời gian thực)
async def forward_thesis_message(message: str):
    if message.startswith("d|s|") or message.startswith("s|") or ("|" in message and "{" in message):
        try:
            # Tach lay phan json payload o phan cuoi cua pipe
            json_part = message[message.find("{"):message.rfind("}")+1] if "{" in message and "}" in message else ""
            if json_part:
                data = json.loads(json_part)
                
                # Nạp tick vào BigOrderTracker nếu là tin khớp lệnh lớn
                try:
                    sym = str(data.get("symbol") or data.get("s") or data.get("sym") or "").upper()
                    price = float(data.get("matchPrice") or data.get("price") or data.get("p") or data.get("lastPrice", 0))
                    qty = int(data.get("matchVol") or data.get("volume") or data.get("v") or data.get("qtty") or data.get("matchVolume", 0))
                    side = str(data.get("side") or data.get("action") or data.get("a") or "BUY").upper()
                    from datetime import datetime
                    t_str = data.get("time") or data.get("t") or datetime.now().strftime("%H:%M:%S")
                    if sym and price > 0 and qty > 0:
                        big_order_tracker.add_order(t_str, sym, price, qty, side)
                except Exception:
                    pass

                payload = {"type": "THESIS_TICK", "data": data}
                for connection in equity_connections[:]:
                    try:
                        await connection.send_json(payload)
                    except Exception:
                        if connection in equity_connections:
                            equity_connections.remove(connection)
                return
        except Exception:
            pass

    for connection in equity_connections[:]:
        try:
            await connection.send_text(message)
        except Exception:
            if connection in equity_connections:
                equity_connections.remove(connection)

# 2. FORWARD OURANOS (Nến C001, Cung cầu C002S60, Khối ngoại C002S900)
async def forward_ouranos_message(message: str):
    try:
        if "|" in message:
            parts = message.split("|", 2)
            if len(parts) == 3:
                code = parts[0].strip()
                sym = parts[1].strip().upper()
                data = json.loads(parts[2])
                
                payload = {
                    "type": "OURANOS_UPDATE",
                    "code": code,
                    "symbol": sym,
                    "data": data
                }

                # Broadcast cho cả kênh Equity và Deriv
                all_conns = list(set(equity_connections + deriv_connections))
                for connection in all_conns:
                    try:
                        await connection.send_json(payload)
                    except Exception:
                        if connection in equity_connections:
                            equity_connections.remove(connection)
                        if connection in deriv_connections:
                            deriv_connections.remove(connection)
                return
    except Exception:
        pass
        
    for connection in deriv_connections[:]:
        try:
            await connection.send_text(message)
        except Exception:
            if connection in deriv_connections:
                deriv_connections.remove(connection)

# 3. FORWARD AITHER (Cập nhật trạng thái lệnh cơ sở STOCK_ORDER)
async def forward_aither_message(message: str):
    try:
        if "message_proto|STOCK_ORDER|" in message:
            json_str = message.split("message_proto|STOCK_ORDER|", 1)[1]
            data = json.loads(json_str)
            payload = {
                "type": "STOCK_ORDER_UPDATE",
                "data": data
            }
            for connection in equity_connections[:]:
                try:
                    await connection.send_json(payload)
                except Exception:
                    if connection in equity_connections:
                        equity_connections.remove(connection)
            return
    except Exception:
        pass

# Đăng ký callbacks với TCBS Socket Manager
socket_manager.thesis_client.register_callback(forward_thesis_message)
socket_manager.ouranos_client.register_callback(forward_ouranos_message)
socket_manager.aither_client.register_callback(forward_aither_message)

@router.websocket("/ws/market/equity")
async def ws_market_equity(websocket: WebSocket):
    await websocket.accept()
    equity_connections.append(websocket)
    logger.info("Client connected to Equity market WS feed.")
    
    thesis_client = socket_manager.thesis_client
    if len(equity_connections) == 1 and thesis_client.status == "DISCONNECTED":
        await thesis_client.start()
        
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in equity_connections:
            equity_connections.remove(websocket)
        logger.info("Client disconnected from Equity market WS feed.")

@router.websocket("/ws/market/deriv")
async def ws_market_deriv(websocket: WebSocket):
    await websocket.accept()
    deriv_connections.append(websocket)
    logger.info("Client connected to Derivatives market WS feed.")
    
    ouranos_client = socket_manager.ouranos_client
    if len(deriv_connections) == 1 and ouranos_client.status == "DISCONNECTED":
        await ouranos_client.start()
        
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in deriv_connections:
            deriv_connections.remove(websocket)
        logger.info("Client disconnected from Derivatives market WS feed.")
