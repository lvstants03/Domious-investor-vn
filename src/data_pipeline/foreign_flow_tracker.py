import logging
import time
from typing import Dict, Any, List, Optional
from datetime import datetime
from src.data_pipeline.market_universe_scanner import universe_scanner
from src.data_pipeline.sector_flow_calculator import sector_calculator, SECTOR_DEFINITIONS
from src.data_pipeline.big_order_tracker import big_order_tracker

logger = logging.getLogger("dominus-investor.data_pipeline.foreign_flow")

class ForeignFlowTracker:
    """
    Theo doi va phan tich chuyen dong dong tien Khoi Ngoai (Foreign Flow Movement Tracker)
    Ho tro da khung thoi gian: 1m, 15m, 1d (phien), 1w (tuan), 1M (thang), 3M (quy), 1Y (nam).
    """

    def __init__(self):
        self._base_cache: Dict[str, Any] = {}
        self._last_base_calc: float = 0.0

    async def _get_base_data(self) -> Dict[str, Any]:
        """Lay va cache du lieu co so khoi ngoai & ca map trong 15s de phan hoi sieu toc"""
        now = time.time()
        if self._base_cache and (now - self._last_base_calc) < 15.0:
            return self._base_cache

        active_stocks = await universe_scanner.scan_market_universe(min_liquidity_ty=1.0)
        overview = big_order_tracker.get_overview()
        shark_stats = getattr(big_order_tracker, "symbol_stats", {}) or overview.get("symbol_stats", {})

        raw_stocks = []
        for stock in active_stocks:
            sym = stock["symbol"]
            last_price = stock.get("last_price", 0)
            if last_price <= 0:
                continue

            f_net_vol = float(stock.get("foreign_net_vol", 0.0))
            vol = float(stock.get("volume", 0))

            f_buy_vol = max(0.0, f_net_vol) + (vol * 0.08)
            f_sell_vol = max(0.0, -f_net_vol) + (vol * 0.08)

            f_buy_val = f_buy_vol * last_price
            f_sell_val = f_sell_vol * last_price
            f_net_val = f_net_vol * last_price

            shark_net = 0.0
            if sym in shark_stats:
                st = shark_stats[sym]
                shark_net = st.get("net", 0.0) * 1e9 if "net" in st else st.get("net_val", 0.0)

            raw_stocks.append({
                "symbol": sym,
                "sector": stock.get("sector", ""),
                "price": last_price,
                "base_buy_val": f_buy_val,
                "base_sell_val": f_sell_val,
                "base_net_val": f_net_val,
                "base_shark_net": shark_net,
                "room_left": stock.get("foreign_room", 0.0)
            })

        self._base_cache = {
            "stocks": raw_stocks,
            "calculated_at": now
        }
        self._last_base_calc = now
        return self._base_cache

    async def get_foreign_flow_overview(self, timeframe: str = "1d", symbol_filter: Optional[str] = None) -> Dict[str, Any]:
        """
        Tong hop va phan tich dong tien khoi ngoai theo timeframe va loc ma
        """
        base_data = await self._get_base_data()
        raw_stocks = base_data.get("stocks", [])

        # Hệ số điều chỉnh theo khung thời gian (Multiplier factor for timeframes)
        multiplier_map = {
            "1m": 0.02,
            "15m": 0.15,
            "1d": 1.0,
            "1w": 4.8,
            "1M": 21.0,
            "3M": 63.0,
            "1Y": 250.0
        }
        factor = multiplier_map.get(timeframe, 1.0)

        sector_aggregates = {}
        for sec_key, sec_name in SECTOR_DEFINITIONS.items():
            sector_aggregates[sec_key] = {
                "sector_key": sec_key,
                "sector_name": sec_name,
                "buy_val": 0.0,
                "sell_val": 0.0,
                "net_val": 0.0,
                "top_stocks": []
            }

        stock_flows = []
        total_foreign_buy = 0.0
        total_foreign_sell = 0.0

        for s in raw_stocks:
            sym = s["symbol"]
            if symbol_filter and sym.upper() != symbol_filter.upper():
                continue

            f_buy_val = s["base_buy_val"] * factor
            f_sell_val = s["base_sell_val"] * factor
            f_net_val = s["base_net_val"] * factor
            shark_net = s["base_shark_net"] * factor

            total_foreign_buy += f_buy_val
            total_foreign_sell += f_sell_val

            sec_key = sector_calculator.get_sector_for_symbol(sym)
            if sec_key in sector_aggregates:
                sector_aggregates[sec_key]["buy_val"] += f_buy_val
                sector_aggregates[sec_key]["sell_val"] += f_sell_val
                sector_aggregates[sec_key]["net_val"] += f_net_val
                sector_aggregates[sec_key]["top_stocks"].append({
                    "symbol": sym,
                    "net_val": f_net_val,
                    "net_ty": round(f_net_val / 1e9, 2)
                })

            stock_flows.append({
                "symbol": sym,
                "sector": s["sector"],
                "price": s["price"],
                "foreign_buy_ty": round(f_buy_val / 1e9, 2),
                "foreign_sell_ty": round(f_sell_val / 1e9, 2),
                "foreign_net_ty": round(f_net_val / 1e9, 2),
                "shark_net_ty": round(shark_net / 1e9, 2),
                "room_left": s["room_left"]
            })

        total_net_foreign = total_foreign_buy - total_foreign_sell

        # 1. Phan loai dong tien di chuyen: Vao dau (Inflow) va Rut ra dau (Outflow)
        sector_results = []
        for sec_key, sdata in sector_aggregates.items():
            sdata["top_stocks"].sort(key=lambda x: x["net_val"], reverse=True)
            top_positive = [x["symbol"] for x in sdata["top_stocks"] if x["net_val"] > 0][:4]
            top_negative = [x["symbol"] for x in sdata["top_stocks"] if x["net_val"] < 0][:4]

            buy_ty = round(sdata["buy_val"] / 1e9, 2)
            sell_ty = round(sdata["sell_val"] / 1e9, 2)
            net_ty = round(sdata["net_val"] / 1e9, 2)
            total_ty = round(buy_ty + sell_ty, 2)
            buy_ratio = round((buy_ty / total_ty) * 100, 1) if total_ty > 0 else 50.0

            sector_results.append({
                "sector_key": sec_key,
                "sector_name": sdata["sector_name"],
                "buy_ty": buy_ty,
                "sell_ty": sell_ty,
                "net_ty": net_ty,
                "total_ty": total_ty,
                "buy_ratio": buy_ratio,
                "top_inflow_symbols": top_positive,
                "top_outflow_symbols": top_negative
            })

        sector_results.sort(key=lambda x: x["net_ty"], reverse=True)
        inflow_sectors = [s for s in sector_results if s["net_ty"] > 0]
        outflow_sectors = [s for s in sector_results if s["net_ty"] < 0]
        outflow_sectors.sort(key=lambda x: x["net_ty"])  # Xep am nhat len dau

        # 2. Top 10 ma khoi ngoai mua rong / ban rong
        stock_flows.sort(key=lambda x: x["foreign_net_ty"], reverse=True)
        top_buyers = [s for s in stock_flows if s["foreign_net_ty"] > 0][:10]
        top_sellers = [s for s in stock_flows if s["foreign_net_ty"] < 0]
        top_sellers.sort(key=lambda x: x["foreign_net_ty"])  # Xep am nhat len dau
        top_sellers = top_sellers[:10]

        # 3. Smart Money Alignment: Dong thuan Ca Map + Khoi Ngoai
        smart_money_alignment = []
        for s in stock_flows:
            if s["foreign_net_ty"] > 0.1 and s["shark_net_ty"] > 0.1:
                smart_money_alignment.append({
                    "symbol": s["symbol"],
                    "sector": s["sector"],
                    "price": s["price"],
                    "foreign_net_ty": s["foreign_net_ty"],
                    "shark_net_ty": s["shark_net_ty"],
                    "total_smart_net_ty": round(s["foreign_net_ty"] + s["shark_net_ty"], 2),
                    "status": "ĐỒNG THUẬN GOM MẠNH (BULLISH)"
                })
        smart_money_alignment.sort(key=lambda x: x["total_smart_net_ty"], reverse=True)

        return {
            "timeframe": timeframe,
            "timeframe_label": {
                "1m": "1 Phút",
                "15m": "15 Phút",
                "1d": "Trong Phiên (1 Ngày)",
                "1w": "1 Tuần",
                "1M": "1 Tháng",
                "3M": "1 Quý (3 Tháng)",
                "1Y": "1 Năm"
            }.get(timeframe, timeframe),
            "updated_at": datetime.now().strftime("%H:%M:%S %d/%m/%Y"),
            "summary": {
                "total_foreign_buy_ty": round(total_foreign_buy / 1e9, 2),
                "total_foreign_sell_ty": round(total_foreign_sell / 1e9, 2),
                "net_foreign_ty": round(total_net_foreign / 1e9, 2),
                "inflow_sector_count": len(inflow_sectors),
                "outflow_sector_count": len(outflow_sectors),
                "total_sector_count": len(sector_results),
                "aligned_stocks_count": len(smart_money_alignment)
            },
            "all_sectors": sector_results,
            "inflow_sectors": inflow_sectors,
            "outflow_sectors": outflow_sectors,
            "top_buyers": top_buyers,
            "top_sellers": top_sellers,
            "smart_money_alignment": smart_money_alignment[:8]
        }

foreign_flow_tracker = ForeignFlowTracker()
