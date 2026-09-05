import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("dominus-investor.paper_trading.sector_exposure")


class SectorExposureGuard:
    """
    Bao ve danh muc khoi ri ro tap trung nganh.

    Nguong mac dinh:
    - Toi da 40% NAV vao 1 nganh
    - Toi da 20% NAV vao 1 ma

    Duoc goi trong PaperTradingEngine.create_paper_trade_from_signal()
    truoc khi mo lenh moi.
    """

    MAX_SECTOR_WEIGHT = 0.40     # 40% toi da 1 nganh
    MAX_POSITION_WEIGHT = 0.20   # 20% toi da 1 ma

    async def get_current_exposure(
        self, sector: str, db_session=None
    ) -> Tuple[float, float]:
        """
        Tinh phan tram NAV hien tai dang trong mot nganh va tong NAV.

        Tra ve (sector_weight: float, total_nav: float).
        sector_weight = tong gia tri vi the open trong nganh / total_nav.
        """
        try:
            from src.database.models import PaperTrade
            from src.data_pipeline.sector_flow_calculator import sector_calculator
            from sqlalchemy import select

            if db_session is None:
                return 0.0, 1.0

            result = await db_session.execute(
                select(PaperTrade).where(PaperTrade.status == "OPEN")
            )
            open_trades = list(result.scalars().all())

            if not open_trades:
                return 0.0, 1.0

            sector_value = 0.0
            total_value = 0.0

            for t in open_trades:
                pos_value = t.entry_price * t.quantity
                total_value += pos_value

                trade_sector = sector_calculator.get_sector_for_symbol(t.symbol)
                if trade_sector == sector:
                    sector_value += pos_value

            if total_value <= 0:
                return 0.0, 1.0

            return sector_value / total_value, total_value

        except Exception as e:
            logger.warning("[SectorGuard] Loi get_current_exposure: %s", e)
            return 0.0, 1.0

    async def can_open_position(
        self,
        symbol: str,
        sector: str,
        proposed_value: float,
        db_session=None,
    ) -> Tuple[bool, str]:
        """
        Kiem tra truoc khi mo vi the moi.

        Tra ve:
        - (True, "")          neu duoc phep mo lenh
        - (False, ly_do)      neu vuot nguong tap trung nganh
        """
        try:
            sector_weight, total_nav = await self.get_current_exposure(sector, db_session)

            if total_nav <= 0:
                return True, ""

            # Tinh them trong so sau khi mo lenh moi
            new_sector_weight = (sector_weight * total_nav + proposed_value) / (total_nav + proposed_value)
            new_position_weight = proposed_value / (total_nav + proposed_value)

            if new_sector_weight > self.MAX_SECTOR_WEIGHT:
                return (
                    False,
                    f"Overweight sector '{sector}': {new_sector_weight*100:.1f}% > {self.MAX_SECTOR_WEIGHT*100:.0f}%"
                )

            if new_position_weight > self.MAX_POSITION_WEIGHT:
                return (
                    False,
                    f"Vi the {symbol} qua lon: {new_position_weight*100:.1f}% > {self.MAX_POSITION_WEIGHT*100:.0f}%"
                )

            return True, ""

        except Exception as e:
            logger.warning("[SectorGuard] Loi can_open_position: %s", e)
            return True, ""   # Fail-open: cho phep mo lenh neu loi he thong

    async def get_sector_summary(self, db_session=None) -> List[Dict]:
        """
        Lay tong quan phan bo nganh hien tai cua portfolio.
        Dung cho UI Dashboard.
        """
        try:
            from src.database.models import PaperTrade
            from src.data_pipeline.sector_flow_calculator import (
                sector_calculator, SECTOR_DEFINITIONS
            )
            from sqlalchemy import select

            if db_session is None:
                return []

            result = await db_session.execute(
                select(PaperTrade).where(PaperTrade.status == "OPEN")
            )
            open_trades = list(result.scalars().all())

            if not open_trades:
                return []

            totals: Dict[str, float] = {}
            grand_total = 0.0

            for t in open_trades:
                pos_value = t.entry_price * t.quantity
                grand_total += pos_value
                sec = sector_calculator.get_sector_for_symbol(t.symbol)
                totals[sec] = totals.get(sec, 0.0) + pos_value

            if grand_total <= 0:
                return []

            summary = []
            for sec_key, value in sorted(totals.items(), key=lambda x: -x[1]):
                weight = value / grand_total
                sec_name = SECTOR_DEFINITIONS.get(sec_key, sec_key)
                summary.append({
                    "sector_key": sec_key,
                    "sector_name": sec_name,
                    "value_vnd": round(value),
                    "weight_pct": round(weight * 100, 1),
                    "is_overweight": weight > self.MAX_SECTOR_WEIGHT,
                })

            return summary

        except Exception as e:
            logger.warning("[SectorGuard] Loi get_sector_summary: %s", e)
            return []


sector_exposure_guard = SectorExposureGuard()
