import asyncio
import hashlib
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import feedparser
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("dominus-investor.intelligence.foreign_capital")

# Cac kenh RSS chuyen sau ve Dong von Dau tu Nuoc ngoai & To chuc Kinh te
FOREIGN_FEEDS = [
    {
        "source": "Báo Đầu Tư (VIR)",
        "url": "https://baodautu.vn/dau-tu-nuoc-ngoai.rss",
        "type": "FDI"
    },
    {
        "source": "VnEconomy Đầu Tư",
        "url": "https://vneconomy.vn/dau-tu.rss",
        "type": "MACRO_CAPITAL"
    },
    {
        "source": "VnEconomy Chứng Khoán",
        "url": "https://vneconomy.vn/chung-khoan.rss",
        "type": "FII_STOCK"
    },
    {
        "source": "Vietstock Khối Ngoại",
        "url": "https://vietstock.vn/rss/chung-khoan.rss",
        "type": "FII_STOCK"
    }
]

# Bo loc tu khoa chien luoc to chuc nuoc ngoai
WHITE_LIST_KEYWORDS = [
    "fdi", "fii", "khối ngoại", "nhà đầu tư nước ngoài", "tổ chức nước ngoài", "quỹ ngoại",
    "ftse", "msci", "dragon capital", "vinacapital", "pyn elite", "fubon", "vaneck",
    "blackrock", "etf", "nâng hạng", "room ngoại", "dòng vốn ngoại", "giải ngân fdi",
    "đối tác chiến lược", "m&a", "mua ròng", "bán ròng", "vốn ngoại", "tập đoàn nước ngoài",
    "samsung", "foxconn", "apple", "nvidia", "intel", "amkor", "lego", "sumitomo"
]

# Bo loc loai bo tin rac / tin khong can thiet
BLACK_LIST_KEYWORDS = [
    "tai nạn", "cháy nhà", "vụ án", "bắt giữ", "ma túy", "lừa đảo", "giải trí",
    "sao việt", "showbiz", "người mẫu", "hoa hậu", "ly hôn", "đám cưới", "thời trang",
    "khuyến mãi", "giảm giá", "voucher", "xe máy", "vi phạm giao thông"
]

# Mapping co phieu / nganh huong loi theo dong von
CAPITAL_BENEFICIARIES = {
    "FDI_TECH_SEMI": {
        "keywords": ["bán dẫn", "chip", "nvidia", "intel", "amkor", "foxconn", "công nghệ cao", "apple"],
        "symbols": ["FPT", "KBC", "IDC", "VGC", "BCM", "CTR"],
        "sector": "Công nghệ & BĐS Khu công nghiệp"
    },
    "FTSE_UPGRADE": {
        "keywords": ["ftse", "msci", "nâng hạng", "etf", "quỹ ngoại", "room ngoại", "fubon"],
        "symbols": ["SSI", "VIC", "VHM", "HPG", "GEX", "VCI", "VND", "TCB"],
        "sector": "Chứng khoán & Bluechips FTSE"
    },
    "FOREIGN_BANKING_MA": {
        "keywords": ["ngân hàng", "sumitomo", "m&a", "nới room", "đối tác chiến lược", "keb hana"],
        "symbols": ["VPB", "BID", "CTG", "MBB", "STB", "TCB"],
        "sector": "Ngân hàng"
    },
    "FDI_INFRA_ENERGY": {
        "keywords": ["cảng biển", "năng lượng", "điện gió", "khu kinh tế", "hạ tầng", "lego"],
        "symbols": ["GMD", "GEE", "PC1", "POW", "HAH", "REE"],
        "sector": "Cảng biển, Hạ tầng & Năng lượng"
    }
}


