import httpx
import logging
from typing import Dict, Any, List, Optional
from src.config import settings
from src.tcbs.auth import auth_provider, catch_tcbs_unauthorized

logger = logging.getLogger("dominus-investor.tcbs.account")

class TCBSAccountClient:
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
            subs = await self.get_sub_accounts()
            for sub in subs:
                if sub.get("account_type") in ["MARGIN", "NORMAL"]:
                    return sub.get("account_id")
        except Exception:
            pass
        # Fallback mac dinh: dung custodyCode + "0"
        custody = auth_provider.get_custody_code()
        return custody + "0"

    # --- Mock Helpers ---
    def _mock_sub_accounts(self) -> List[Dict[str, Any]]:
        return [
            {"account_id": "105C123456", "account_type": "MARGIN", "name": "Tieu khoan Margin"},
            {"account_id": "105C123457", "account_type": "DERIVATIVE", "name": "Tieu khoan Phai sinh"}
        ]

    def _mock_equity_portfolio(self) -> List[Dict[str, Any]]:
        return [
            {
                "symbol": "FPT",
                "quantity": 1000,
                "available_qty": 1000,
                "avg_cost": 125000.0,
                "current_price": 128500.0,
                "market_value": 128500000.0,
                "unrealized_pnl": 3500000.0,
                "unrealized_pnl_pct": 2.8
            },
            {
                "symbol": "VNM",
                "quantity": 500,
                "available_qty": 500,
                "avg_cost": 75000.0,
                "current_price": 74200.0,
                "market_value": 37100000.0,
                "unrealized_pnl": -400000.0,
                "unrealized_pnl_pct": -1.07
            }
        ]

    def _mock_cash_balance(self) -> Dict[str, Any]:
        return {
            "available_cash": 150000000.0,
            "purchasing_power": 300000000.0,
            "withdrawable_cash": 120000000.0,
            "blocked_cash": 10000000.0,
            "bod_balance": 140000000.0,
            "bond_fund_pp": 50000000.0,
            "total_cash": 210000000.0
        }

    def _mock_cash_statement(self) -> List[Dict[str, Any]]:
        return [
            {
                "date": "2026-08-07",
                "transaction_id": "TX-998877",
                "description": "Nop tien tu VPBank",
                "amount": 50000000.0,
                "balance_after": 150000000.0
            }
        ]

    # --- API Methods ---
    @catch_tcbs_unauthorized
    async def get_sub_accounts(self) -> List[Dict[str, Any]]:
        """Lấy danh sách tiểu khoản của người dùng từ /eros/v2/get-profile/by-username/{custodyCode}"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return self._mock_sub_accounts()

        custody_code = auth_provider.get_custody_code()
        url = f"{self.base_url}/eros/v2/get-profile/by-username/{custody_code}?fields=basicInfo,bankSubAccounts"
        
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                result = []
                for sub in data.get("bankSubAccounts", []):
                    result.append({
                        "account_id": sub.get("accountNo"),
                        "account_type": sub.get("accountType"),
                        "name": sub.get("accountTypeName")
                    })
                return result
        except Exception as e:
            logger.error("Loi khi lay thong tin cac tieu khoan tu TCBS: %s", str(e))
            raise e

    @catch_tcbs_unauthorized
    async def get_equity_portfolio(self, account_no: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lấy danh mục cổ phiếu từ /aion/v1/accounts/{accountNo}/se"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return self._mock_equity_portfolio()

        if not account_no:
            account_no = await self._get_stock_account_no()
        url = f"{self.base_url}/aion/v1/accounts/{account_no}/se"
        
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                result = []
                for asset in data.get("assets", []):
                    qty = int(asset.get("quantity", 0))
                    avg_price = float(asset.get("avgPrice", 0.0))
                    market_value = float(asset.get("marketValue", 0.0))
                    current_price = market_value / qty if qty > 0 else avg_price
                    unrealized_pnl = market_value - (qty * avg_price)
                    unrealized_pnl_pct = (unrealized_pnl / (qty * avg_price) * 100) if (qty * avg_price) > 0 else 0.0
                    
                    result.append({
                        "symbol": asset.get("symbol"),
                        "quantity": qty,
                        "available_qty": qty,
                        "avg_cost": avg_price,
                        "current_price": current_price,
                        "market_value": market_value,
                        "unrealized_pnl": unrealized_pnl,
                        "unrealized_pnl_pct": unrealized_pnl_pct
                    })
                return result
        except Exception as e:
            logger.error("Loi khi lay danh muc co phieu tu TCBS: %s", str(e))
            raise e

    @catch_tcbs_unauthorized
    async def get_cash_balance(self, account_no: Optional[str] = None) -> Dict[str, Any]:
        """Lấy số dư tiền mặt của tiểu khoản từ /aion/v1/accounts/{accountNo}/cashInvestments"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return self._mock_cash_balance()

        if not account_no:
            account_no = await self._get_stock_account_no()
        url = f"{self.base_url}/aion/v1/accounts/{account_no}/cashInvestments"
        
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                if "data" in data and len(data["data"]) > 0:
                    item = data["data"][0]
                    # Field names confirmed from TCBS OpenAPI spec v1.0.0
                    cash_balance = float(item.get("cashBalance", 0.0))
                    bod_balance = float(item.get("bodBalance", 0.0))
                    pp_bond_fund = float(item.get("pp0forBF", 0.0))
                    bank_avl_bf = float(item.get("bankAvlBalanceBF", 0.0))
                    
                    # Trích xuất trường purchasingPower (sức mua khả dụng của tài khoản ký quỹ)
                    purchasing_power = float(item.get("purchasingPower", 0.0))
                    if purchasing_power <= 0:
                        purchasing_power = max(cash_balance, pp_bond_fund, bank_avl_bf)

                    return {
                        "available_cash": purchasing_power,
                        "purchasing_power": purchasing_power,
                        "withdrawable_cash": bank_avl_bf,
                        "blocked_cash": max(0.0, bod_balance - cash_balance),
                        "bod_balance": bod_balance,
                        "bond_fund_pp": pp_bond_fund,
                        "total_cash": cash_balance
                    }
                raise ValueError("Khong co du lieu so du tra ve tu TCBS.")
        except Exception as e:
            logger.error("Loi khi lay so du tien tu TCBS: %s", str(e))
            raise e

    @catch_tcbs_unauthorized
    async def get_cash_statement(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """Lấy sao kê tiền mặt từ /erebos/v2/digital/trans-hist-cashStatements"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return self._mock_cash_statement()

        account_no = await self._get_stock_account_no()
        url = f"{self.base_url}/erebos/v2/digital/trans-hist-cashStatements"
        params = {
            "accountNo": account_no,
            "fromDate": start_date,
            "toDate": end_date,
            "pageSize": "50",
            "pageIndex": "1",
            "transactionCode": "ALL"
        }
        
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers, params=params)
                response.raise_for_status()
                data = response.json()
                resp_data = data.get("response", {})
                result = []
                for item in resp_data.get("data", []):
                    debit = float(item.get("debitAmount", 0.0))
                    credit = float(item.get("creditAmount", 0.0))
                    amount = credit - debit
                    result.append({
                        "date": item.get("transactionDate"),
                        "transaction_id": item.get("transactionCode"),
                        "description": item.get("descriptions"),
                        "amount": amount,
                        "balance_after": 0.0
                    })
                return result
        except Exception as e:
            logger.error("Loi khi lay sao ke tien tu TCBS: %s", str(e))
            raise e

    @catch_tcbs_unauthorized
    async def get_margin_overview(self) -> Dict[str, Any]:
        """Lay tong hop margin: han muc tu /aion/v1/customers/{custodyId}/accounts"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return {
                "margin_limit": 1000000000.0,
                "margin_account_no": "105C123456M",
                "account_type": "margin",
                "account_status": "A"
            }

        custody_code = auth_provider.get_custody_code()
        url = f"{self.base_url}/aion/v1/customers/{custody_code}/accounts"
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                accounts = response.json()
                # Tim tai khoan margin
                margin_acc = next(
                    (a for a in accounts if str(a.get("accountType", "")).lower() == "margin"),
                    accounts[0] if accounts else {}
                )
                return {
                    "margin_limit": float(margin_acc.get("marginLimit", 0.0)),
                    "margin_account_no": margin_acc.get("accountNo", ""),
                    "account_type": margin_acc.get("accountType", ""),
                    "account_status": margin_acc.get("accountStatus", "")
                }
        except Exception as e:
            logger.error("Loi khi lay thong tin margin quota: %s", str(e))
            raise e

    @catch_tcbs_unauthorized
    async def get_margin_risk(self, account_no: Optional[str] = None) -> Dict[str, Any]:
        """Lấy thông tin margin risk từ /hydros/v1/account/{accountNo}/risk thực tế từ TCBS"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return {
                "rtt": 115.5,
                "outstanding_margin": 450000000.0,
                "margin_ratio": 45.2,
                "margin_call_threshold": 85.0,
                "margin_warning_threshold": 100.0
            }

        if not account_no:
            account_no = await self._get_stock_account_no()
        url = f"{self.base_url}/hydros/v1/account/{account_no}/risk"
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                return {
                    "rtt": float(data.get("rtt", 0.0)),
                    "outstanding_margin": float(data.get("outstandingMargin", 0.0)),
                    "margin_ratio": float(data.get("marginRatio", 0.0)),
                    "margin_call_threshold": float(data.get("marginCallThreshold", 85.0)),
                    "margin_warning_threshold": float(data.get("marginWarningThreshold", 100.0))
                }
        except Exception as e:
            logger.error("Loi khi lay thong tin margin risk tu TCBS cho tieu khoan %s: %s", account_no, str(e))
            # Trả về 0 mặc định thay vì mock số giả nếu API lỗi hoặc tài khoản không phải margin
            return {
                "rtt": 0.0,
                "outstanding_margin": 0.0,
                "margin_ratio": 0.0,
                "margin_call_threshold": 85.0,
                "margin_warning_threshold": 100.0
            }

    async def get_loans_list(self) -> List[Dict[str, Any]]:
        """Lay danh sach khoan vay tu /khaos/v1/loan/{accountNo}"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return [
                {
                    "opening_date": "2026-07-01",
                    "due_date": "2026-09-28",
                    "renew_time": 0,
                    "max_renew_time": 2,
                    "is_renewable": True,
                    "insurance_name": "",
                    "insurance_fee": 0.0
                }
            ]

        account_no = await self._get_stock_account_no()
        url = f"{self.base_url}/khaos/v1/loan/{account_no}"
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                result = []
                for loan in data.get("content", []):
                    insurance = loan.get("insurance") or {}
                    result.append({
                        "opening_date": loan.get("openingDate", ""),
                        "due_date": loan.get("dueDate", ""),
                        "renew_time": loan.get("renewTime", 0),
                        "max_renew_time": loan.get("maxRenewTime", 0),
                        "is_renewable": loan.get("isRenewable", False),
                        "insurance_name": insurance.get("insuranceName", ""),
                        "insurance_fee": float(insurance.get("insuranceFee", 0.0))
                    })
                return result
        except Exception as e:
            logger.error("Loi khi lay danh sach khoan vay: %s", str(e))
            raise e

    async def get_account_summary(self) -> Dict[str, Any]:
        """Tong hop: portfolio + cash -> NAV, total PnL, hieu qua dau tu"""
        try:
            portfolio = await self.get_equity_portfolio()
            cash = await self.get_cash_balance()

            total_market_value = sum(float(p.get("market_value", 0)) for p in portfolio)
            total_cost = sum(
                float(p.get("avg_cost", 0)) * int(p.get("quantity", 0))
                for p in portfolio
            )
            total_unrealized_pnl = total_market_value - total_cost
            pnl_pct = (total_unrealized_pnl / total_cost * 100) if total_cost > 0 else 0.0
            available_cash = float(cash.get("available_cash", 0))
            total_nav = total_market_value + available_cash

            winning = sum(1 for p in portfolio if float(p.get("unrealized_pnl", 0)) >= 0)
            losing = len(portfolio) - winning

            return {
                "total_portfolio_value": total_market_value,
                "total_invested_cost": total_cost,
                "total_unrealized_pnl": total_unrealized_pnl,
                "pnl_pct": round(pnl_pct, 2),
                "total_cash": available_cash,
                "total_nav": total_nav,
                "num_positions": len(portfolio),
                "num_winning": winning,
                "num_losing": losing
            }
        except Exception as e:
            logger.error("Loi khi tong hop account summary: %s", str(e))
            raise e


account_client = TCBSAccountClient()

