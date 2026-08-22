import asyncio
import json
import logging
import websockets
from datetime import datetime
from typing import Dict, Any, List, Callable, Awaitable
from src.config import settings
from src.tcbs.auth import auth_provider

logger = logging.getLogger("dominus-investor.tcbs.ws_equity")

class TCBSEquityWSClient:
    def __init__(self):
        self.uri = settings.TCBS_BASE_URL.replace("http://", "ws://").replace("https://", "wss://") + "/ws/equity"
        self._callbacks: List[Callable[[Dict[str, Any]], Awaitable[None]]] = []
        self._running = False
        self._websocket = None
        self._task = None

    def register_callback(self, callback: Callable[[Dict[str, Any]], Awaitable[None]]):
        self._callbacks.append(callback)

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self):
        self._running = False
        if self._websocket:
            await self._websocket.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self):


        while self._running:
            try:
                token = await auth_provider.get_token()
                logger.info("Connecting to TCBS Equity WebSocket...")
                async with websockets.connect(f"{self.uri}?token={token}") as ws:
                    self._websocket = ws
                    logger.info("Connected to TCBS Equity WebSocket.")
                    
                    # Dang ky subscription danh sach ma neu can (tuy dac ta)
                    # Example: await ws.send(json.dumps({"action": "subscribe", "symbols": ["FPT", "VNM"]}))
                    
                    async for message in ws:
                        if not self._running:
                            break
                        try:
                            data = json.loads(message)
                            # Xu ly tin nhan khop lenh realtime qua big_order_tracker
                            if isinstance(data, dict):
                                sym = data.get("symbol") or data.get("s")
                                price = float(data.get("price") or data.get("p", 0))
                                qty = int(data.get("volume") or data.get("v") or data.get("qty", 0))
                                side = data.get("side") or data.get("type", "B")
                                t_str = data.get("time") or datetime.now().strftime("%H:%M:%S")
                                if sym and price > 0 and qty > 0:
                                    from src.data_pipeline.big_order_tracker import big_order_tracker
                                    big_order_tracker.add_order(t_str, sym, price, qty, side)

                            for callback in self._callbacks:
                                await callback(data)
                        except Exception as e:
                            logger.error("Loi khi xu ly tin nhan WS: %s", str(e))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Loi ket noi WebSocket Equity: %s. Reconnecting in 5s...", str(e))
                await asyncio.sleep(5)

ws_equity_client = TCBSEquityWSClient()