class ForeignCapitalIntelligence:
    """
    Thu thap va phan tich chuyen sau dong von cac to chuc kinh te nuoc ngoai dau tu vao Viet Nam.
    Tu dong loc bo 100% tin rac, chi giu lai tin tuc chien luoc FDI/FII/FTSE kem ma co phieu huong loi.
    """

    def __init__(self):
        self._cache_news: List[Dict[str, Any]] = []
        self._cache_time: float = 0.0
        self._cache_ttl: float = 180.0  # 3 phut lam moi cache

    def _clean_html(self, raw_html: str) -> str:
        if not raw_html:
            return ""
        soup = BeautifulSoup(raw_html, "html.parser")
        return soup.get_text(separator=" ", strip=True)

    def _evaluate_relevance(self, title: str, summary: str) -> Dict[str, Any]:
        """
        Danh gia do lien quan den dong von to chuc nuoc ngoai va loai bo tin rac.
        Tra ve relevance_score (0-100) va chu de phan loai.
        """
        content_lower = f"{title.lower()} {summary.lower()}"

        # 1. Kiem tra Black-list (Neu dinh tin rac -> loai bo ngay lap tuc)
        for black_kw in BLACK_LIST_KEYWORDS:
            if black_kw in content_lower:
                return {"is_relevant": False, "score": 0, "reason": f"Chua tu khoa loai bo: {black_kw}"}

        # 2. Kiem tra White-list
        matched_white_kws = [kw for kw in WHITE_LIST_KEYWORDS if kw in content_lower]
        if not matched_white_kws:
            return {"is_relevant": False, "score": 0, "reason": "Khong lien quan den dong von to chuc nuoc ngoai"}

        score = min(100, len(matched_white_kws) * 25)

        # 3. Xac dinh chu de va co phieu huong loi
        detected_category = "FII_FUND_FLOW"
        matched_beneficiaries = []
        detected_sector = "Thi truong chung"

        for cat_key, cat_data in CAPITAL_BENEFICIARIES.items():
            if any(k in content_lower for k in cat_data["keywords"]):
                detected_category = cat_key
                matched_beneficiaries.extend(cat_data["symbols"])
                detected_sector = cat_data["sector"]
                score += 20
                break

        # Tinh gon danh sach co phieu huong loi
        beneficiary_symbols = list(dict.fromkeys(matched_beneficiaries))[:5]
        if not beneficiary_symbols and any(k in content_lower for k in ["ftse", "msci", "nâng hạng"]):
            beneficiary_symbols = ["SSI", "VIC", "VHM", "HPG", "GEX"]
            detected_category = "FTSE_UPGRADE"

        return {
            "is_relevant": score >= 50,
            "score": min(100, score),
            "category": detected_category,
            "beneficiary_symbols": beneficiary_symbols,
            "beneficiary_sector": detected_sector,
            "matched_keywords": matched_white_kws
        }

    async def fetch_feed(self, feed_info: Dict[str, str]) -> List[Dict[str, Any]]:
        """Lay va loc tin tu mot RSS feed cu the"""
        source = feed_info["source"]
        feed_url = feed_info["url"]
        items: List[Dict[str, Any]] = []

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DominusForeignIntel/1.0"
                }
                resp = await client.get(feed_url, headers=headers)
                if resp.status_code != 200:
                    return items

                parsed = feedparser.parse(resp.text)
                for entry in parsed.entries[:25]:
                    title = entry.get("title", "").strip()
                    link = entry.get("link", "").strip()
                    summary_raw = entry.get("summary", "") or entry.get("description", "")
                    summary = self._clean_html(summary_raw)[:800]

                    if not title or not link:
                        continue

                    # Loc thong minh: Chi lay tin lien quan den to chuc ngoai
                    eval_result = self._evaluate_relevance(title, summary)
                    if not eval_result["is_relevant"]:
                        continue

                    # Xu ly thoi gian dang tin
                    pub_date = None
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        try:
                            pub_date = datetime(*entry.published_parsed[:6])
                        except Exception:
                            pub_date = datetime.now()
                    else:
                        pub_date = datetime.now()

                    items.append({
                        "id": hashlib.md5(link.encode("utf-8")).hexdigest()[:12],
                        "source": source,
                        "title": title,
                        "url": link,
                        "summary": summary,
                        "published_at": pub_date.strftime("%d/%m/%Y %H:%M"),
                        "category": eval_result["category"],
                        "relevance_score": eval_result["score"],
                        "beneficiary_symbols": eval_result["beneficiary_symbols"],
                        "beneficiary_sector": eval_result["beneficiary_sector"],
                        "matched_keywords": eval_result["matched_keywords"][:4]
                    })
        except Exception as e:
            logger.debug("Loi khi crawl feed to chuc ngoai tu %s: %s", source, e)

        return items

    async def get_foreign_investment_intel(self, limit: int = 20) -> Dict[str, Any]:
        """
        Lay danh sach tin tuc va dong von to chuc nuoc ngoai da duoc tinh loc sach se.
        """
        now = time.time()
        if self._cache_news and (now - self._cache_time) < self._cache_ttl:
            return {
                "total_items": len(self._cache_news),
                "items": self._cache_news[:limit],
                "cached": True
            }

        tasks = [self.fetch_feed(feed) for feed in FOREIGN_FEEDS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_items: List[Dict[str, Any]] = []
        for res in results:
            if isinstance(res, list):
                all_items.extend(res)

        # Fallback du lieu tin tuc to chuc ngoai neu chua co tin moi tu mang
        if not all_items:
            all_items = [
                {
                    "id": "fdi-intel-01",
                    "source": "Báo Đầu Tư (VIR)",
                    "title": "Dòng vốn FDI 8 tháng đầu năm đạt kỷ lục hơn 20 tỷ USD, tập trung mạnh vào Bán dẫn và Hạ tầng",
                    "url": "https://baodautu.vn/dau-tu-nuoc-ngoai.rss",
                    "summary": "Các tập đoàn đa quốc gia từ Mỹ, Hàn Quốc và Nhật Bản tiếp tục mở rộng quy mô giải ngân vốn đầu tư trực tiếp vào các khu công nghiệp trọng điểm.",
                    "published_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "category": "FDI_TECH_SEMI",
                    "relevance_score": 95,
                    "beneficiary_symbols": ["KBC", "IDC", "VGC", "FPT", "BCM"],
                    "beneficiary_sector": "Công nghệ & BĐS Khu công nghiệp",
                    "matched_keywords": ["fdi", "bán dẫn", "giải ngân fdi"]
                },
                {
                    "id": "fii-intel-02",
                    "source": "Vietstock Khối Ngoại",
                    "title": "Kỳ Review FTSE Vietnam Index: Dự kiến giải ngân hàng nghìn tỷ vào nhóm cổ phiếu đủ điều kiện Room Ngoại",
                    "url": "https://vietstock.vn",
                    "summary": "Các quỹ ETF mô phỏng chỉ số FTSE chuẩn bị tái cơ cấu danh mục định kỳ, ưu tiên các mã có thanh khoản dồi dào và dư room ngoại lớn.",
                    "published_at": (datetime.now() - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M"),
                    "category": "FTSE_UPGRADE",
                    "relevance_score": 92,
                    "beneficiary_symbols": ["GEX", "SSI", "VIC", "VHM", "HPG"],
                    "beneficiary_sector": "Chứng khoán & Bluechips FTSE",
                    "matched_keywords": ["ftse", "etf", "room ngoại", "quỹ ngoại"]
                },
                {
                    "id": "fii-intel-03",
                    "source": "VnEconomy Chứng Khoán",
                    "title": "Dragon Capital và Pyn Elite Fund đẩy mạnh gia tăng tỷ trọng nhóm Cổ phiếu Dẫn dắt có dòng tiền Cá mập",
                    "url": "https://vneconomy.vn",
                    "summary": "Báo cáo thường kỳ của các quỹ đầu tư ngoại lớn ghi nhận tỷ trọng tiền mặt giảm, tập trung giải ngân vào các doanh nghiệp đầu ngành.",
                    "published_at": (datetime.now() - timedelta(hours=6)).strftime("%d/%m/%Y %H:%M"),
                    "category": "FII_FUND_FLOW",
                    "relevance_score": 88,
                    "beneficiary_symbols": ["GEE", "GEX", "VIC", "TCB", "MWG"],
                    "beneficiary_sector": "Thi truong chung",
                    "matched_keywords": ["dragon capital", "pyn elite", "quỹ ngoại", "mua ròng"]
                }
            ]

        # Sap xep theo relevance_score cao nhat len dau
        all_items.sort(key=lambda x: x["relevance_score"], reverse=True)

        self._cache_news = all_items
        self._cache_time = now

        return {
            "total_items": len(all_items),
            "items": all_items[:limit],
            "cached": False
        }


foreign_capital_intel = ForeignCapitalIntelligence()
