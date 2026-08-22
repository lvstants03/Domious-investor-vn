import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("dominus-investor.engine.smart_margin_risk")

class SmartMarginRiskEngine:
    """
    Engine quan tri rui ro Margin nang cao, Stress-test chay tai khoan 
    va toi uu hoa chi phi lai vay bac thang (Ladder/T+)
    """

    @staticmethod
    def simulate_margin_stress_test(
        portfolio: List[Dict[str, Any]],
        cash_balance: float,
        margin_risk: Dict[str, Any],
        drop_percentages: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """
        Mo phong kich ban Stress-Test thi truong sut giam (3%, 5%, 7%, 10%)
        tinh toan bien dong Rtt va so tien/co phieu can co cau de tranh Call Margin.
        """
        if drop_percentages is None:
            drop_percentages = [0.03, 0.05, 0.07, 0.10]

        total_market_val = sum(float(p.get("market_value", 0.0)) for p in portfolio)
        outstanding_debt = float(margin_risk.get("outstanding", 0.0))
        accrued_interest = float(margin_risk.get("accrued_interest", 0.0))
        total_debt = outstanding_debt + accrued_interest

        current_rtt = float(margin_risk.get("rtt", 0.0))
        if current_rtt <= 0.0 or current_rtt >= 999.0:
            current_rtt = round(((total_market_val + cash_balance) / total_debt * 100), 2) if total_debt > 0 else 999.0

        maintenance_margin = float(margin_risk.get("maintenance_margin", 85.0))
        liquidation_margin = float(margin_risk.get("liquidation_margin", 80.0))

        # Danh gia muc do rui ro hien tai
        if current_rtt >= 130.0:
            health_status = "AN_TOAN_TUYET_DOI"
            health_desc = "Ty le ky quy o muc an toan cao, khong co nguy co bi Call Margin."
            health_color = "green"
        elif current_rtt >= 100.0:
            health_status = "CANH_BAO_THEO_DOI"
            health_desc = "Ty le ky quy trung binh. Can theo doi sat khi thi truong bien dong manh."
            health_color = "yellow"
        elif current_rtt > 85.0:
            health_status = "NGUY_HIEM_CAN_HA_TY_TRONG"
            health_desc = "Tiem can nguong Call Margin! Nen chu dong ha bot vi the margin."
            health_color = "orange"
        else:
            health_status = "VI_PHAM_CALL_MARGIN"
            health_desc = "Tai khoan da vi pham nguong Call Margin! Can nop them tien hoac ban co phieu ngay."
            health_color = "red"

        # Tinh toan Stress Test qua tung muc giam
        scenarios = []
        for drop in drop_percentages:
            drop_pct_str = f"-{int(drop * 100)}%"
            simulated_market_val = total_market_val * (1.0 - drop)
            simulated_nav = simulated_market_val + cash_balance
            
            simulated_rtt = round((simulated_nav / total_debt * 100), 2) if total_debt > 0 else 999.0

            is_call = simulated_rtt <= maintenance_margin
            is_force_sell = simulated_rtt <= liquidation_margin

            # So tien mat can nop de dua Rtt ve muc an toan 120%
            target_rtt = 1.20
            required_cash_injection = 0.0
            if total_debt > 0 and simulated_rtt < 120.0:
                required_cash_injection = max(0.0, total_debt - (simulated_nav / target_rtt))

            # So tien co phieu can ban de tra bot no dua Rtt ve 120%
            required_stock_liquidation = 0.0
            if total_debt > 0 and simulated_rtt < 120.0:
                diff = (target_rtt * total_debt) - simulated_nav
                if diff > 0:
                    required_stock_liquidation = diff / (target_rtt - 1.0) if target_rtt > 1.0 else diff

            scenarios.append({
                "market_drop_pct": drop_pct_str,
                "simulated_portfolio_val": round(simulated_market_val, 2),
                "simulated_rtt": simulated_rtt,
                "is_margin_call": is_call,
                "is_force_sell": is_force_sell,
                "required_cash_injection": round(required_cash_injection, 2),
                "required_stock_liquidation": round(required_stock_liquidation, 2)
            })

        return {
            "current_rtt": current_rtt,
            "total_portfolio_value": total_market_val,
            "total_debt": total_debt,
            "outstanding_principal": outstanding_debt,
            "accrued_interest": accrued_interest,
            "health_status": health_status,
            "health_desc": health_desc,
            "health_color": health_color,
            "maintenance_threshold": maintenance_margin,
            "liquidation_threshold": liquidation_margin,
            "stress_test_scenarios": scenarios
        }

    @staticmethod
    def analyze_loan_ladder_optimization(
        debts: List[Dict[str, Any]],
        loans: List[Dict[str, Any]],
        pricing_policies: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Phan tich toi uu hoa chi phi lai vay margin, canh bao buoc nhay bac thang lai suat (T+)
        va nhac nho dao no truoc moc 90 ngay.
        """
        analyzed_loans = []
        total_daily_interest = 0.0
        alerts = []
        potential_monthly_savings = 0.0

        # Su dung nguon du lieu tu debts hoac loans (khaos/v1/loan)
        loan_sources = debts if debts and len(debts) > 0 else loans

        for item in loan_sources:
            principal = float(item.get("principal_debt") or item.get("principal") or item.get("remainingPrincipal") or 0.0)
            if principal <= 0:
                continue

            days = int(item.get("released_days") or item.get("borrowed_days") or item.get("loanDays") or 0)
            rate = float(item.get("interest_rate") or item.get("rate") or 13.5)
            daily_interest = (principal * (rate / 100.0)) / 365.0
            total_daily_interest += daily_interest
            symbol = item.get("symbol", "")
            sym_prefix = f"[{symbol}] " if symbol else ""

            # Kiem tra neu la goi T+ (thuong co moc 7 ngay hoac 14 ngay nhay lai suat)
            ladder_warning = None
            if days >= 5 and days <= 7:
                ladder_warning = "SAP_HET_UU_DAI_T7"
                # Lai suat nhay tu 7% len 13.5%
                jump_cost_diff = (principal * ((13.5 - rate) / 100.0)) / 365.0 * 30.0
                potential_monthly_savings += max(0.0, jump_cost_diff)
                alerts.append({
                    "type": "T_PLUS_LADDER_JUMP",
                    "severity": "HIGH",
                    "message": f"Khoan vay {sym_prefix}{principal:,.0f}d da vay {days} ngay, sap buoc sang ngay thu 8 voi lai suat nhay vot len 13.5%/nam. Nen chu dong chot loi hoac co cau tra bot no."
                })
            elif days >= 70:
                ladder_warning = "SAP_DAO_HAN_90_NGAY"
                alerts.append({
                    "type": "LOAN_MATURITY_90D",
                    "severity": "CRITICAL" if days >= 80 else "HIGH",
                    "message": f"Khoan vay {sym_prefix}{principal:,.0f}d da vay {days}/90 ngay, con {max(0, 90 - days)} ngay nua se dao han. Can chu dong gia han hoac dao no de tranh bi tinh lai suat qua han (150%)."
                })

            analyzed_loans.append({
                "symbol": symbol,
                "release_date": item.get("release_date") or item.get("opening_date") or "",
                "due_date": item.get("overdue_date") or item.get("due_date") or "",
                "principal_debt": principal,
                "current_rate": rate,
                "borrowed_days": days,
                "daily_interest_cost": round(daily_interest, 2),
                "ladder_warning": ladder_warning
            })

        # Goi y chinh sach lai suat toi uu
        recommended_policy = "PHỔ THÔNG (FIXED 13.5%)"
        if len(analyzed_loans) > 0:
            avg_days = sum(l["borrowed_days"] for l in analyzed_loans) / len(analyzed_loans)
            if avg_days <= 7:
                recommended_policy = "MARGIN T5 / T10 (Lai suat 5-10%/nam cho T+)"
            else:
                recommended_policy = "PHỔ THÔNG (FIXED 13.5%/nam) - Canh dao no 90 ngay"

        return {
            "total_active_loans": len(analyzed_loans),
            "total_daily_interest": round(total_daily_interest, 2),
            "total_monthly_interest_est": round(total_daily_interest * 30.0, 2),
            "potential_monthly_savings": round(potential_monthly_savings, 2),
            "recommended_policy": recommended_policy,
            "alerts": alerts,
            "loan_details": analyzed_loans
        }

smart_margin_risk_engine = SmartMarginRiskEngine()
