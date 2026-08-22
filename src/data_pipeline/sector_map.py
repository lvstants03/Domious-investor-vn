"""
Module mapping mã cổ phiếu với nhóm ngành chuẩn tại thị trường chứng khoán Việt Nam.
"""

SECTOR_MAPPING = {
    # Bất động sản
    "VHM": "Bất động sản", "VIC": "Bất động sản", "VRE": "Bất động sản", "NVL": "Bất động sản",
    "PDR": "Bất động sản", "DIG": "Bất động sản", "DXG": "Bất động sản", "KDH": "Bất động sản",
    "NLG": "Bất động sản", "CEO": "Bất động sản", "KBC": "Bất động sản", "IDC": "Bất động sản",
    "SZC": "Bất động sản", "TCH": "Bất động sản", "HDG": "Bất động sản", "HDC": "Bất động sản",
    
    # Ngân hàng
    "VCB": "Ngân hàng", "BID": "Ngân hàng", "CTG": "Ngân hàng", "TCB": "Ngân hàng",
    "MBB": "Ngân hàng", "VPB": "Ngân hàng", "ACB": "Ngân hàng", "HDB": "Ngân hàng",
    "STB": "Ngân hàng", "SHB": "Ngân hàng", "TPB": "Ngân hàng", "VIB": "Ngân hàng",
    "MSB": "Ngân hàng", "LPB": "Ngân hàng", "OCB": "Ngân hàng", "SSB": "Ngân hàng",
    "EIB": "Ngân hàng", "NAB": "Ngân hàng", "BAB": "Ngân hàng", "BVB": "Ngân hàng",

    # Chứng khoán
    "SSI": "Chứng khoán", "VND": "Chứng khoán", "VCI": "Chứng khoán", "HCM": "Chứng khoán",
    "SHS": "Chứng khoán", "MBS": "Chứng khoán", "FTS": "Chứng khoán", "BSI": "Chứng khoán",
    "CTS": "Chứng khoán", "AGR": "Chứng khoán", "VIX": "Chứng khoán", "ORS": "Chứng khoán",

    # Thép & Tài nguyên cơ bản
    "HPG": "Thép & Kim loại", "HSG": "Thép & Kim loại", "NKG": "Thép & Kim loại",
    "TLH": "Thép & Kim loại", "VGS": "Thép & Kim loại", "POM": "Thép & Kim loại",

    # Dầu khí & Năng lượng
    "GAS": "Dầu khí", "PVD": "Dầu khí", "PVS": "Dầu khí", "BSR": "Dầu khí",
    "PLX": "Dầu khí", "PVT": "Dầu khí", "POW": "Dầu khí", "GEG": "Dầu khí",
    "PC1": "Dầu khí", "HDG": "Dầu khí", "REE": "Dầu khí", "NT2": "Dầu khí",

    # Công nghệ & Viễn thông
    "FPT": "Công nghệ", "CMG": "Công nghệ", "ELC": "Công nghệ", "FOX": "Công nghệ",
    "VGI": "Công nghệ", "CTR": "Công nghệ", "SAM": "Công nghệ",

    # Vận tải & Kho bãi (Logistics)
    "GMD": "Vận tải & Kho bãi", "HAH": "Vận tải & Kho bãi", "VSC": "Vận tải & Kho bãi",
    "PVT": "Vận tải & Kho bãi", "VJC": "Vận tải & Kho bãi", "HVN": "Vận tải & Kho bãi",
    "TMS": "Vận tải & Kho bãi", "VOS": "Vận tải & Kho bãi",

    # Phân bón & Hóa chất
    "DPM": "Phân bón & Hóa chất", "DCM": "Phân bón & Hóa chất", "DGC": "Phân bón & Hóa chất",
    "CSV": "Phân bón & Hóa chất", "BFC": "Phân bón & Hóa chất", "LAS": "Phân bón & Hóa chất",

    # Bán lẻ & Hàng tiêu dùng
    "MWG": "Bán lẻ", "FRT": "Bán lẻ", "PNJ": "Bán lẻ", "DGW": "Bán lẻ",
    "MSN": "Bán lẻ", "VNM": "Bán lẻ", "SAB": "Bán lẻ", "KDC": "Bán lẻ",

    # Công nghiệp & Thiết bị điện
    "GEE": "Công nghiệp", "GEX": "Công nghiệp", "DHC": "Công nghiệp", "VGC": "Công nghiệp",
    "PHR": "Công nghiệp", "DPR": "Công nghiệp", "GVR": "Công nghiệp",

    # Nông lâm thủy sản
    "VHC": "Nông lâm nghiệp", "ANV": "Nông lâm nghiệp", "IDI": "Nông lâm nghiệp",
    "BAF": "Nông lâm nghiệp", "DBC": "Nông lâm nghiệp", "HAG": "Nông lâm nghiệp",
    "HNG": "Nông lâm nghiệp",

    # Bảo hiểm
    "BVH": "Bảo hiểm", "BMI": "Bảo hiểm", "MIG": "Bảo hiểm", "PVI": "Bảo hiểm",

    # Mía đường
    "SBT": "Mía đường", "QNS": "Mía đường", "LSS": "Mía đường", "SLS": "Mía đường",
    
    # Xây dựng & Vật liệu
    "VC3": "Xây dựng", "CTD": "Xây dựng", "HBC": "Xây dựng", "VCG": "Xây dựng",
    "HHV": "Xây dựng", "LCG": "Xây dựng", "FCN": "Xây dựng", "C4G": "Xây dựng",
    "KSB": "Xây dựng", "BCC": "Xây dựng", "HT1": "Xây dựng", "VLB": "Xây dựng"
}

def get_sector_by_symbol(symbol: str) -> str:
    """Tra cuu nhom nganh cua ma co phieu"""
    if not symbol:
        return "Khác"
    sym = symbol.strip().upper()
    return SECTOR_MAPPING.get(sym, "Khác")
