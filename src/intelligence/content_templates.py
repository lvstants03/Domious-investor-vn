"""
Module quan ly cac template prompt cho Gemini Narrator
Dinh dang tieng Viet chuyen nghiep theo phong cach quy dau tu Dominus Capital.
"""
from typing import Any, Dict

TEMPLATES = {
    "morning_brief": {
        "version": "1.0",
        "system_instruction": "Ban la giam doc phan tich chien luoc tai Dominus Capital. Viet ban tin sang suc tich (~250 tu), tieng Viet chuan muc, co so lieu thuc te, khong dung tu cam doan hay khang dinh chac chan 100%, luon nhac nho quan tri rui ro.",
        "template": """THI TRUONG CHUNG:
- VNINDEX: {vnindex_close} | EMA20: {ema20} | EMA50: {ema50}
- Che do thi truong: {regime_vn} (RSI: {rsi})
- Hieu qua khuyen nghi 30 ngay qua: Hit Rate T+3 = {hit_rate_t3}% | T+5 = {hit_rate_t5}%

TIN VI MO TAC DONG DOT BIEN (24h qua):
{high_impact_news}

DANH SACH CO PHIEU HUONG LOI TU TIN TUC (Catalyst Boost):
{top_beneficiaries}

TOP 3 CO HOI TIEM NANG (Ket hop Quant Multi-Layer va Tin Tuc):
{top_signals}

DONG TIEN CA MAP QUA DEM / PHIEN TRUOC:
{shark_summary}

Yeu cau trinh bay:
1. Nhan dinh ngan ve xu huong phien nay
2. Danh gia tac dong vi mo va nhom nganh huong loi
3. Goi y hanh dong cu the (Gom / Quan sat / Phong thu)"""
    },

    "session_open": {
        "version": "1.0",
        "system_instruction": "Ban la chuyen vien giam sat thi truong thoi gian thuc. Viet thong bao dau gio giao dich (~120 tu), tap trung vao kich ban mo cua va vung gia quan trong.",
        "template": """VNINDEX mo phien: {vnindex_close} | Trang thai: {regime_vn}
Tin tuc nong truoc gio mo cua: {news_highlight}
Nhom nganh dang co luc cau chu dong: {active_sectors}
Luu y rui ro dau phien: Tranh fomo mua duoi trong 15 phut dau ATO neu khong co dong tien lon xac nhan."""
    },

    "shark_mega_alert": {
        "version": "1.0",
        "system_instruction": "Ban la he thong canh bao ca map tu dong. Thong bao ngay lap tuc khi phat hien lenh gom dot bien > 5 ty VND tren san.",
        "template": """CANH BAO CA MAP GOM LENH KHUNG:
- Co phieu: {symbol} ({sector})
- Gia khop: {price}d
- Gia tri gom rong dot bien: {shark_val_ty} Ty VND
- Tin hieu dong thuan: {confirmation}
- Ghi chu: Dong tien lon chu dong vao hang tai vung gia tich luy."""
    },

    "session_close": {
        "version": "1.0",
        "system_instruction": "Ban la chuyen gia tong ket phien tai Dominus Capital. Viet tong ket phien dong cua (~200 tu), danh gia muc do thanh cong cua cac nhom co phieu va dong tien ca map.",
        "template": """KET PHIEN GIAO DICH:
- VNINDEX dong cua: {vnindex_close} ({change_pts} diem) | Thanh khoan: {market_val_ty} Ty
- Che do hien tai: {regime_vn}
- Nganh hut tien manh nhat: {top_inflow_sectors}
- Nganh bi rut tien: {outflow_sectors}
- Hanh dong cua Ca Map: {shark_net_total} Ty
- Danh gia danh muc theo doi cua Dominus: {watchlist_performance}"""
    },

    "sector_rotation": {
        "version": "1.0",
        "system_instruction": "Ban la chuyen gia dinh luong dong tien luan chuyen nganh. Thong bao su thay doi ve vi the dong tien lon giua cac nhom nganh.",
        "template": """LUAN CHUYEN DONG TIEN NGANH (SECTOR ROTATION):
- Nganh buoc vao pha BUNG NO (Markup): {leading_sectors}
- Nganh dang duoc Ca Map AM THAM GOM (Accumulation T+7 ~ T+10): {accumulating_sectors}
- Nganh bi ap luc CHOT LOI (Distribution): {distributing_sectors}
- Chien luoc: Don dau dong tien truoc khi co phieu but pha."""
    },

    "weekly_analysis": {
        "version": "1.0",
        "system_instruction": "Ban la giam doc dau tu quy. Viet bao cao chien luoc tuan (~350 tu), he thong hoa buc tranh vi mo, dong tien lon va danh muc uu tien tuan toi.",
        "template": """BAO CAO CHIEN LUOC TUAN - DOMINUS CAPITAL:
- VNINDEX tuan qua: {weekly_vnindex_summary}
- Danh gia vi mo & tin tuc quoc te: {weekly_macro_summary}
- Kiem chung Track Record he thong: Hit Rate T+3 = {hit_rate_t3}%, T+5 = {hit_rate_t5}%
- Top 3 nganh trong tam don song tuan toi: {priority_sectors}
- Top 5 co phieu hoi tu day du tieu chi 5-Layer Quant: {top_5_picks}
- Nguyen tac quan tri: {risk_rule}"""
    }
}

def get_template(name: str) -> Dict[str, Any]:
    """Lay template noi dung theo ten"""
    return TEMPLATES.get(name, TEMPLATES["morning_brief"])
