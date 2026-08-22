import asyncio
import json
import logging
import base64
import time
from typing import Dict, Any, List, Callable, Awaitable, Optional
import websockets
from src.config import settings
from src.tcbs.auth import auth_provider

logger = logging.getLogger("dominus-investor.tcbs.socket_manager")

class TCBSSocketClient:
    def __init__(self, name: str, endpoint: str, ping_msg: str, client_type: str):
        self.name = name
        self.endpoint = endpoint
        self.ping_msg = ping_msg
        self.client_type = client_type  # "thesis", "aither", "ouranos"
        self.uri = settings.TCBS_BASE_URL.replace("http://", "ws://").replace("https://", "wss://") + endpoint
        
        self.status = "DISCONNECTED" # CONNECTED, CONNECTING, RECONNECTING, AUTHENTICATED, DISCONNECTED
        self.msg_count = 0
        self.reconnect_count = 0
        self.start_time = 0
        self.subscribed_topics = []
        self.logs: List[Dict[str, Any]] = [] # Buffer for last 100 log messages
        
        self._running = False
        self._websocket = None
        self._task = None
        self._heartbeat_task = None
        self._callbacks: List[Callable[[str], Awaitable[None]]] = []
        
    def register_callback(self, callback: Callable[[str], Awaitable[None]]):
        self._callbacks.append(callback)
        
    def add_log(self, direction: str, message: str):
        self.logs.append({
            "time": time.strftime("%H:%M:%S"),
            "direction": direction, # "SENT" or "RECV" or "INFO" or "ERROR"
            "message": message
        })
        if len(self.logs) > 100:
            self.logs.pop(0)

    async def start(self):
        if self._running:
            return
        self._running = True
        self.start_time = time.time()
        self._task = asyncio.create_task(self._run_loop())
        self.add_log("INFO", f"Socket {self.name} started.")

    async def stop(self):
        self._running = False
        self.status = "DISCONNECTED"
        if self._websocket:
            try:
                await self._websocket.close()
            except Exception:
                pass
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.add_log("INFO", f"Socket {self.name} stopped.")

    async def send_message(self, message: str):
        if self._websocket and self.status in ["CONNECTED", "AUTHENTICATED"]:
            await self._websocket.send(message)
            self.add_log("SENT", message)
        else:
            self.add_log("ERROR", f"Cannot send message, socket {self.name} is not connected.")

    async def _send_heartbeat(self):
        while self._running and self._websocket and self.status == "AUTHENTICATED":
            try:
                await asyncio.sleep(2)
                if not self._running or self.status != "AUTHENTICATED" or not self._websocket:
                    break
                await self._websocket.send(self.ping_msg)
                self.add_log("SENT", self.ping_msg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                # Chi log khi van dang o trang thai AUTHENTICATED
                if self.status == "AUTHENTICATED":
                    self.add_log("ERROR", f"Heartbeat error: {str(e)}")
                break

    async def _run_loop(self):
        attempt = 0
        while self._running:
            self.status = "CONNECTING"
            self.add_log("INFO", f"Connecting to {self.uri}...")
            try:
                # Disable auto-ping RFC 6455
                async with websockets.connect(self.uri, ping_interval=None, ping_timeout=None) as ws:
                    self._websocket = ws
                    self.status = "CONNECTED"
                    self.add_log("INFO", "TCP Connection established. Authenticating...")
                    
                    # 1. LAY JWT TOKEN
                    try:
                        token = await auth_provider.get_token()
                        # Validate JWT format (3 phan tach boi dau cham)
                        if not token or len(token.split(".")) != 3:
                            raise ValueError("Token JWT khong dung dinh dang hop le (header.payload.signature).")
                    except Exception as e:
                        self.add_log("ERROR", f"Chua the xac thuc vi thieu token hoac token khong hop le: {str(e)}")
                        self.status = "DISCONNECTED"
                        await asyncio.sleep(10)
                        continue
                    
                    # 2. TAO AUTH PAYLOAD THEO CHUAN TUNG LOAI SOCKET
                    if self.client_type == "thesis":
                        # THESIS: Raw JWT pipe format
                        auth_msg = f"d|a||{token}"
                    elif self.client_type == "ouranos":
                        # OURANOS: Raw JWT pipe format tuong tu Thesis
                        auth_msg = f"d|a||{token}"
                    elif self.client_type == "aither":
                        # AITHER: Base64 encode cua json {"jwt":"token"} khong co space
                        auth_payload = json.dumps({"jwt": token}, separators=(',', ':'))
                        b64_jwt_payload = base64.b64encode(auth_payload.encode('utf-8')).decode('utf-8')
                        auth_msg = f"authenticate|{b64_jwt_payload}"
                    else:
                        auth_msg = f"d|a||{token}"
                        
                    await ws.send(auth_msg)
                    self.add_log("SENT", auth_msg)
                    
                    # 3. NHAN VA XAC THUC PHAN HOI (Handle pingTimeout truoc response authenticate)
                    is_authenticated = False
                    
                    # Cho doc toi da 3 message dau tien de tim response auth
                    for _ in range(3):
                        try:
                            resp = await asyncio.wait_for(ws.recv(), timeout=5.0)
                            self.add_log("RECV", resp)
                            
                            # Kiem tra success theo dac ta
                            if self.client_type == "aither":
                                if resp.startswith("pingTimeout|"):
                                    # Server Aither gui pingTimeout truoc, phan hoi ngay ping|1 roi doc tiep
                                    await ws.send("ping|1")
                                    self.add_log("SENT", "ping|1")
                                    continue
                                if resp.startswith("authenticate|") and '"success":true' in resp:
                                    is_authenticated = True
                                    break
                                if "error" in resp.lower():
                                    break
                            elif self.client_type == "ouranos":
                                if resp.startswith("d|33") or resp.startswith("d|0") or resp.startswith("d|a") or ("d|" in resp and "error" not in resp.lower()):
                                    is_authenticated = True
                                    break
                                if "false" in resp:
                                    break
                            else: # thesis
                                if resp.startswith("d|33") or resp.startswith("d|0") or resp.startswith("d|a") or ("d|" in resp and "error" not in resp.lower()):
                                    is_authenticated = True
                                    break
                        except asyncio.TimeoutError:
                            break
                    
                    if is_authenticated:
                        self.status = "AUTHENTICATED"
                        self.add_log("INFO", "Authentication SUCCESS. Heartbeat started.")
                        
                        # Kich hoat Heartbeat
                        self._heartbeat_task = asyncio.create_task(self._send_heartbeat())
                        attempt = 0
                        
                        # 4. DANG KY KENH (SUBSCRIBE) THEO DAC TA
                        if self.client_type == "aither":
                            # Aither: subscribe topic STOCK_ORDER (base64 cua {"topic":"STOCK_ORDER"})
                            sub_payload = base64.b64encode(json.dumps({"topic": "STOCK_ORDER"}, separators=(',', ':')).encode('utf-8')).decode('utf-8')
                            sub_msg = f"subscribe|{sub_payload}"
                            if "STOCK_ORDER" not in self.subscribed_topics:
                                self.subscribed_topics.append("STOCK_ORDER")
                            await ws.send(sub_msg)
                            self.add_log("SENT", sub_msg)

                        elif self.client_type == "ouranos":
                            # Ouranos: d|st|C001+C002S60+C002S900|TICKERS
                            if not self.subscribed_topics:
                                self.subscribed_topics.append("d|st|C001+C002S60+C002S900|FPT,HPG,VNM,VIC,VHM,SSI,TCB,MWG,GEE,VN30")
                            for topic in self.subscribed_topics:
                                await ws.send(topic)
                                self.add_log("SENT", topic)

                        elif self.client_type == "thesis":
                            # Thesis: d|s|tk|bp+bi+tm+mp+op+fe|TICKERS
                            if not self.subscribed_topics:
                                default_syms = "FPT,HPG,VNM,VIC,VHM,VCB,SSI,TCB,MWG,MBB,STB,GEE,NVL,DXG,SHB,VND,DIG,PDR,VRE,ACB,VPB,MSN,GAS,BID,CTG,KBC,DGC,GEX,VIX,SHS"
                                self.subscribed_topics.append(f"d|s|tk|bp+bi+tm+mp+op+fe|{default_syms}")
                            for topic in self.subscribed_topics:
                                await ws.send(topic)
                                self.add_log("SENT", topic)

                        # 5. VONG LAP NHAN DU LIEU (MESSAGE RECEIVING LOOP)
                        async for message in ws:
                            if not self._running:
                                break
                            self.msg_count += 1
                            self.add_log("RECV", message)
                            
                            for cb in self._callbacks:
                                try:
                                    await cb(message)
                                except Exception as e:
                                    logger.error("Callback error in WSS %s: %s", self.name, str(e))
                    else:
                        self.add_log("ERROR", "Authentication failed. Re-authenticating...")
                        self.status = "DISCONNECTED"
                        await asyncio.sleep(5)
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.status = "RECONNECTING"
                self.reconnect_count += 1
                self.add_log("ERROR", f"Connection error: {str(e)}")
                
                delay = min(2 ** attempt, 30)
                self.add_log("INFO", f"Reconnecting in {delay} seconds (Attempt {self.reconnect_count})...")
                await asyncio.sleep(delay)
                attempt += 1
            finally:
                if self._heartbeat_task:
                    self._heartbeat_task.cancel()
                    self._heartbeat_task = None
                self._websocket = None

    def get_status_info(self) -> Dict[str, Any]:
        uptime = int(time.time() - self.start_time) if self.start_time > 0 and self._running else 0
        return {
            "name": self.name,
            "status": self.status,
            "msg_count": self.msg_count,
            "reconnect_count": self.reconnect_count,
            "uptime": uptime,
            "subscribed_topics": self.subscribed_topics,
            "uri": self.uri
        }

class TCBSSocketManager:
    def __init__(self):
        # 1. THESIS: Bang gia & khop lenh toan thi truong
        self.thesis_client = TCBSSocketClient(
            name="thesis",
            endpoint="/ws/thesis/v1/stream/normal",
            ping_msg="d|p|||",
            client_type="thesis"
        )
        # 2. AITHER: Thong bao thay doi lenh co so ca nhan
        self.aither_client = TCBSSocketClient(
            name="aither",
            endpoint="/ws/aither",
            ping_msg="ping|1",
            client_type="aither"
        )
        # 3. OURANOS: Lich su gia khop 1 phut (C001), Cung cau 60s (C002S60), Khoi ngoai 15m (C002S900)
        self.ouranos_client = TCBSSocketClient(
            name="ouranos",
            endpoint="/ws/ouranos/v1/stream",
            ping_msg="d|po",
            client_type="ouranos"
        )
        self._clients = {
            "thesis": self.thesis_client,
            "aither": self.aither_client,
            "ouranos": self.ouranos_client
        }

    async def start_all(self):
        logger.info("Khoi dong TCBS Socket Manager theo dac ta OpenAPI chuan...")
        for client in self._clients.values():
            await client.start()

    async def stop_all(self):
        logger.info("Dang tat TCBS Socket Manager...")
        for client in self._clients.values():
            await client.stop()

    def get_client(self, name: str) -> Optional[TCBSSocketClient]:
        return self._clients.get(name)

    def get_all_status(self) -> Dict[str, Any]:
        return {name: client.get_status_info() for name, client in self._clients.items()}

socket_manager = TCBSSocketManager()
