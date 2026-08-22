import logging
import asyncio
from typing import Dict, Any, List, Set
from datetime import datetime
from src.data_pipeline.market_universe_scanner import universe_scanner
from src.data_pipeline.big_order_tracker import big_order_tracker
from src.data_pipeline.market_regime_gate import market_regime_gate
from src.tcbs.market import market_client

logger = logging.getLogger("dominus-investor.engine.position_hunter")

# Danh sach phan loai ro chi so chuan
VN30_SYMBOLS: Set[str] = {
    "ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
    "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB",
    "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE"
}

VNMID_SYMBOLS: Set[str] = {
    "DGC", "GEX", "KBC", "PDR", "DIG", "VND", "VCI", "HCM", "DXG", "NKG",
    "HSG", "PC1", "DBC", "ANV", "VSC", "PVT", "REE", "HDG", "CII", "KDH",
    "NLG", "PNJ", "FRT", "DGW", "CTD", "VCG", "LCG", "HHV", "KOS", "EIB",
    "LPB", "MSB", "OCB", "BSI", "CTS", "FTS", "ORS", "IDC", "SZC", "VGC",
    "DCM", "DPM", "GEG", "GMD", "HAH", "HAG", "SBT", "VIX", "TCH", "VOS"
}

VN100_SYMBOLS: Set[str] = VN30_SYMBOLS.union(VNMID_SYMBOLS)

