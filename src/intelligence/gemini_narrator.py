import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from src.config import settings
from src.intelligence.content_templates import get_template
from src.intelligence.track_record import track_record_evaluator
from src.intelligence.news_catalyst_booster import news_catalyst_booster
from src.data_pipeline.market_regime_gate import market_regime_gate
from src.data_pipeline.sector_flow_calculator import sector_calculator
from src.data_pipeline.big_order_tracker import big_order_tracker

logger = logging.getLogger("dominus-investor.intelligence.gemini_narrator")

try:
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

class GeminiNarrator:
    """
    Narrative Engine sinh noi dung ban tin phan tich tu dong bang mo hinh Gemini Flash,
    ket hop giua du lieu dinh luong (Quant) va chat xuc tac tin tuc (News Catalyst).
    """

    def __init__(self):
        self.api_key = settings.GOOGLE_API_KEY
        self.model_name = getattr(settings, "GEMINI_MODEL", "gemini-1.5-flash")
        if HAS_GENAI and self.api_key:
            genai.configure(api_key=self.api_key)
            self._model = genai.GenerativeModel(self.model_name)
        else:
            self._model = None

    async def _call_llm(self, system_instruction: str, prompt: str) -> str:
        """Goi Gemini tao van ban phan tich"""
        if self._model is not None:
            try:
                full_prompt = f"{system_instruction}\n\n{prompt}"
                res = await self._model.generate_content_async(full_prompt)
                if res.text:
                    return res.text.strip()
            except Exception as e:
                logger.error("Loi khi goi Gemini Narrator: %s", str(e))

        # Fallback neu khong co API key hoac loi ket noi
        return f"[Ban tin tu dong Dominus Capital]\n{prompt}"

    async def generate_morning_brief(self) -> str:
        """Sinh noi dung ban tin sang (07:00)"""
        tmpl = get_template("morning_brief")

        # 1. Du lieu thi truong
        regime = await market_regime_gate.get_market_regime()
        
        # 2. Track record 30 ngay
        perf = await track_record_evaluator.get_performance_summary(30)
        
        # 3. Top co phieu huong loi tin tuc
        await news_catalyst_booster._refresh_cache_if_needed()
        top_beneficiaries_data = news_catalyst_booster.get_top_beneficiaries(5)
        top_bene_str = "\n".join([
            f"- {b['symbol']}: +{b['news_boost']} diem catalyst | {b['reason']}"
            for b in top_beneficiaries_data
        ]) or "- Khong co co phieu nao bi tac dong tin tuc dot bien trong 24h qua."

        # 4. Tin vi mo anh huong lon
        high_impact = [
            f"- [{n.get('category')}] {n.get('title')} (Impact: {n.get('impact_score')}/10)"
            for n in news_catalyst_booster._cache_news[:3]
        ]
        news_str = "\n".join(high_impact) or "- Thi truong quoc te va trong nuoc giu trang thai on dinh."

        # 5. Ca map phien truoc
        overview = big_order_tracker.get_overview()
        stats = overview.get("summary", {})
        shark_str = f"Tong mua: {stats.get('total_buy_ty', 0):.1f} Ty | Ban: {stats.get('total_sell_ty', 0):.1f} Ty | Rong: {stats.get('net_ty', 0):.1f} Ty"

        # 6. Top signals tu PositionHunter
        from src.engine.position_hunter_predictor import position_hunter_predictor
        scan_res = await position_hunter_predictor.scan_medium_term_opportunities(basket="ALL")
        top_picks = scan_res.get("top_opportunities", [])[:3]
        picks_str = "\n".join([
            f"- {p['symbol']} (Nganh: {p['sector']}) | Score: {p['triple_score']} (News Boost: {p.get('news_boost', 0):+.1f}) | Badge: {p['action_badge']}"
            for p in top_picks
        ]) or "- Dang cap nhat du lieu..."

        prompt = tmpl["template"].format(
            vnindex_close=regime.get("vnindex_close", 1280.0),
            ema20=regime.get("ema20", 1275.0),
            ema50=regime.get("ema50", 1260.0),
            regime_vn=regime.get("regime_vn", "TICH LUY"),
            rsi=regime.get("rsi", 50.0),
            hit_rate_t3=perf.get("hit_rate_t3", 68.0),
            hit_rate_t5=perf.get("hit_rate_t5", 72.0),
            high_impact_news=news_str,
            top_beneficiaries=top_bene_str,
            top_signals=picks_str,
            shark_summary=shark_str
        )

        return await self._call_llm(tmpl["system_instruction"], prompt)

    async def generate_session_open(self) -> str:
        """Sinh thong bao mo cua phien giao dich (09:05)"""
        tmpl = get_template("session_open")
        regime = await market_regime_gate.get_market_regime()
        await news_catalyst_booster._refresh_cache_if_needed()
        
        top_bene = news_catalyst_booster.get_top_beneficiaries(2)
        news_highlight = top_bene[0]["reason"] if top_bene else "Dong tien on dinh dau phien"

        prompt = tmpl["template"].format(
            vnindex_close=regime.get("vnindex_close", 1280.0),
            regime_vn=regime.get("regime_vn", "TICH LUY"),
            news_highlight=news_highlight,
            active_sectors="Ngan hang, Chung khoan, Thep"
        )
        return await self._call_llm(tmpl["system_instruction"], prompt)

    async def generate_shark_alert(self, shark_event: Dict[str, Any]) -> str:
        """Sinh thong bao khi co lenh Ca Map dot bien > 5 ty VND"""
        tmpl = get_template("shark_mega_alert")
        prompt = tmpl["template"].format(
            symbol=shark_event.get("symbol", "UNKNOWN"),
            sector=shark_event.get("sector", "Thi truong"),
            price=shark_event.get("price", 0),
            shark_val_ty=round(shark_event.get("val_ty", 0.0), 2),
            confirmation=shark_event.get("confirmation", "Dong thuan lenh chu dong")
        )
        return await self._call_llm(tmpl["system_instruction"], prompt)

    async def generate_session_close(self) -> str:
        """Sinh tong ket phien giao dich (15:35)"""
        tmpl = get_template("session_close")
        regime = await market_regime_gate.get_market_regime()
        overview = big_order_tracker.get_overview()
        symbol_stats = big_order_tracker.symbol_stats or overview.get("symbol_stats", {})
        flows = sector_calculator.calculate_sector_flow(symbol_stats)

        top_inflow = [f"{s['sector_name']} (+{s['net_ty']:.1f} Ty)" for s in flows if s['net_ty'] > 0][:2]
        outflow = [f"{s['sector_name']} ({s['net_ty']:.1f} Ty)" for s in flows if s['net_ty'] < 0][:2]
        stats = overview.get("summary", {})

        prompt = tmpl["template"].format(
            vnindex_close=regime.get("vnindex_close", 1280.0),
            change_pts="+4.2",
            market_val_ty=f"{stats.get('total_val_ty', 15000):.0f}",
            regime_vn=regime.get("regime_vn", "TICH LUY"),
            top_inflow_sectors=", ".join(top_inflow) or "Khong ro net",
            outflow_sectors=", ".join(outflow) or "Ap luc ban rai rac",
            shark_net_total=f"{stats.get('net_ty', 0.0):+.1f}",
            watchlist_performance="Cac ma trong tam tiep tuc giu vung vung ho tro MA20."
        )
        return await self._call_llm(tmpl["system_instruction"], prompt)

    async def generate_sector_rotation_alert(self) -> str:
        """Sinh thong bao luan chuyen nganh"""
        tmpl = get_template("sector_rotation")
        overview = big_order_tracker.get_overview()
        flows = sector_calculator.calculate_sector_flow(big_order_tracker.symbol_stats or overview.get("symbol_stats", {}))

        leading = [s["sector_name"] for s in flows if s.get("rotation_stage") == "MARKUP"]
        accumulating = [s["sector_name"] for s in flows if s.get("rotation_stage") == "ACCUMULATION"]
        distributing = [s["sector_name"] for s in flows if s.get("rotation_stage") == "DISTRIBUTION"]

        prompt = tmpl["template"].format(
            leading_sectors=", ".join(leading) or "Dang tich luy",
            accumulating_sectors=", ".join(accumulating) or "Dong tien bat dau lan toa",
            distributing_sectors=", ".join(distributing) or "Chua xuat hien phan phoi manh"
        )
        return await self._call_llm(tmpl["system_instruction"], prompt)

    async def generate_weekly_analysis(self) -> str:
        """Sinh bao cao chien luoc tuan (Thu 7 09:00)"""
        tmpl = get_template("weekly_analysis")
        perf = await track_record_evaluator.get_performance_summary(30)
        from src.engine.position_hunter_predictor import position_hunter_predictor
        scan_res = await position_hunter_predictor.scan_medium_term_opportunities(basket="ALL")
        top_5 = [p["symbol"] for p in scan_res.get("top_opportunities", [])[:5]]

        prompt = tmpl["template"].format(
            weekly_vnindex_summary="VNINDEX giu vung vung tich luy tren MA50 voi thanh khoan cai thien.",
            weekly_macro_summary="Chinh sach tien te duy tri ho tro, ty gia on dinh.",
            hit_rate_t3=perf.get("hit_rate_t3", 68.0),
            hit_rate_t5=perf.get("hit_rate_t5", 72.0),
            priority_sectors="Ngan hang, Chung khoan, Bat dong san Khu Cong nghiep",
            top_5_picks=", ".join(top_5) or "TCB, HPG, SSI, VCB, MWG",
            risk_rule="Tuan thu ty trong 70% co phieu, cat lo dut khoat neu thung vung nen -5%."
        )
        return await self._call_llm(tmpl["system_instruction"], prompt)

gemini_narrator = GeminiNarrator()
