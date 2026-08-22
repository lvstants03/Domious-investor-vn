import httpx
import logging
from typing import Optional, Dict, Any, List
from src.config import settings
from src.tcbs.auth import auth_provider, catch_tcbs_unauthorized

logger = logging.getLogger("dominus-investor.tcbs.orders")

# Bang mapping trang thai lenh TCBS (orStatus)
ORDER_STATUS_MAP = {
    "0": "Tu choi",
    "2": "Da gui",
    "3": "Da huy",
    "4": "Da khop mot phan",
    "5": "Het hieu luc",
    "8": "Cho gui",
    "10": "Da sua",
    "11": "Dang gui",
    "12": "Khop het",
    "A": "Dang sua",
    "C": "Dang huy",
    "S": "Hoan tat"
}

class TCBSEquityOrderClient:
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

    async def _get_stock_account_no(self) -> str:
        """Helper de lay so tieu khoan co phieu (NORMAL hoac MARGIN)"""
        try:
            from src.tcbs.account import account_client
            subs = await account_client.get_sub_accounts()
            for sub in subs:
                if str(sub.get("account_type", "")).upper() in ["MARGIN", "NORMAL"]:
                    return sub.get("account_id")
        except Exception:
            pass
        custody = auth_provider.get_custody_code()
        return custody + "0"

    # --- API Methods ---
    @catch_tcbs_unauthorized
    async def place_order(self, symbol: str, action: str, qty: int, price: float, order_type: str = "LO") -> Dict[str, Any]:
        """Dat lenh thuong co phieu qua /akhlys/v1/accounts/{accountNo}/orders"""
        headers = await self._get_headers()
        if not headers:
            raise ValueError("Chua xac thuc token de dat lenh.")

        account_no = await self._get_stock_account_no()
        url = f"{self.base_url}/akhlys/v1/accounts/{account_no}/orders"
        
        exec_type = "NB" if action.upper() in ["BUY", "NB"] else "NS"
        
        body = {
            "execType": exec_type,
            "symbol": symbol.upper(),
            "priceType": order_type.upper(),
            "price": int(price),
            "quantity": int(qty)
        }
        
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.post(url, json=body, headers=headers)
                response.raise_for_status()
                data = response.json()
                return {
                    "order_id": data.get("orderId"),
                    "status": "SUCCESS" if str(data.get("error")) == "0" else "FAILED",
                    "message": data.get("message"),
                    "symbol": symbol.upper(),
                    "action": action,
                    "qty": qty,
                    "price": price,
                    "order_type": order_type
                }
        except Exception as e:
            logger.error("Loi khi dat lenh co so %s %s tren TCBS: %s", action, symbol, str(e))
            raise e

    async def modify_order(self, order_id: str, qty: int, price: float) -> Dict[str, Any]:
        logger.warning("Sua lenh khong duoc ho tro truc tiep tren thi truong co so TCBS. Vui long huy va dat lai.")
        raise NotImplementedError("Sua lenh khong duoc ho tro truc tiep tren TCBS. Vui long huy va dat lai.")

    @catch_tcbs_unauthorized
    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Huy lenh thuong co phieu qua /akhlys/v1/accounts/{accountNo}/cancel-orders"""
        headers = await self._get_headers()
        if not headers:
            raise ValueError("Chua xac thuc token de huy lenh.")

        account_no = await self._get_stock_account_no()
        url = f"{self.base_url}/akhlys/v1/accounts/{account_no}/cancel-orders"
        body = {
            "ordersList": [
                {"orderId": order_id}
            ]
        }
        
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.put(url, json=body, headers=headers)
                response.raise_for_status()
                data = response.json()
                return {
                    "order_id": order_id,
                    "status": "SUCCESS" if str(data.get("error")) == "0" else "FAILED",
                    "message": data.get("message")
                }
        except Exception as e:
            logger.error("Loi khi huy lenh co so ID %s tren TCBS: %s", order_id, str(e))
            raise e

    # --- 4.4 Lay so lenh ---
    @catch_tcbs_unauthorized
    async def get_order_book(self) -> List[Dict[str, Any]]:
        """Lay so lenh co phieu cua tieu khoan tu /aion/v1/accounts/{accountNo}/orders"""
        headers = await self._get_headers()
        if not headers:
            return []

        account_no = await self._get_stock_account_no()
        url = f"{self.base_url}/aion/v1/accounts/{account_no}/orders"
        
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                result = []
                for order in data.get("orders", []):
                    action = "BUY" if order.get("execType") == "NB" else "SELL"
                    result.append({
                        "order_id": order.get("orderId"),
                        "symbol": order.get("symbol"),
                        "action": action,
                        "qty": int(order.get("quantity", 0)),
                        "price": float(order.get("price", 0.0)),
                        "status": order.get("status")
                    })
                return result
        except Exception as e:
            logger.warning("Loi khi lay so lenh tu TCBS: %s", str(e))
            return []

    # --- 4.5 Lay chi tiet lenh theo Order ID ---
    @catch_tcbs_unauthorized
    async def get_order_by_id(self, order_id: str) -> Dict[str, Any]:
        """Truy van thong tin chi tiet mot lenh tu /aion/v1/accounts/{accountNo}/orders/{orderID}"""
        headers = await self._get_headers()
        if not headers:
            raise ValueError("Chua xac thuc token.")

        account_no = await self._get_stock_account_no()
        url = f"{self.base_url}/aion/v1/accounts/{account_no}/orders/{order_id}"
        
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                if "data" in data and len(data["data"]) > 0:
                    item = data["data"][0]
                    action = "BUY" if item.get("execType") == "NB" else "SELL"
                    raw_status = str(item.get("orStatus", ""))
                    status_text = ORDER_STATUS_MAP.get(raw_status, raw_status)
                    
                    return {
                        "order_id": item.get("orderID"),
                        "account_no": item.get("accountNo"),
                        "symbol": item.get("symbol"),
                        "action": action,
                        "order_qty": int(item.get("orderQtty", 0)),
                        "exec_qty": int(item.get("execQtty", 0)),
                        "price_type": item.get("priceType", "LO"),
                        "limit_price": float(item.get("limitPrice", 0.0)),
                        "match_price": float(item.get("matchPrice", 0.0)),
                        "raw_status": raw_status,
                        "status_desc": status_text,
                        "tx_date": item.get("txdate"),
                        "tx_time": item.get("txtime")
                    }
                raise ValueError(f"Khong tim thay lenh voi ID {order_id}")
        except Exception as e:
            logger.error("Loi khi lay chi tiet lenh ID %s tu TCBS: %s", order_id, str(e))
            raise e

    # --- 4.6 Lay thong tin khop lenh ---
    @catch_tcbs_unauthorized
    async def get_executions(self) -> List[Dict[str, Any]]:
        """Lay thong tin cac lenh da khop trong phien tu /aion/v1/accounts/{accountNo}/matching-details"""
        headers = await self._get_headers()
        if not headers:
            return []

        account_no = await self._get_stock_account_no()
        url = f"{self.base_url}/aion/v1/accounts/{account_no}/matching-details"
        
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                result = []
                for item in data.get("data", []):
                    action = "BUY" if item.get("side") == "B" else "SELL"
                    result.append({
                        "order_id": item.get("orderId"),
                        "trade_id": item.get("tradeId"),
                        "symbol": item.get("symbol"),
                        "action": action,
                        "quote_qty": int(item.get("quoteQtty", 0)),
                        "quote_price": float(item.get("quotePrice", 0.0)),
                        "exec_qty": int(item.get("qtty", 0)),
                        "exec_price": float(item.get("price", 0.0)),
                        "exec_time": item.get("timeExec")
                    })
                return result
        except Exception as e:
            logger.error("Loi khi lay thong tin khop lenh tu TCBS: %s", str(e))
            raise e

    # --- 4.7 Lay suc mua tong quat ---
    @catch_tcbs_unauthorized
    async def get_buying_power(self) -> Dict[str, Any]:
        """Lay suc mua tong quat tu /aion/v1/accounts/{accountNo}/ppse"""
        headers = await self._get_headers()
        if not headers:
            return {"purchasing_power": 0.0, "max_quantity": 0}

        account_no = await self._get_stock_account_no()
        url = f"{self.base_url}/aion/v1/accounts/{account_no}/ppse"
        
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "account_no": account_no,
                        "purchasing_power": float(data.get("purchasingPower", 0.0)),
                        "max_quantity": int(data.get("maxQuantity", 0))
                    }
                return {"purchasing_power": 0.0, "max_quantity": 0}
        except Exception as e:
            logger.debug("Loi khi lay ppse tong quat: %s", str(e))
            return {"purchasing_power": 0.0, "max_quantity": 0}

    # --- 4.8 Lay suc mua theo ma ---
    @catch_tcbs_unauthorized
    async def get_buying_power_for_symbol(self, symbol: str) -> Dict[str, Any]:
        """Lay suc mua theo ma tu /aion/v1/accounts/{accountNo}/ppse/{symbol}"""
        headers = await self._get_headers()
        if not headers:
            return {"symbol": symbol.upper(), "pp0": 0.0, "max_qty": 0}

        account_no = await self._get_stock_account_no()
        url = f"{self.base_url}/aion/v1/accounts/{account_no}/ppse/{symbol.upper()}"
        
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                return {
                    "symbol": symbol.upper(),
                    "pp0": float(data.get("pp0", 0.0)),
                    "max_qty": int(data.get("maxQtty", 0))
                }
        except Exception as e:
            logger.debug("Loi khi lay suc mua cho ma %s: %s", symbol, str(e))
            return {"symbol": symbol.upper(), "pp0": 0.0, "max_qty": 0}

    # --- 4.9 Lay suc mua theo ma va gia ---
    @catch_tcbs_unauthorized
    async def get_buying_power_for_symbol_price(self, symbol: str, price: float) -> Dict[str, Any]:
        """Lay suc mua theo ma va muc gia tu /aion/v1/accounts/{accountNo}/ppse/{symbol}/{price}"""
        headers = await self._get_headers()
        if not headers:
            return {"symbol": symbol.upper(), "price": price, "pp0": 0.0, "max_qty": 0}

        account_no = await self._get_stock_account_no()
        url = f"{self.base_url}/aion/v1/accounts/{account_no}/ppse/{symbol.upper()}/{int(price)}"
        
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                return {
                    "symbol": symbol.upper(),
                    "price": price,
                    "pp0": float(data.get("pp0", 0.0)),
                    "max_qty": int(data.get("maxQtty", 0))
                }
        except Exception as e:
            logger.debug("Loi khi lay suc mua cho ma %s gia %s: %s", symbol, price, str(e))
            return {"symbol": symbol.upper(), "price": price, "pp0": 0.0, "max_qty": 0}

equity_order_client = TCBSEquityOrderClient()