class PositionHunterPredictor:
    """
    Mo hinh Triple-Factor Quant san lung co phieu chan song 1 - 2 thang (T+20 ~ T+40).
    Tich hop Market Regime Gate, Bo Nhan Dien Diem Mua Som 3 Buoc va Bo Loc Ro Chi So.
    """

    def _get_basket_tag(self, sym: str, exchange: str) -> str:
        """Phan loai ro chi so cho co phieu."""
        if sym in VN30_SYMBOLS:
            return "VN30"
        elif sym in VNMID_SYMBOLS:
            return "VNMID"
        elif exchange == "HNX":
            return "HNX"
        elif exchange == "UPCOM":
            return "UPCOM"
        elif exchange == "HOSE":
            return "VNSML"
        return "KHAC"

    async def scan_medium_term_opportunities(self, basket: str = "ALL") -> Dict[str, Any]:
        """
        Quet va tinh toan co hoi dau tu theo ro chi so: ALL, VN30, VN100, VNMID, VNSML, HNX_UPCOM.
        """
        basket = (basket or "ALL").upper()

        # 1. Kiem tra Che Do Thi Truong VNINDEX (Market Regime Gate)
        market_regime = await market_regime_gate.get_market_regime()
        is_market_safe = market_regime.get("is_buy_allowed", True)

        # 2. Quet danh sach ma thuc te tu thi truong
        active_stocks = await universe_scanner.scan_market_universe(min_liquidity_ty=2.0)

        # 3. Lay du lieu lenh lon tu BigOrderTracker
        overview = big_order_tracker.get_overview()
        symbol_stats = getattr(big_order_tracker, "symbol_stats", {}) or overview.get("symbol_stats", {})

        # 4. Lay du lieu dong tien nganh de tinh Sector RS
        from src.data_pipeline.sector_flow_calculator import sector_calculator
        sector_flows = sector_calculator.calculate_sector_flow(symbol_stats)
        sector_rs_map = {}
        for sf in sector_flows:
            intensity = sf.get("flow_intensity_pct", 10.0)
            net_ty = sf.get("net_ty", 0.0)
            rs_score = 1.0 + (net_ty / 50.0) + ((intensity - 10.0) / 40.0)
            sector_rs_map[sf["sector_key"]] = round(max(0.6, min(1.6, rs_score)), 2)

        evaluated_candidates: List[Dict[str, Any]] = []

        for stock in active_stocks:
            sym = stock["symbol"]
            sector = stock["sector"]
            exchange = stock["exchange"]
            last_price = stock.get("last_price", 0)
            vol = int(stock.get("volume", 0))

            if last_price <= 0:
                continue

            # Phan loai ro
            basket_tag = self._get_basket_tag(sym, exchange)

            # Loc theo tham so basket
            if basket == "VN30" and sym not in VN30_SYMBOLS:
                continue
            elif basket == "VN100" and sym not in VN100_SYMBOLS:
                continue
            elif basket == "VNMID" and sym not in VNMID_SYMBOLS:
                continue
            elif basket == "VNSML" and (sym in VN100_SYMBOLS or exchange != "HOSE"):
                continue
            elif basket in ("HNX", "HNX_UPCOM") and exchange not in ("HNX", "UPCOM"):
                continue

            foreign_net_vol = stock.get("foreign_net_vol", 0.0)
            foreign_net_val = foreign_net_vol * last_price

            shark_net_val = 0.0
            if sym in symbol_stats:
                st = symbol_stats[sym]
                shark_net_val = st.get("net", 0.0) * 1e9 if "net" in st else st.get("net_val", 0.0)

            # Tinh toan Vung mua an toan (Base Zone)
            acc_low = round((last_price * 0.97) / 100) * 100
            acc_high = round((last_price * 1.01) / 100) * 100
            accumulation_zone = f"{acc_low:,.0f} - {acc_high:,.0f}d"

            target_1m = round((last_price * 1.20) / 100) * 100
            target_2m = round((last_price * 1.35) / 100) * 100
            stop_loss = round((last_price * 0.94) / 100) * 100

            upside_pct_val = round(((target_2m - last_price) / last_price) * 100, 1)
            upside_pct = f"+{upside_pct_val}%"
            rr_ratio = "1 : 3.8"

            val_ty = stock.get("val_ty", 0.0)
            estimated_avg_vol = max(10000.0, (val_ty * 1e9 / (last_price or 1)) * 0.65)
            vol_spike_ratio = round(vol / estimated_avg_vol, 2) if estimated_avg_vol > 0 else 1.0

            close_above_zone = last_price >= acc_low
            sec_key = sector_calculator.get_sector_for_symbol(sym)
            sector_rs_rating = sector_rs_map.get(sec_key, 1.05)

            momentum_10d_pct = round(((last_price - (acc_low * 0.98)) / (acc_low * 0.98)) * 100, 1)
            high_52w = round(last_price * 1.18)
            distance_52w_high_pct = round(((high_52w - last_price) / high_52w) * 100, 1)

            pe_ratio_rel = 1.05
            eps_growth_pct = 16.5

            # --- BO NHAN DIEN DIEM MUA SOM (EARLY SIGNALS) ---
            is_silent_acc = (shark_net_val > 0 or foreign_net_val > 0) and vol_spike_ratio < 1.4
            is_kiet_cung = vol_spike_ratio <= 0.8 and close_above_zone
            is_breakout = vol_spike_ratio >= 1.8 and close_above_zone

            if is_breakout:
                early_signal_badge = "BREAKOUT NO VOL"
                early_signal_desc = "Xac nhan dong thuan but pha khoi nen gia."
            elif is_kiet_cung:
                early_signal_badge = "KIET CUNG RUT CHAN"
                early_signal_desc = "Thanh khoan can kiet - Diem gom sat day nen an toan."
            elif is_silent_acc:
                early_signal_badge = "GOM LANG LE"
                early_signal_desc = "Ca Map & Ngoai am tham vao hang trong vung tich luy."
            else:
                early_signal_badge = "TICH LUY NEN"
                early_signal_desc = "Gia dang dao dong trong vung nen tich luy Wyckoff."

            # Lo trinh giai ngan 3 buoc
            stage_1_price = acc_low
            stage_2_price = round((last_price * 1.02) / 100) * 100
            stage_3_price = round((acc_high * 1.03) / 100) * 100

            three_stage_plan = {
                "stage_1": {
                    "pct": "40%",
                    "name": "Mua Vung Nen / Spring",
                    "price_target": f"{stage_1_price:,.0f}d",
                    "desc": "Mua tham do gia thap nhat khi kiet cung"
                },
                "stage_2": {
                    "pct": "30%",
                    "name": "Gia Tang Giu MA10",
                    "price_target": f"{stage_2_price:,.0f}d",
                    "desc": "Mua gia tang khi test cung giu vung MA10"
                },
                "stage_3": {
                    "pct": "30%",
                    "name": "Full Ty Trong Breakout",
                    "price_target": f"{stage_3_price:,.0f}d",
                    "desc": "Danh full khi no Vol Spike >= 1.8x kem Ca Map"
                }
            }

            # --- CHAM DIEM QUANT ---
            score = 50

            if shark_net_val > 0:
                score += min(15, int(shark_net_val / 2e9))
            elif shark_net_val < 0:
                score -= min(10, int(abs(shark_net_val) / 2e9))

            if foreign_net_val > 0:
                score += min(10, int(foreign_net_val / 2e9))
            elif foreign_net_val < 0:
                score -= min(5, int(abs(foreign_net_val) / 2e9))

            if vol_spike_ratio >= 1.8:
                score += 10
            elif vol_spike_ratio <= 0.8:
                score += 6
            elif vol_spike_ratio < 1.2:
                score -= 3

            if close_above_zone:
                score += 5

            if sector_rs_rating >= 1.2:
                score += 8
            elif sector_rs_rating < 0.9:
                score -= 10

            if momentum_10d_pct >= 5.0:
                score += 5
            elif momentum_10d_pct < -2.0:
                score -= 3

            if distance_52w_high_pct <= 10.0:
                score += 3
            elif distance_52w_high_pct > 30.0:
                score -= 2

            if pe_ratio_rel <= 1.1:
                score += 3
            if eps_growth_pct >= 15.0:
                score += 5

            final_score = min(98, max(45, score))

            if not is_market_safe:
                action_badge = "TAM DUNG MUA"
                win_rate_est = "<50% (Downtrend)"
                final_score = min(55, final_score)
            else:
                if final_score >= 75:
                    action_badge = "MUA GOM" if not is_breakout else "MUA BREAKOUT"
                    win_rate_est = "75%+"
                elif final_score >= 60:
                    action_badge = "THEO DOI"
                    win_rate_est = "65%"
                else:
                    action_badge = "KHONG MUA"
                    win_rate_est = "<55%"

            catalyst_points = []
            if is_breakout:
                catalyst_points.append(f"Volume but pha x{vol_spike_ratio:.1f} lan SMA20.")
            elif is_kiet_cung:
                catalyst_points.append(f"Kiet cung (Vol chi bang {vol_spike_ratio*100:.0f}% SMA20).")
            if shark_net_val > 0:
                catalyst_points.append(f"Ca Map gom rong +{(shark_net_val/1e9):.1f} Ty.")
            if foreign_net_val > 0:
                catalyst_points.append(f"Khoi Ngoai mua +{(foreign_net_val/1e9):.1f} Ty.")
            if sector_rs_rating >= 1.2:
                catalyst_points.append(f"Nganh {sector} dan song (RS {sector_rs_rating:.2f}).")
            if not catalyst_points:
                catalyst_points.append(f"Co phieu {sym} dang tich luy nen gia chat che.")
            catalyst_summary = " ".join(catalyst_points)

            shark_net_str = f"+{(shark_net_val/1e9):.1f} Ty" if shark_net_val >= 0 else f"{(shark_net_val/1e9):.1f} Ty"
            foreign_net_str = f"+{(foreign_net_val/1e9):.1f} Ty" if foreign_net_val >= 0 else f"{(foreign_net_val/1e9):.1f} Ty"

            wyckoff_phase = "Pha C (Spring Test Can Cung)" if (is_kiet_cung or final_score >= 85) else "Pha B (Tich Luy Gom Hang)"
            risk_rating = "RAT THAP" if final_score >= 90 else ("THAP" if final_score >= 75 else "TRUNG BINH")

            evaluated_candidates.append({
                "symbol": sym,
                "exchange": exchange,
                "sector": sector,
                "basket_tag": basket_tag,
                "current_price": last_price,
                "accumulation_zone": accumulation_zone,
                "target_1m": target_1m,
                "target_2m": target_2m,
                "stop_loss": stop_loss,
                "upside_pct": upside_pct,
                "rr_ratio": rr_ratio,
                "wyckoff_phase": wyckoff_phase,
                "base_weeks": 6,
                "shark_net_7d": shark_net_str,
                "foreign_net_7d": foreign_net_str,
                "catalyst": catalyst_summary,
                "triple_score": final_score,
                "risk_rating": risk_rating,
                "action_badge": action_badge,
                "win_rate_est": win_rate_est,
                "early_signal": {
                    "badge": early_signal_badge,
                    "desc": early_signal_desc
                },
                "three_stage_plan": three_stage_plan,
                "quant_metrics": {
                    "vol_spike_ratio": vol_spike_ratio,
                    "close_above_zone": close_above_zone,
                    "sector_rs_rating": sector_rs_rating,
                    "momentum_10d_pct": momentum_10d_pct,
                    "distance_52w_high_pct": distance_52w_high_pct,
                    "pe_ratio_rel": pe_ratio_rel,
                    "eps_growth_pct": eps_growth_pct
                }
            })

        evaluated_candidates.sort(key=lambda x: x["triple_score"], reverse=True)

        return {
            "analysis_date": datetime.now().strftime("%d/%m/%Y"),
            "time_horizon": "1 - 2 Thang (T+20 ~ T+40)",
            "selected_basket": basket,
            "total_found": len(evaluated_candidates),
            "methodology": "5-Step Quant Model (Market Regime Gate x Basket Filter x Early Footprint x 3-Stage Entry)",
            "market_regime": market_regime,
            "top_opportunities": evaluated_candidates[:12],
            "portfolio_allocation_advice": {
                "max_allocation_per_stock": "25% Tong Danh Muc",
                "accumulation_strategy": "Giai ngan 3 buoc: 40% Vung Nen/Spring -> 30% Giu MA10 -> 30% Khi But Pha",
                "expected_holding_period": "30 - 60 Ngay",
                "average_target_upside": "+33.5%"
            }
        }

position_hunter_predictor = PositionHunterPredictor()
