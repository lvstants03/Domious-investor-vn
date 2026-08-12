import asyncio
import json
import logging
import websockets
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
        # Neu su dung dummy_api_key, ta se gia lap nhan event realtime
        if settings.TCBS_API_KEY == "dummy_api_key":
            logger.info("MOCK WS EQUITY: Bat dau gia lap WebSocket feed co so...")
            import random
            symbols = ["FPT", "VNM", "HPG", "VIC", "VHM"]
            while self._running:
                await asyncio.sleep(random.uniform(1.0, 5.0))
                symbol = random.choice(symbols)
                price_change = random.choice([-500, -100, 0, 100, 500])
                base_price = 128500.0 if symbol == "FPT" else (74200.0 if symbol == "VNM" else 28000.0)
                price = base_price + price_change
                volume = random.randint(1, 50) * 100
                
                event_data = {
                    "event": "match",
                    "symbol": symbol,
                    "price": price,
                    "volume": volume,
                    "time": "14:29:00",
                    "side": random.choice(["BUY", "SELL"])
                }
                
                for callback in self._callbacks:
                    try:
                        await callback(event_data)
                    except Exception as e:
                        logger.error("Loi trong callback WS Equity: %s", str(e))
            return

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
