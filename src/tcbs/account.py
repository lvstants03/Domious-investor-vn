import httpx
import logging
import time
from typing import Dict, Any, List, Optional, Tuple
from datetime import date, timedelta
from src.config import settings
from src.tcbs.auth import auth_provider, catch_tcbs_unauthorized

logger = logging.getLogger("dominus-investor.tcbs.account")

class TCBSAccountClient:
    def __init__(self):
        self.base_url = settings.TCBS_BASE_URL
        self._sub_accounts_cache: Optional[List[Dict[str, Any]]] = None
        self._portfolio_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
        self._cash_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._risk_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._loans_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}

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

    async def _get_margin_account_no(self) -> str:
        """Helper de lay so tieu khoan MARGIN (ky quy)"""
        try:
            subs = await self.get_sub_accounts()
            for sub in subs:
                if str(sub.get("account_type", "")).upper() == "MARGIN":
                    return sub.get("account_id")
            for sub in subs:
                if str(sub.get("account_type", "")).upper() == "NORMAL":
                    return sub.get("account_id")
        except Exception:
            pass
        custody = auth_provider.get_custody_code()
        return custody + "0"

    async def _get_stock_account_no(self) -> str:
        """Helper uu tien lay tieu khoan MARGIN truoc neu co, sau do la NORMAL"""
        return await self._get_margin_account_no()

    # --- 1. Danh sach tieu khoan ---
    @catch_tcbs_unauthorized
    async def get_sub_accounts(self) -> List[Dict[str, Any]]:
        """Lay danh sach tieu khoan cua nguoi dung tu /eros/v2/get-profile/by-username/{custodyCode}"""
        if self._sub_accounts_cache:
            return self._sub_accounts_cache

        headers = await self._get_headers()
        if not headers:
            return []

        custody_code = auth_provider.get_custody_code()
        url = f"{self.base_url}/eros/v2/get-profile/by-username/{custody_code}?fields=basicInfo,bankSubAccounts"
        
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    result = []
                    for sub in data.get("bankSubAccounts", []):
                        result.append({
                            "account_id": sub.get("accountNo"),
                            "account_type": sub.get("accountType"),
                            "name": sub.get("accountTypeName")
                        })
                    self._sub_accounts_cache = result
                    return result
                return []
        except Exception as e:
            logger.warning("Loi khi lay thong tin cac tieu khoan tu TCBS: %s", str(e))
            return []

    # --- 4.14 Tra cuu tai san co phieu ---
    @catch_tcbs_unauthorized
    async def get_equity_portfolio(self, account_no: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lay danh muc co phieu tu /aion/v1/accounts/{accountNo}/se"""
        cache_key = account_no or "ALL"
        now = time.time()
        if cache_key in self._portfolio_cache:
            ts, cached_val = self._portfolio_cache[cache_key]
            if (now - ts < 15.0 or len(cached_val) > 0) and len(cached_val) > 0:
                if now - ts < 10.0:
                    return cached_val

        headers = await self._get_headers()
        if not headers:
            return self._portfolio_cache.get(cache_key, (0, []))[1]

        target_accounts = [account_no] if account_no else []
        if not target_accounts:
            subs = await self.get_sub_accounts()
            for sub in subs:
                acc_id = sub.get("account_id")
                if acc_id and str(sub.get("account_type", "")).upper() in ["MARGIN", "NORMAL"]:
                    target_accounts.append(acc_id)
            if not target_accounts:
                target_accounts = [await self._get_stock_account_no()]

        all_assets = []
        async with httpx.AsyncClient(timeout=3.0) as client:
            for acc in target_accounts:
                url = f"{self.base_url}/aion/v1/accounts/{acc}/se"
                try:
                    response = await client.get(url, headers=headers)
                    if response.status_code == 200:
                        data = response.json()
                        stocks_list = data.get("stock") or data.get("assets") or []
                        for asset in stocks_list:
                            sym = asset.get("symbol")
                            if not sym:
                                continue
                            
                            qty = int(asset.get("totalQtty") or asset.get("tradeQtty") or asset.get("quantity") or 0)
                            if qty <= 0:
                                continue

                            avail_qty = int(asset.get("availableTrading") or asset.get("availableTradingForBuyIn") or asset.get("tradeQtty") or qty)
                            avg_price = float(asset.get("costPrice") or asset.get("avgPrice") or 0.0)
                            current_price = float(asset.get("currentPrice") or 0.0)
                            
                            market_value = qty * current_price if current_price > 0 else float(asset.get("marketValue", 0.0))
                            unrealized_pnl = round((current_price - avg_price) * qty, 2) if (current_price > 0 and avg_price > 0) else 0.0
                            unrealized_pnl_pct = round(((current_price - avg_price) / avg_price * 100), 2) if avg_price > 0 else 0.0

                            all_assets.append({
                                "account_no": acc,
                                "symbol": sym,
                                "quantity": qty,
                                "available_qty": avail_qty,
                                "avg_cost": avg_price,
                                "current_price": current_price,
                                "market_value": market_value,
                                "unrealized_pnl": unrealized_pnl,
                                "unrealized_pnl_pct": unrealized_pnl_pct
                            })
                except Exception as e:
                    logger.warning("Loi khi lay co phieu cho tieu khoan %s: %s", acc, str(e))

        # Enrich voi gia realtime tu /tartarus/v1/tickerCommons
        if all_assets:
            symbols = list(set([a["symbol"] for a in all_assets if a.get("symbol")]))
            if symbols:
                try:
                    tickers_param = ",".join(symbols)
                    url_ticker = f"{self.base_url}/tartarus/v1/tickerCommons?tickers={tickers_param}"
                    async with httpx.AsyncClient(timeout=2.5) as client:
                        resp_ticker = await client.get(url_ticker, headers=headers)
                        if resp_ticker.status_code == 200:
                            t_data = resp_ticker.json()
                            ticker_items = t_data.get("data", []) if isinstance(t_data, dict) else (t_data if isinstance(t_data, list) else [])
                            price_map = {}
                            for item in ticker_items:
                                sym = item.get("symbol")
                                match_p = float(item.get("matchPrice") or item.get("lastPrice") or 0.0)
                                if match_p > 0 and sym:
                                    price_map[sym] = match_p
                            
                            for asset in all_assets:
                                sym = asset["symbol"]
                                if sym in price_map:
                                    live_p = price_map[sym]
                                    asset["current_price"] = live_p
                                    qty = asset["quantity"]
                                    avg_p = asset["avg_cost"]
                                    asset["market_value"] = qty * live_p
                                    asset["unrealized_pnl"] = round((live_p - avg_p) * qty, 2) if avg_p > 0 else 0.0
                                    asset["unrealized_pnl_pct"] = round(((live_p - avg_p) / avg_p * 100), 2) if avg_p > 0 else 0.0
                except Exception as e:
                    logger.warning("Khong the enrich gia realtime cho portfolio: %s", str(e))

        if len(all_assets) > 0:
            self._portfolio_cache[cache_key] = (now, all_assets)
            return all_assets
        
        # Neu lan nay bi 429 thi tra ve cache cu neu co
        if cache_key in self._portfolio_cache:
            return self._portfolio_cache[cache_key][1]
        return []

    # --- 4.15 Lay thong tin so du tien ---
    @catch_tcbs_unauthorized
    async def get_cash_balance(self, account_no: Optional[str] = None) -> Dict[str, Any]:
        """Lay thong tin so du tien cua tieu khoan tu /aion/v1/accounts/{accountNo}/cashInvestments"""
        cache_key = account_no or "DEFAULT"
        now = time.time()
        if cache_key in self._cash_cache:
            ts, cached_val = self._cash_cache[cache_key]
            if now - ts < 10.0:
                return cached_val

        default_cash = {
            "account_no": account_no or "",
            "available_cash": 0.0,
            "purchasing_power": 0.0,
            "withdrawable_cash": 0.0,
            "blocked_cash": 0.0,
            "bod_balance": 0.0,
            "bond_fund_pp": 0.0,
            "total_cash": 0.0
        }
        headers = await self._get_headers()
        if not headers:
            return self._cash_cache.get(cache_key, (0, default_cash))[1]

        if not account_no:
            account_no = await self._get_stock_account_no()
        url = f"{self.base_url}/aion/v1/accounts/{account_no}/cashInvestments"
        
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    if "data" in data and len(data["data"]) > 0:
                        item = data["data"][0]
                        cash_balance = float(item.get("cashBalance", 0.0))
                        bod_balance = float(item.get("bodBalance", 0.0))
                        pp_bond_fund = float(item.get("pp0forBF", 0.0))
                        bank_avl_bf = float(item.get("bankAvlBalanceBF", 0.0))
                        purchasing_power = float(item.get("purchasingPower", 0.0))
                        if purchasing_power <= 0:
                            purchasing_power = max(cash_balance, pp_bond_fund, bank_avl_bf)

                        res = {
                            "account_no": item.get("accountNo", account_no),
                            "available_cash": max(0.0, purchasing_power),
                            "purchasing_power": purchasing_power,
                            "withdrawable_cash": max(0.0, bank_avl_bf),
                            "blocked_cash": max(0.0, bod_balance - cash_balance),
                            "bod_balance": bod_balance,
                            "bond_fund_pp": pp_bond_fund,
                            "total_cash": cash_balance
                        }
                        self._cash_cache[cache_key] = (now, res)
                        return res
                if cache_key in self._cash_cache:
                    return self._cash_cache[cache_key][1]
                return default_cash
        except Exception as e:
            logger.warning("Loi khi lay so du tien tu TCBS: %s", str(e))
            if cache_key in self._cash_cache:
                return self._cash_cache[cache_key][1]
            return default_cash

    # --- 4.16 Thong tin sao ke tien ---
    @catch_tcbs_unauthorized
    async def get_cash_statement(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """Lay thong tin sao ke tien tu /erebos/v2/digital/trans-hist-cashStatements"""
        headers = await self._get_headers()
        if not headers:
            return []

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
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(url, headers=headers, params=params)
                if response.status_code == 200:
                    data = response.json()
                    resp_data = data.get("response", {})
                    result = []
                    for item in resp_data.get("data", []):
                        debit = float(item.get("debitAmount", 0.0))
                        credit = float(item.get("creditAmount", 0.0))
                        amount = credit - debit
                        result.append({
                            "custody_id": item.get("custodyID"),
                            "date": item.get("transactionDate"),
                            "business_date": item.get("businessDate"),
                            "transaction_code": item.get("transactionCode"),
                            "transaction_name": item.get("transactionName"),
                            "debit_amount": debit,
                            "credit_amount": credit,
                            "amount": amount,
                            "description": item.get("descriptions")
                        })
                    return result
                return []
        except Exception as e:
            logger.warning("Loi khi lay sao ke tien tu TCBS: %s", str(e))
            return []

    # --- 4.10 Han muc margin khach hang ---
    @catch_tcbs_unauthorized
    async def get_margin_overview(self) -> List[Dict[str, Any]]:
        """Lay toan bo danh sach han muc margin cua cac tieu khoan tu /aion/v1/customers/{custodyId}/accounts"""
        headers = await self._get_headers()
        if not headers:
            return []

        custody_code = auth_provider.get_custody_code()
        url = f"{self.base_url}/aion/v1/customers/{custody_code}/accounts"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    accounts = response.json()
                    result = []
                    if isinstance(accounts, list):
                        for a in accounts:
                            result.append({
                                "custody_id": a.get("custodyID", custody_code),
                                "account_no": a.get("accountNo", ""),
                                "af_type": a.get("aftype", ""),
                                "vsd_status": a.get("vsdStatus", ""),
                                "account_status": a.get("accountStatus", ""),
                                "margin_limit": float(a.get("marginLimit", 0.0)),
                                "account_type": a.get("accountType", ""),
                                "is_ia": a.get("isIA", "N"),
                                "bank_name": a.get("bankName", ""),
                                "bank_account": a.get("bankAccount", "")
                            })
                    return result
                return []
        except Exception as e:
            logger.warning("Loi khi lay thong tin margin quota: %s", str(e))
            return []

    # --- 4.11 Ty le margin & rui ro (Rtt, No goc, No lai, Policy) ---
    @catch_tcbs_unauthorized
    async def get_margin_risk(self, account_no: Optional[str] = None) -> Dict[str, Any]:
        """Lay ty le ky quy Rtt va chi tiet cac loai no tu /hydros/v1/account/{accountNo}/risk"""
        cache_key = account_no or "MARGIN"
        now = time.time()
        if cache_key in self._risk_cache:
            ts, cached_val = self._risk_cache[cache_key]
            if (now - ts < 15.0 or cached_val.get("outstanding", 0) > 0):
                if now - ts < 10.0:
                    return cached_val

        headers = await self._get_headers()
        default_risk = {
            "account_no": account_no or "",
            "rtt": 999.0,
            "outstanding": 0.0,
            "accrued_interest": 0.0,
            "due_amount": 0.0,
            "overdue_amount": 0.0,
            "total_fee_debt": 0.0,
            "initial_margin": 100.0,
            "maintenance_margin": 85.0,
            "liquidation_margin": 80.0,
            "risk_status_code": "SAFE",
            "risk_status_desc": "Safe"
        }
        if not headers:
            return self._risk_cache.get(cache_key, (0, default_risk))[1]

        if not account_no:
            account_no = await self._get_margin_account_no()
        url = f"{self.base_url}/hydros/v1/account/{account_no}/risk"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    raw = response.json()
                    item = raw[0] if (isinstance(raw, list) and len(raw) > 0) else (raw if isinstance(raw, dict) else {})
                    if not item:
                        return default_risk

                    risk_policy = item.get("riskPolicy") or {}
                    risk_status = item.get("riskStatus") or {}

                    res = {
                        "account_no": item.get("accountNo", account_no),
                        "rtt": float(item.get("rtt", 999.0)),
                        "outstanding": float(item.get("outstanding", 0.0)),
                        "accrued_interest": float(item.get("accruedInterest", 0.0)),
                        "due_amount": float(item.get("dueAmount", 0.0)),
                        "overdue_amount": float(item.get("overdueAmount", 0.0)),
                        "total_fee_debt": float(item.get("totalFeeDebt", 0.0)),
                        "initial_margin": float(risk_policy.get("initialMargin", 100.0)),
                        "maintenance_margin": float(risk_policy.get("maintenanceMargin", 85.0)),
                        "liquidation_margin": float(risk_policy.get("liquidationMargin", 80.0)),
                        "risk_status_code": risk_status.get("code", "SAFE"),
                        "risk_status_desc": risk_status.get("description", "Safe")
                    }

                    # Rtt goc tu TCBS API (/hydros/v1/account/{accountNo}/risk)
                    # Truong hop muon cap nhat theo gia realtime: Rtt = (Tong Thi Gia Realtime - Tong No) / Tong No * 100
                    total_debt = res["outstanding"] + res["accrued_interest"]
                    raw_tcbs_rtt = float(item.get("rtt", 999.0))
                    if raw_tcbs_rtt > 0 and raw_tcbs_rtt < 999.0:
                        res["rtt"] = raw_tcbs_rtt
                    elif total_debt > 0:
                        try:
                            port_items = await self.get_equity_portfolio(account_no)
                            total_live_val = sum(p.get("market_value", 0.0) for p in port_items)
                            if total_live_val > 0:
                                res["rtt"] = round(((total_live_val - total_debt) / total_debt) * 100, 2)
                        except Exception:
                            pass

                    self._risk_cache[cache_key] = (now, res)
                    return res
                if cache_key in self._risk_cache:
                    return self._risk_cache[cache_key][1]
                return default_risk
        except Exception as e:
            logger.debug("Loi khi lay thong tin margin risk cho tieu khoan %s: %s", account_no, str(e))
            if cache_key in self._risk_cache:
                return self._risk_cache[cache_key][1]
            return default_risk

    # --- 4.12 Goi vay bo tro (Marginsure, T+) ---
    @catch_tcbs_unauthorized
    async def get_margin_addons(self, account_no: Optional[str] = None) -> Dict[str, Any]:
        """Lay chi tiet goi vay bo tro tu /campaign-management/v1/margin/subscription/{accountNo}/addons/detail"""
        headers = await self._get_headers()
        if not headers:
            return {"margin_sure": [], "t_plus": []}

        if not account_no:
            account_no = await self._get_margin_account_no()
        url = f"{self.base_url}/campaign-management/v1/margin/subscription/{account_no}/addons/detail"
        
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    margin_sure_views = []
                    for ms in data.get("marginSureViews", []):
                        margin_sure_views.append({
                            "id": ms.get("id"),
                            "name": ms.get("name"),
                            "code": ms.get("code"),
                            "subscription_fee": float(ms.get("subscriptionFee", 0.0)),
                            "status": ms.get("status")
                        })
                        
                    t_plus_data = []
                    tplus_obj = data.get("tplus", {})
                    for tp in tplus_obj.get("data", []):
                        t_plus_data.append({
                            "id": tp.get("id"),
                            "name": tp.get("name"),
                            "first_rate": float(tp.get("firstRate", 0.0)),
                            "status": tp.get("status")
                        })

                    return {
                        "account_no": account_no,
                        "margin_sure": margin_sure_views,
                        "t_plus": t_plus_data
                    }
                return {"margin_sure": [], "t_plus": []}
        except Exception as e:
            logger.debug("Loi khi lay margin addons detail: %s", str(e))
            return {"margin_sure": [], "t_plus": []}

    # --- 4.13 Danh sach khoan vay ---
    @catch_tcbs_unauthorized
    async def get_loans_list(self, account_no: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lay danh sach khoan vay tu /khaos/v1/loan/{accountNo}"""
        cache_key = account_no or "LOANS"
        now = time.time()
        if cache_key in self._loans_cache:
            ts, cached_val = self._loans_cache[cache_key]
            if (now - ts < 15.0 or len(cached_val) > 0) and len(cached_val) > 0:
                if now - ts < 10.0:
                    return cached_val

        headers = await self._get_headers()
        if not headers:
            return self._loans_cache.get(cache_key, (0, []))[1]

        if not account_no:
            account_no = await self._get_margin_account_no()
        url = f"{self.base_url}/khaos/v1/loan/{account_no}"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    result = []
                    for loan in data.get("content", []):
                        insurance = loan.get("insurance") or {}
                        principal = float(loan.get("remainingPrincipal") or loan.get("principal") or 0.0)
                        interest = float(loan.get("interest") or 0.0)
                        rate = float(loan.get("rate") or 0.0)
                        borrowed_days = int(loan.get("loanDays") or 0)
                        result.append({
                            "id": loan.get("id"),
                            "symbol": loan.get("symbol", ""),
                            "principal": principal,
                            "interest": interest,
                            "rate": rate,
                            "borrowed_days": borrowed_days,
                            "opening_date": loan.get("openingDate", ""),
                            "due_date": loan.get("dueDate", ""),
                            "pricing_policy_name": loan.get("pricingPolicyName", "PHỔ THÔNG"),
                            "renew_time": loan.get("renewTime", 0),
                            "max_renew_time": loan.get("maxRenewTime", 0),
                            "is_renewable": loan.get("isRenewable", False),
                            "reason_list": loan.get("reasonList", []),
                            "insurance_name": insurance.get("insuranceName", ""),
                            "insurance_code": insurance.get("insuranceCode", ""),
                            "insurance_fee": float(insurance.get("insuranceFee", 0.0))
                        })
                    if len(result) > 0:
                        self._loans_cache[cache_key] = (now, result)
                        return result
                if cache_key in self._loans_cache:
                    return self._loans_cache[cache_key][1]
                return []
        except Exception as e:
            logger.debug("Loi khi lay danh sach khoan vay: %s", str(e))
            if cache_key in self._loans_cache:
                return self._loans_cache[cache_key][1]
            return []

    # --- 4.17 Tra cuu no chi tiet ---
    @catch_tcbs_unauthorized
    async def get_margin_debt_details(self, account_no: Optional[str] = None) -> List[Dict[str, Any]]:
        """Tra cuu thong tin no margin chi tiet tu /erebos/v2/digital/margin-info"""
        headers = await self._get_headers()
        if not headers:
            return []

        if not account_no:
            account_no = await self._get_margin_account_no()
        custody_code = auth_provider.get_custody_code()
        url = f"{self.base_url}/erebos/v2/digital/margin-info"
        params = {
            "acctno": account_no,
            "custodycd": custody_code,
            "fromdate": (date.today() - timedelta(days=180)).strftime("%Y-%m-%d"),
            "todate": date.today().strftime("%Y-%m-%d"),
            "page": "1",
            "size": "50"
        }
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(url, headers=headers, params=params)
                if response.status_code == 200:
                    data = response.json()
                    resp_data = data.get("response", {})
                    result = []
                    for item in resp_data.get("data", []):
                        result.append({
                            "release_date": item.get("releaseDate"),
                            "overdue_date": item.get("overDueDate"),
                            "released_amount": float(item.get("releasedAmount", 0.0)),
                            "principal_debt": float(item.get("printAmount", 0.0)),
                            "interest_debt": float(item.get("intAmount", 0.0)),
                            "remaining_interest_fee": float(item.get("remainingInterestFee", 0.0)),
                            "paid_interest_fee": float(item.get("paidInterestFee", 0.0)),
                            "interest_rate": float(item.get("rate2", 0.0)),
                            "released_days": int(item.get("releasedDay", 0)),
                            "paid_fee": float(item.get("paidFee", 0.0)),
                            "remaining_fee": float(item.get("remainingFee", 0.0))
                        })
                    return result
                return []
        except Exception as e:
            logger.debug("Loi khi tra cuu margin info: %s", str(e))
            return []

    # --- 4.18 Tra cuu goi lai suat margin (Ladder, T_PLUS, Fixed) ---
    @catch_tcbs_unauthorized
    async def get_pricing_policies(self, account_no: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lay danh sach pricing policy kha dung tu /hydros/v1/account/{accountNo}/pricing-policy"""
        headers = await self._get_headers()
        if not headers:
            return []

        if not account_no:
            account_no = await self._get_margin_account_no()
        url = f"{self.base_url}/hydros/v1/account/{account_no}/pricing-policy"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    policies = data.get("data") if isinstance(data, dict) and "data" in data else data
                    result = []
                    if isinstance(policies, list):
                        for p in policies:
                            ladder_interest = []
                            for l in p.get("undueLadderValue", []):
                                ladder_interest.append({
                                    "id": l.get("id"),
                                    "rate": float(l.get("rate", 0.0)),
                                    "start_day": int(l.get("startDate", 0)),
                                    "due_day": int(l.get("dueDate", 0))
                                })

                            result.append({
                                "id": p.get("id"),
                                "name": p.get("name"),
                                "status": p.get("status"),
                                "policy_type": p.get("pricingPolicyType"),
                                "interest_type": p.get("undueInterestType"),
                                "fixed_rate": float(p.get("undueFixedValue", 0.0)),
                                "ladder_rates": ladder_interest,
                                "least_mass_rate": float(p.get("leastMassRate", 0.0)),
                                "greatest_mass_rate": float(p.get("greatestMassRate", 0.0)),
                                "overdue_interest": float(p.get("overdueInterest", 0.0)),
                                "extension_interest": float(p.get("extensionInterest", 0.0)),
                                "description": p.get("description", ""),
                                "valid_from": p.get("validFrom", ""),
                                "valid_to": p.get("validTo", "")
                            })
                    return result
                return []
        except Exception as e:
            logger.debug("Loi khi lay pricing policy: %s", str(e))
            return []

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
            return {
                "total_portfolio_value": 0.0,
                "total_invested_cost": 0.0,
                "total_unrealized_pnl": 0.0,
                "pnl_pct": 0.0,
                "total_cash": 0.0,
                "total_nav": 0.0,
                "num_positions": 0,
                "num_winning": 0,
                "num_losing": 0
            }

account_client = TCBSAccountClient()
