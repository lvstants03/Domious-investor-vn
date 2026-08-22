import logging
from typing import Dict, Any, List
from datetime import datetime, date

logger = logging.getLogger("dominus-investor.data_pipeline.sector_flow")

# 12 Nhóm ngành cốt lõi của thị trường chứng khoán Việt Nam
SECTOR_DEFINITIONS = {
    "NGAN_HANG": "Ngân Hàng",
    "BAT_DONG_SAN": "Bất Động Sản",
    "CHUNG_KHOAN": "Chứng Khoán",
    "THEP_VAT_LIEU": "Thép & Vật Liệu",
    "DAU_KHI_NANG_LUONG": "Dầu Khí & Năng Lượng",
    "BAN_LE_TIEU_DUNG": "Bán Lẻ & Tiêu Dùng",
    "CONG_NGHE_THONG_TIN": "Công Nghệ Thông Tin",
    "HOA_CHAT_PHAN_BON": "Hóa Chất & Phân Bón",
    "KHU_CONG_NGHIEP": "BĐS Khu Công Nghiệp",
    "VAN_TAI_LOGISTICS": "Vận Tải & Logistics",
    "THUY_SAN_NONG_NGHIEP": "Thủy Sản & Nông Nghiệp",
    "XAY_DUNG_DAU_TU_CONG": "Xây Dựng & ĐTC"
}

