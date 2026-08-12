import asyncio
import json
import logging
import websockets
from typing import Dict, Any, List, Callable, Awaitable
from src.config import settings
from src.tcbs.auth import auth_provider

logger = logging.getLogger("dominus-investor.tcbs.ws_deriv")

class TCBSDerivWSClient:
    def __init__(self):
        self.uri = settings.TCBS_BASE_URL.replace("http://", "ws://").replace("https://", "wss://") + "/ws/derivatives"
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
        # Neu su dung dummy_api_key, ta se gia lap nhan event realtime phai sinh
        if settings.TCBS_API_KEY == "dummy_api_key":
            logger.info("MOCK WS DERIV: Bat dau gia lap WebSocket feed phai sinh...")
            import random
            symbols = ["VN30F2608", "VN30F2609"]
            while self._running:
                await asyncio.sleep(random.uniform(0.5, 3.0))
                symbol = random.choice(symbols)
                price_change = random.choice([-1.5, -0.5, 0.0, 0.5, 1.5])
                base_price = 1320.0
                price = base_price + price_change
                volume = random.randint(1, 10)
                
                event_data = {
                    "event": "deriv_match",
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
                        logger.error("Loi trong callback WS Deriv: %s", str(e))
            return

        while self._running:
            try:
                token = await auth_provider.get_token()
                logger.info("Connecting to TCBS Derivatives WebSocket...")
                async with websockets.connect(f"{self.uri}?token={token}") as ws:
                    self._websocket = ws
                    logger.info("Connected to TCBS Derivatives WebSocket.")
                    
                    async for message in ws:
                        if not self._running:
                            break
                        try:
                            data = json.loads(message)
                            for callback in self._callbacks:
                                await callback(data)
                        except Exception as e:
                            logger.error("Loi khi xu ly tin nhan WS phai sinh: %s", str(e))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Loi ket noi WebSocket phai sinh: %s. Reconnecting in 5s...", str(e))
                await asyncio.sleep(5)

ws_deriv_client = TCBSDerivWSClient()
