import httpx
import logging
from typing import Dict, Any, List, Optional
from src.config import settings
from src.tcbs.auth import auth_provider, catch_tcbs_unauthorized

logger = logging.getLogger("dominus-investor.tcbs.market")

class TCBSMarketClient:
    def __init__(self):
        self.base_url = settings.TCBS_BASE_URL

    async def _get_headers(self) -> Optional[Dict[str, str]]:
        try:
            token = await auth_provider.get_token()
            if not token:
                return None
            return {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
        except Exception:
            return None

    # --- API Methods ---
    @catch_tcbs_unauthorized
    async def get_ticker_commons(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Lay thong tin chi tiet bang gia khop lenh tu /tartarus/v1/tickerCommons"""
        headers = await self._get_headers()
        if not headers:
            return None

        url = f"{self.base_url}/tartarus/v1/tickerCommons?tickers={symbol.upper()}"
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    if "data" in data and len(data["data"]) > 0:
                        return data["data"][0]
                return None
        except Exception as e:
            logger.debug("Loi khi lay tickerCommons cho ma %s: %s", symbol, str(e))
            return None

    @catch_tcbs_unauthorized
    async def get_price_info(self, symbol: str) -> Dict[str, Any]:
        """Lay gia co phieu thoi gian thuc tu /tartarus/v1/tickerCommons"""
        headers = await self._get_headers()
        if not headers:
            raise ValueError(f"Chua xac thuc token de lay gia cho {symbol}")

        url = f"{self.base_url}/tartarus/v1/tickerCommons?tickers={symbol}"
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                if "data" in data and len(data["data"]) > 0:
                    item = data["data"][0]
                    return {
                        "symbol": item.get("symbol", symbol),
                        "price": float(item.get("matchPrice", 0.0)),
                        "change": float(item.get("change", 0.0)),
                        "percent_change": float(item.get("changePercent", 0.0)),
                        "open": float(item.get("open", 0.0)),
                        "high": float(item.get("high", 0.0)),
                        "low": float(item.get("low", 0.0)),
                        "volume": int(item.get("totalVol", 0)),
                        "total_val": float(item.get("totalVal", 0.0))
                    }
                else:
                    raise ValueError(f"Khong tim thay thong tin cho ma {symbol}")
        except Exception as e:
            logger.error("Loi khi lay thong tin gia ma %s tu TCBS: %s", symbol, str(e))
            raise e

    @catch_tcbs_unauthorized
    async def get_foreign_room(self, symbol: str) -> Dict[str, Any]:
        """Lay thong tin room nuoc ngoai tu /tartarus/v1/tickerSnaps"""
        headers = await self._get_headers()
        if not headers:
            raise ValueError(f"Chua xac thuc token de lay room cho {symbol}")

        indices = [1, 3, 5]
        for idx in indices:
            url = f"{self.base_url}/tartarus/v1/tickerSnaps?index={idx}"
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    response = await client.get(url, headers=headers)
                    if response.status_code == 200:
                        data = response.json()
                        if "data" in data:
                            for item in data["data"]:
                                if item.get("symbol") == symbol:
                                    buy_qtty = float(item.get("buyForeignQtty") or 0)
                                    sell_qtty = float(item.get("sellForeignQtty") or 0)
                                    match_price = float(item.get("matchPrice") or 0.0)
                                    net_buy_vol = buy_qtty - sell_qtty
                                    return {
                                        "symbol": symbol,
                                        "foreign_owned_pct": 0.0,
                                        "foreign_room_left": float(item.get("room") or 0),
                                        "net_buy_volume": net_buy_vol,
                                        "net_buy_value": net_buy_vol * match_price
                                    }
            except Exception as e:
                logger.warning("Loi khi quet tickerSnaps index %d cho ma %s: %s", idx, symbol, str(e))
        
        raise ValueError(f"Khong tim thay thong tin room nuoc ngoai cho ma {symbol}")

    @catch_tcbs_unauthorized
    async def get_put_through_deals(self, symbol: str) -> List[Dict[str, Any]]:
        """Lay thong tin giao dich thoa thuan thuc te cua TCBS tu /tartarus/v1/putThroughSnaps"""
        headers = await self._get_headers()
        if not headers:
            return []

        url = f"{self.base_url}/tartarus/v1/putThroughSnaps"
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    deals = []
                    for item in data.get("data", []):
                        if item.get("symbol") == symbol:
                            vol = float(item.get("totalVol") or 0.0)
                            price = float(item.get("price") or 0.0)
                            ref_price = float(item.get("refPrice") or price or 1.0)
                            price_diff = ((price - ref_price) / ref_price) * 100
                            deals.append({
                                "time": item.get("time", "15:00:00"),
                                "volume": vol,
                                "price": price,
                                "value": vol * price,
                                "price_diff_pct": round(price_diff, 2)
                            })
                    return deals
                return []
        except Exception as e:
            logger.warning("Loi khi lay putThroughSnaps tu TCBS cho ma %s: %s", symbol, str(e))
            return []

    async def get_deals(self, symbol: str) -> List[Dict[str, Any]]:
        return await self.get_put_through_deals(symbol)

    @catch_tcbs_unauthorized
    async def get_match_history(self, symbol: str) -> List[Dict[str, Any]]:
        headers = await self._get_headers()
        if not headers:
            return []

        url = f"{self.base_url}/nyx/v1/intraday/{symbol}/his/paging?page=0&size=50"
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                return data.get("data", [])
        except Exception as e:
            logger.error("Loi khi lay lich su khop lenh cho ma %s: %s", symbol, str(e))
            raise e

    @catch_tcbs_unauthorized
    async def get_ticker_snaps(self, index: int = 1) -> List[Dict[str, Any]]:
        headers = await self._get_headers()
        if not headers:
            return []

        url = f"{self.base_url}/tartarus/v1/tickerSnaps?index={index}"
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    return data.get("data", [])
                return []
        except Exception as e:
            logger.debug("Loi khi lay tickerSnaps index %s: %s", index, str(e))
            return []

    @catch_tcbs_unauthorized
    async def get_shark_flow(self, symbol: str) -> List[Dict[str, Any]]:
        headers = await self._get_headers()
        if not headers:
            return []

        from datetime import date
        today_str = date.today().strftime("%Y-%m-%d")

        url = f"{self.base_url}/nyx/v1/intraday/{symbol}/bsa"
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    raw_list = data.get("data", [])
                    if not raw_list:
                        return []
                    
                    step = max(1, len(raw_list) // 50)
                    sampled_list = raw_list[::step]
                    
                    result = []
                    for item in sampled_list:
                        time_str = item.get("t", "09:00")
                        bup = float(item.get("bup") or 0.5)
                        sdp = float(item.get("sdp") or 0.5)
                        net_ratio = bup - sdp
                        
                        shark_val = net_ratio * 1_000_000_000.0
                        wolf_val = -net_ratio * 300_000_000.0
                        
                        result.append({
                            "trade_date": today_str,
                            "time_str": time_str,
                            "shark_flow": round(shark_val, 2),
                            "wolf_flow": round(wolf_val, 2)
                        })
                    return result
                return []
        except Exception as e:
            logger.warning("Loi khi lay bsa shark flow tu TCBS cho ma %s: %s", symbol, str(e))
            return []

market_client = TCBSMarketClient()
