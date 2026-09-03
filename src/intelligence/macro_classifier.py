import json
import logging
import re
from typing import Dict, Any, List, Optional
from sqlalchemy import select
from src.config import settings
from src.database.connection import get_db_session
from src.database.models import NewsItem
from src.data_pipeline.market_universe_scanner import universe_scanner
from src.data_pipeline.sector_map import SECTOR_MAPPING

logger = logging.getLogger("dominus-investor.intelligence.macro_classifier")

try:
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

class MacroClassifier:
    """
    Module phan tich noi dung tin tuc vi mo bang mo hinh Gemini Flash.
    Tu dong map tin tuc vao nhom nganh va giai quyet dong danh sach co phieu
    bi tac dong tu universe_scanner, khong hardcode ma co phieu.
    """

    def __init__(self):
        self.api_key = settings.GOOGLE_API_KEY
        self.model_name = getattr(settings, "GEMINI_MODEL", "gemini-1.5-flash")
        if HAS_GENAI and self.api_key:
            genai.configure(api_key=self.api_key)
            self._model = genai.GenerativeModel(self.model_name)
        else:
            self._model = None

    async def _build_sector_to_symbols_map(self) -> Dict[str, List[str]]:
        """
        Xay dung danh sach ma co phieu theo tung nganh tu dong tu universe_scanner va SECTOR_MAPPING.
        """
        mapping: Dict[str, List[str]] = {}
        
        # 1. Tu SECTOR_MAPPING san co
        for sym, sec in SECTOR_MAPPING.items():
            mapping.setdefault(sec, []).append(sym)

        # 2. Tu dynamic universe_scanner
        try:
            active_stocks = await universe_scanner.scan_market_universe(min_liquidity_ty=1.0)
            for item in active_stocks:
                sym = item.get("symbol")
                sec = item.get("sector") or SECTOR_MAPPING.get(sym)
                if sym and sec:
                    if sym not in mapping.setdefault(sec, []):
                        mapping[sec].append(sym)
        except Exception as e:
            logger.warning("Khong the lay universe dong cho classifier: %s", str(e))

        return mapping

    async def _call_gemini_classify(self, title: str, summary: str, available_sectors: List[str]) -> Dict[str, Any]:
        """
        Goi Gemini Flash de phan loai bai tin
        """
        sectors_str = ", ".join(available_sectors)
        prompt = f"""Ban la chuyen gia phan tich vi mo thi truong chung khoan Viet Nam. Hay phan tich bai tin sau va tra ve DUY NHAT dinh dang JSON hop le.

Tieu de: {title}
Tom tat: {summary}

Danh sach cac nhom nganh Viet Nam:
[{sectors_str}]

Yeu cau dinh dang JSON:
{{
  "category": "FED_RATE|NHNN_POLICY|EXCHANGE_RATE|COMMODITY|REAL_ESTATE|BANKING|TECH_GLOBAL|EXPORT|EARNINGS|MACRO_VIETNAM",
  "sentiment": 1,
  "impact_score": 7.5,
  "sectors_affected": ["Nganh 1", "Nganh 2"],
  "reason": "Giai thich ngan gon 1 cau ve ly do tac dong"
}}
Luu y: 
- sentiment chi lay 1 (tich cuc), -1 (tieu cuc), hoac 0 (trung lap)
- impact_score la so thuc tu 0.0 den 10.0
- sectors_affected phai nam trong danh sach cac nhom nganh da cung cap o tren."""

        if self._model is not None:
            try:
                response = await self._model.generate_content_async(prompt)
                raw_text = response.text.strip()
                # Loc bo markdown block neu co
                clean_json = re.sub(r"^```json\s*", "", raw_text)
                clean_json = re.sub(r"```$", "", clean_json).strip()
                return json.loads(clean_json)
            except Exception as e:
                logger.error("Loi khi goi Gemini API classify: %s", str(e))

        # Heuristic fallback neu chua cau hinh Gemini API
        return self._heuristic_fallback_classify(title, summary, available_sectors)

    def _heuristic_fallback_classify(self, title: str, summary: str, available_sectors: List[str]) -> Dict[str, Any]:
        """Fallback bang rule-based tu khoa khi chua co Gemini API key"""
        text = (title + " " + summary).lower()
        sectors_affected = []
        sentiment = 0
        impact = 5.0
        category = "MACRO_VIETNAM"

        if "lãi suất" in text or "nhnn" in text or "ngân hàng nhà nước" in text:
            category = "NHNN_POLICY"
            sectors_affected.extend(["Ngân hàng", "Chứng khoán", "Bất động sản"])
            sentiment = 1 if "giảm" in text or "hạ" in text else (-1 if "tăng" in text else 0)
            impact = 8.5
        elif "thép" in text or "quặng" in text:
            category = "COMMODITY"
            sectors_affected.append("Thép & Kim loại")
            sentiment = 1 if "tăng" in text or "kỷ lục" in text else (-1 if "giảm" in text else 0)
            impact = 7.5
        elif "dầu" in text or "brent" in text or "opec" in text:
            category = "COMMODITY"
            sectors_affected.append("Dầu khí")
            sentiment = 1 if "tăng" in text else (-1 if "giảm" in text else 0)
            impact = 7.0
        elif "bất động sản" in text or "nhà đất" in text or "trái phiếu" in text:
            category = "REAL_ESTATE"
            sectors_affected.append("Bất động sản")
            sentiment = 1 if "tháo gỡ" in text or "phục hồi" in text else (-1 if "vỡ nợ" in text or "khó khăn" in text else 0)
            impact = 7.5

        # Dam bao sectors hop le
        valid_sectors = [s for s in sectors_affected if s in available_sectors]

        return {
            "category": category,
            "sentiment": sentiment,
            "impact_score": impact,
            "sectors_affected": valid_sectors,
            "reason": "Phan loai tu dong boi he thong tu khoa fallback"
        }

    async def classify_unprocessed_news(self, limit: int = 10) -> int:
        """
        Duyet qua cac tin tuc chua duoc xu ly trong CSDL va gan nhan anh huong vi mo
        """
        sector_to_symbols = await self._build_sector_to_symbols_map()
        available_sectors = list(sector_to_symbols.keys())
        processed_count = 0

        try:
            async with get_db_session() as session:
                stmt = select(NewsItem).where(NewsItem.is_processed == False).limit(limit)
                res = await session.execute(stmt)
                unprocessed = res.scalars().all()

                for item in unprocessed:
                    result = await self._call_gemini_classify(item.title, item.summary or "", available_sectors)
                    
                    # Resolve sectors -> symbols dong
                    affected_symbols = []
                    for sec in result.get("sectors_affected", []):
                        for sym in sector_to_symbols.get(sec, []):
                            if sym not in affected_symbols:
                                affected_symbols.append(sym)

                    item.category = result.get("category", "MACRO_VIETNAM")
                    item.sentiment = int(result.get("sentiment", 0))
                    item.impact_score = float(result.get("impact_score", 0.0))
                    item.sectors_affected = result.get("sectors_affected", [])
                    item.symbols_affected = affected_symbols
                    item.is_processed = True
                    processed_count += 1

                await session.commit()
                logger.info("Da phan loai xong %d ban tin vi mo qua Gemini.", processed_count)
        except Exception as e:
            logger.error("Loi khi phan loai tin vi mo: %s", str(e))

        return processed_count

macro_classifier = MacroClassifier()
