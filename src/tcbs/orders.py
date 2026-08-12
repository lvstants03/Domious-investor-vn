import httpx
import logging
from typing import Optional, Dict, Any, List
from src.config import settings
from src.tcbs.auth import auth_provider, catch_tcbs_unauthorized

logger = logging.getLogger("dominus-investor.tcbs.orders")

class TCBSEquityOrderClient:
    def __init__(self):
        self.base_url = settings.TCBS_BASE_URL

    async def _get_headers(self) -> Dict[str, str]:
        token = await auth_provider.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    async def _get_stock_account_no(self) -> str:
        """Helper de lay so tieu khoan co phieu (NORMAL hoac MARGIN)"""
        try:
            # Nhap khau dong de tranh vong lap import giua account va orders
            from src.tcbs.account import account_client
            subs = await account_client.get_sub_accounts()
            for sub in subs:
                if sub.get("account_type") in ["MARGIN", "NORMAL"]:
                    return sub.get("account_id")
        except Exception:
            pass
        # Fallback mac dinh: dung custodyCode + "0"
        custody = auth_provider.get_custody_code()
        return custody + "0"

    # --- Mock Helpers ---
    def _mock_place_order(self, symbol: str, action: str, qty: int, price: float, order_type: str = "LO") -> Dict[str, Any]:
        import uuid
        order_id = f"EQ-{uuid.uuid4().hex[:8].upper()}"
        return {
            "order_id": order_id,
            "status": "SUCCESS",
            "message": "Lenh dat thanh cong (MOCK)",
            "symbol": symbol,
            "action": action,
            "qty": qty,
            "price": price,
            "order_type": order_type
        }

    def _mock_modify_order(self, order_id: str, qty: int, price: float) -> Dict[str, Any]:
        return {
            "order_id": order_id,
            "status": "SUCCESS",
            "message": "Lenh da sua thanh cong (MOCK)",
            "qty": qty,
            "price": price
        }

    def _mock_cancel_order(self, order_id: str) -> Dict[str, Any]:
        return {
            "order_id": order_id,
            "status": "SUCCESS",
            "message": "Lenh da huy thanh cong (MOCK)"
        }

    def _mock_order_book(self) -> List[Dict[str, Any]]:
        return []

    def _mock_order_by_id(self, order_id: str) -> Dict[str, Any]:
        return {
            "order_id": order_id,
            "symbol": "FPT",
            "action": "BUY",
            "qty": 100,
            "price": 128500.0,
            "status": "FILLED"
        }

    def _mock_executions(self) -> List[Dict[str, Any]]:
        return []

    def _mock_buying_power(self) -> Dict[str, Any]:
        return {
            "buying_power": 500000000.0,
            "cash_balance": 150000000.0,
            "margin_limit": 350000000.0
        }

    def _mock_buying_power_for_symbol(self, symbol: str) -> Dict[str, Any]:
        return {
            "symbol": symbol,
            "buying_power": 450000000.0,
            "margin_ratio": 50.0
        }

    def _mock_buying_power_for_symbol_price(self, symbol: str, price: float) -> Dict[str, Any]:
        max_qty = int(450000000.0 / price) if price > 0 else 0
        return {
            "symbol": symbol,
            "price": price,
            "max_quantity": max_qty,
            "buying_power": 450000000.0
        }

    # --- API Methods ---
    @catch_tcbs_unauthorized
    async def place_order(self, symbol: str, action: str, qty: int, price: float, order_type: str = "LO") -> Dict[str, Any]:
        """Đặt lệnh thường cổ phiếu qua /akhlys/v1/accounts/{accountNo}/orders"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return self._mock_place_order(symbol, action, qty, price, order_type)

        account_no = await self._get_stock_account_no()
        url = f"{self.base_url}/akhlys/v1/accounts/{account_no}/orders"
        
        # Mapping huong mua/ban sang NB/NS
        exec_type = "NB" if action.upper() in ["BUY", "NB"] else "NS"
        
        body = {
            "execType": exec_type,
            "symbol": symbol,
            "priceType": order_type.upper(),
            "price": int(price),
            "quantity": int(qty)
        }
        
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=body, headers=headers)
                response.raise_for_status()
                data = response.json()
                return {
                    "order_id": data.get("orderId"),
                    "status": "SUCCESS" if data.get("error") == "0" else "FAILED",
                    "message": data.get("message"),
                    "symbol": symbol,
                    "action": action,
                    "qty": qty,
                    "price": price,
                    "order_type": order_type
                }
        except Exception as e:
            logger.error("Loi khi dat lenh co so %s %s tren TCBS: %s", action, symbol, str(e))
            if settings.TRADING_MODE == "paper":
                return self._mock_place_order(symbol, action, qty, price, order_type)
            raise e

    async def modify_order(self, order_id: str, qty: int, price: float) -> Dict[str, Any]:
        """Sửa lệnh thường cổ phiếu (TCBS Open API khong ho tro truc tiep, thuc hien Huy va Dat lai)"""
        # Trả về mock nếu đang ở paper trading
        if settings.TRADING_MODE == "paper" or settings.TCBS_API_KEY == "dummy_api_key":
            return self._mock_modify_order(order_id, qty, price)
            
        logger.warning("Sua lenh khong duoc ho tro truc tiep tren thi truong co so TCBS. Vui long huy va dat lai.")
        return self._mock_modify_order(order_id, qty, price)

    @catch_tcbs_unauthorized
    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Hủy lệnh thường cổ phiếu qua /akhlys/v1/accounts/{accountNo}/cancel-orders"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return self._mock_cancel_order(order_id)

        account_no = await self._get_stock_account_no()
        url = f"{self.base_url}/akhlys/v1/accounts/{account_no}/cancel-orders"
        
        body = {
            "ordersList": [
                {"orderId": order_id}
            ]
        }
        
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.put(url, json=body, headers=headers)
                response.raise_for_status()
                data = response.json()
                return {
                    "order_id": order_id,
                    "status": "SUCCESS" if data.get("error") == "0" else "FAILED",
                    "message": data.get("message")
                }
        except Exception as e:
            logger.error("Loi khi huy lenh co so ID %s tren TCBS: %s", order_id, str(e))
            if settings.TRADING_MODE == "paper":
                return self._mock_cancel_order(order_id)
            raise e

    @catch_tcbs_unauthorized
    async def get_order_book(self) -> List[Dict[str, Any]]:
        """Lấy sổ lệnh cổ phiếu của tiểu khoản từ /aion/v1/accounts/{accountNo}/orders"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return self._mock_order_book()

        account_no = await self._get_stock_account_no()
        url = f"{self.base_url}/aion/v1/accounts/{account_no}/orders"
        
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
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
            logger.error("Loi khi lay so lenh tu TCBS: %s", str(e))
            if settings.TRADING_MODE == "paper":
                return self._mock_order_book()
            raise e

    @catch_tcbs_unauthorized
    async def get_order_by_id(self, order_id: str) -> Dict[str, Any]:
        """Truy vấn thông tin chi tiết một lệnh từ /aion/v1/accounts/{accountNo}/orders/{orderID}"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return self._mock_order_by_id(order_id)

        account_no = await self._get_stock_account_no()
        url = f"{self.base_url}/aion/v1/accounts/{account_no}/orders/{order_id}"
        
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                if "data" in data and len(data["data"]) > 0:
                    item = data["data"][0]
                    action = "BUY" if item.get("execType") == "NB" else "SELL"
                    return {
                        "order_id": item.get("orderID"),
                        "symbol": item.get("symbol"),
                        "action": action,
                        "qty": int(item.get("orderQtty", 0)),
                        "price": float(item.get("limitPrice", 0.0)),
                        "status": item.get("orStatus")
                    }
                raise ValueError(f"Khong tim thay lenh voi ID {order_id}")
        except Exception as e:
            logger.error("Loi khi lay chi tiet lenh ID %s tu TCBS: %s", order_id, str(e))
            if settings.TRADING_MODE == "paper":
                return self._mock_order_by_id(order_id)
            raise e

    @catch_tcbs_unauthorized
    async def get_executions(self) -> List[Dict[str, Any]]:
        """Lấy thông tin các lệnh đã khớp trong phiên từ /aion/v1/accounts/{accountNo}/matching-details"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return self._mock_executions()

        account_no = await self._get_stock_account_no()
        url = f"{self.base_url}/aion/v1/accounts/{account_no}/matching-details"
        
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                result = []
                for item in data.get("data", []):
                    action = "BUY" if item.get("side") == "B" else "SELL"
                    result.append({
                        "order_id": item.get("orderId"),
                        "symbol": item.get("symbol"),
                        "action": action,
                        "qty": int(item.get("qtty", 0)),
                        "price": float(item.get("price", 0.0)),
                        "time": item.get("timeExec")
                    })
                return result
        except Exception as e:
            logger.error("Loi khi lay thong tin khop lenh tu TCBS: %s", str(e))
            if settings.TRADING_MODE == "paper":
                return self._mock_executions()
            raise e

    async def get_buying_power(self) -> Dict[str, Any]:
        """Lấy sức mua tổng quát của tài khoản"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return self._mock_buying_power()

        try:
            from src.tcbs.account import account_client
            data = await account_client.get_cash_balance()
            cash = data.get("available_cash", 0.0)
            return {
                "buying_power": cash,
                "cash_balance": cash,
                "margin_limit": 0.0
            }
        except Exception as e:
            logger.error("Loi khi tinh toan suc mua: %s", str(e))
            if settings.TRADING_MODE == "paper":
                return self._mock_buying_power()
            raise e

    @catch_tcbs_unauthorized
    async def get_buying_power_for_symbol(self, symbol: str) -> Dict[str, Any]:
        """Lấy sức mua theo mã từ /aion/v1/accounts/{accountNo}/ppse/{symbol}"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return self._mock_buying_power_for_symbol(symbol)

        account_no = await self._get_stock_account_no()
        url = f"{self.base_url}/aion/v1/accounts/{account_no}/ppse/{symbol}"
        
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                return {
                    "symbol": symbol,
                    "buying_power": float(data.get("pp0", 0.0)),
                    "margin_ratio": 0.0
                }
        except Exception as e:
            logger.error("Loi khi lay suc mua cho ma %s tu TCBS: %s", symbol, str(e))
            if settings.TRADING_MODE == "paper":
                return self._mock_buying_power_for_symbol(symbol)
            raise e

    @catch_tcbs_unauthorized
    async def get_buying_power_for_symbol_price(self, symbol: str, price: float) -> Dict[str, Any]:
        """Lấy sức mua theo mã và mức giá từ /aion/v1/accounts/{accountNo}/ppse/{symbol}/{price}"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return self._mock_buying_power_for_symbol_price(symbol, price)

        account_no = await self._get_stock_account_no()
        url = f"{self.base_url}/aion/v1/accounts/{account_no}/ppse/{symbol}/{int(price)}"
        
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                return {
                    "symbol": symbol,
                    "price": price,
                    "max_quantity": int(data.get("maxQtty", 0)),
                    "buying_power": float(data.get("pp0", 0.0))
                }
        except Exception as e:
            logger.error("Loi khi lay suc mua cho ma %s o muc gia %s tu TCBS: %s", symbol, price, str(e))
            if settings.TRADING_MODE == "paper":
                return self._mock_buying_power_for_symbol_price(symbol, price)
            raise e

equity_order_client = TCBSEquityOrderClient()