class SectorFlowCalculator:
    """Tính toán dòng tiền và xung lực luân chuyển ngành toàn thị trường động 100%"""
    
    def __init__(self):
        self._dynamic_sector_cache: Dict[str, str] = {}

    def register_symbol_sector(self, symbol: str, sector_name: str):
        """Đăng ký mapping ngành động cho mã mới từ TCBS tickerCommons"""
        sym_upper = symbol.strip().upper()
        # Chuẩn hóa tên ngành vào 12 nhóm chính
        mapped_key = "KHAC"
        sec_lower = sector_name.lower()
        if "ngân hàng" in sec_lower or "bank" in sec_lower:
            mapped_key = "NGAN_HANG"
        elif "chứng khoán" in sec_lower or "securities" in sec_lower:
            mapped_key = "CHUNG_KHOAN"
        elif "khu công nghiệp" in sec_lower or "kcn" in sec_lower:
            mapped_key = "KHU_CONG_NGHIEP"
        elif "bất động sản" in sec_lower or "real estate" in sec_lower:
            mapped_key = "BAT_DONG_SAN"
        elif "thép" in sec_lower or "kim loại" in sec_lower or "vật liệu" in sec_lower:
            mapped_key = "THEP_VAT_LIEU"
        elif "dầu khí" in sec_lower or "năng lượng" in sec_lower or "điện" in sec_lower:
            mapped_key = "DAU_KHI_NANG_LUONG"
        elif "công nghệ" in sec_lower or "it" in sec_lower or "viễn thông" in sec_lower:
            mapped_key = "CONG_NGHE_THONG_TIN"
        elif "hóa chất" in sec_lower or "phân bón" in sec_lower:
            mapped_key = "HOA_CHAT_PHAN_BON"
        elif "bán lẻ" in sec_lower or "tiêu dùng" in sec_lower or "thực phẩm" in sec_lower:
            mapped_key = "BAN_LE_TIEU_DUNG"
        elif "vận tải" in sec_lower or "logistics" in sec_lower or "cảng" in sec_lower:
            mapped_key = "VAN_TAI_LOGISTICS"
        elif "thủy sản" in sec_lower or "nông nghiệp" in sec_lower or "chăn nuôi" in sec_lower:
            mapped_key = "THUY_SAN_NONG_NGHIEP"
        elif "xây dựng" in sec_lower or "đầu tư công" in sec_lower or "hạ tầng" in sec_lower:
            mapped_key = "XAY_DUNG_DAU_TU_CONG"

        self._dynamic_sector_cache[sym_upper] = mapped_key

    def get_sector_for_symbol(self, symbol: str) -> str:
        sym = symbol.upper()
        if sym in self._dynamic_sector_cache:
            return self._dynamic_sector_cache[sym]
        
        try:
            from src.data_pipeline.sector_map import get_sector_by_symbol
            raw_sec = get_sector_by_symbol(sym)
            self.register_symbol_sector(sym, raw_sec)
            return self._dynamic_sector_cache.get(sym, "NGAN_HANG")
        except Exception:
            return "NGAN_HANG"

    def calculate_sector_flow(self, symbol_stats: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Gom dòng tiền từ symbol_stats (của big_order_tracker) theo 12 nhóm ngành
        """
        sector_aggregates = {}
        for sec_key, sec_display_name in SECTOR_DEFINITIONS.items():
            sector_aggregates[sec_key] = {
                "sector_key": sec_key,
                "name": sec_display_name,
                "total_buy_val": 0.0,
                "total_sell_val": 0.0,
                "net_val": 0.0,
                "total_val": 0.0,
                "order_count": 0,
                "lead_symbols": []
            }

        # Duyệt qua các mã thực tế phát sinh giao dịch lớn
        for sym, stat in symbol_stats.items():
            sec_key = self.get_sector_for_symbol(sym)
            if sec_key not in sector_aggregates:
                sec_key = "NGAN_HANG"

            # Ho tro ca don vi ty VND (stat['buy']) va VND (stat['buy_val'])
            if "buy" in stat:
                buy = float(stat.get("buy", 0.0)) * 1e9
                sell = float(stat.get("sell", 0.0)) * 1e9
                net = float(stat.get("net", 0.0)) * 1e9
            else:
                buy = float(stat.get("buy_val", 0.0))
                sell = float(stat.get("sell_val", 0.0))
                net = float(stat.get("net_val", 0.0))

            total = buy + sell

            agg = sector_aggregates[sec_key]
            agg["total_buy_val"] += buy
            agg["total_sell_val"] += sell
            agg["net_val"] += net
            agg["total_val"] += total
            agg["order_count"] += stat.get("count", 1)

            if net > 0:
                agg["lead_symbols"].append({
                    "symbol": sym,
                    "net_val": net,
                    "net_ty": round(net / 1e9, 2)
                })

        total_market_flow = sum(s["total_val"] for s in sector_aggregates.values()) or 1.0

        results = []
        for sec_key, data in sector_aggregates.items():
            net = data["net_val"]
            tot = data["total_val"]
            intensity = round((tot / total_market_flow) * 100, 2) if total_market_flow > 0 else 0.0
            
            # Sắp xếp top mã dẫn sóng
            data["lead_symbols"].sort(key=lambda x: x["net_val"], reverse=True)
            top_leads = [x["symbol"] for x in data["lead_symbols"][:3]]

            # Xác định chu kỳ luân chuyển ngành
            if net > 5e9 and intensity >= 10.0:
                stage = "MARKUP"
                stage_name = "BÙNG NỔ DẪN SÓNG"
            elif net > 0:
                stage = "ACCUMULATION"
                stage_name = "GOM HÀNG CHÂN SÓNG"
            elif net < -5e9 and intensity >= 10.0:
                stage = "DISTRIBUTION"
                stage_name = "PHÂN PHỐI / RÚT TIỀN"
            else:
                stage = "REACCUMULATION"
                stage_name = "TÁI TÍCH LŨY"

            results.append({
                "sector_key": sec_key,
                "sector_name": data["name"],
                "total_buy_val": data["total_buy_val"],
                "total_sell_val": data["total_sell_val"],
                "net_val": net,
                "total_buy_ty": round(data["total_buy_val"] / 1e9, 2),
                "total_sell_ty": round(data["total_sell_val"] / 1e9, 2),
                "net_ty": round(net / 1e9, 2),
                "order_count": data["order_count"],
                "flow_intensity_pct": intensity,
                "rotation_stage": stage,
                "stage": stage,
                "stage_name": stage_name,
                "stage_vn": stage_name,
                "lead_symbols": top_leads
            })

        results.sort(key=lambda x: x["net_ty"], reverse=True)
        return results

sector_calculator = SectorFlowCalculator()
SECTOR_MAP = {k: {"name": v, "symbols": []} for k, v in SECTOR_DEFINITIONS.items()}
