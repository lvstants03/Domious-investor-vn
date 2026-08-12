import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional, List
import pandas as pd

from src.wyckoff.base_detector import BaseDetector, BaseResult
from src.wyckoff.spring_detector import SpringDetector, SpringResult
from src.wyckoff.retest_detector import RetestDetector, RetestResult
from src.data_pipeline.indicators import indicators
from src.data_pipeline.market_regime import market_regime_calc

logger = logging.getLogger("dominus-investor.wyckoff.signal_generator")


@dataclass
class WyckoffSignalData:
    """Du lieu day du cua mot tin hieu Wyckoff duoc sinh ra."""
    symbol: str
    signal_date: date
    signal_type: str              # SPRING hoac RETEST
    base: BaseResult
    spring: Optional[SpringResult]
    retest: Optional[RetestResult]

    # Entry prices
    entry_aggressive: float       # Close cua phien Spring
    entry_standard: float         # Open ngay T+1 (uoc luong = Close * 1.003)
    entry_optimal: float          # Low Spring * 0.995 (dat lenh cho)

    # Risk management
    stop_loss: float              # Low Spring - ATR * 0.5
    target_price: float           # Dinh khang cu gan nhat truoc Base
    rr_ratio: float               # (Target - Entry_std) / (Entry_std - StopLoss)

    # Scoring
    z_score: Optional[float]      # Z-Score cua Volume phien Spring so voi 1 nam
    market_regime: str            # BULL / BEAR / SIDEWAYS
    composite_score: float        # Diem tong hop (0-100)
    win_probability: Optional[float] = None  # Se duoc cap nhat sau Monte Carlo


class WyckoffSignalGenerator:
    """
    Tong hop ket qua tu Base/Spring/Retest va sinh ra WyckoffSignalData day du.
    Bao gom tinh 3 muc Entry, Stop-loss ATR, Target, R/R Ratio, va Z-Score.
    """

    def __init__(self):
        self.base_det = BaseDetector()
        self.spring_det = SpringDetector()
        self.retest_det = RetestDetector()

    def _find_target_price(self, df: pd.DataFrame, base: BaseResult) -> float:
        """
        Tim muc gia muc tieu (Target):
        Dinh cao nhat truoc Base (khang cu lich su).
        Neu khong co, dung resistance_level cua Base + 10%.
        """
        base_start_idx = df.index[df["trade_date"] <= base.start_date].tolist()
        if base_start_idx:
            pre_base = df.iloc[: base_start_idx[-1]]
            if not pre_base.empty:
                target = float(pre_base["high"].max())
                # Neu Target gan bang Resistance (it hon 5%), dung fallback
                if target <= base.resistance_level * 1.05:
                    target = base.resistance_level * 1.10
                return round(target, 0)
        return round(base.resistance_level * 1.10, 0)

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Optional[WyckoffSignalData]:
        """
        Chay day du pipeline Wyckoff cho 1 ma co phieu.
        Tra ve WyckoffSignalData hoac None neu khong du dieu kien.
        """
        if df is None or len(df) < 80:
            return None

        df = df.sort_values("trade_date").reset_index(drop=True)

        # --- Buoc 1: Phat hien Base ---
        base = self.base_det.detect_base(df, lookback=60)
        if base is None:
            return None

        # --- Buoc 2: Phat hien Spring ---
        spring = self.spring_det.detect_spring(df, base)
        if spring is None:
            return None

        # --- Buoc 3: Tim Retest (khong bat buoc) ---
        retest = self.retest_det.detect_retest(df, base, spring)

        # Xac dinh loai tin hieu
        signal_type = "RETEST" if retest else "SPRING"

        # --- Buoc 4: Tinh ATR ---
        atr_val = indicators.atr_latest(df["high"], df["low"], df["close"], period=14)
        if atr_val is None:
            atr_val = (spring.close_price - spring.low_price) * 0.5

        # --- Buoc 5: Tinh cac muc Entry ---
        entry_aggressive = spring.close_price
        entry_standard = round(spring.close_price * 1.003, 0)   # Uoc tinh Open T+1
        entry_optimal = round(spring.low_price * 0.995, 0)       # Dat lenh cho duoi Spring

        # --- Buoc 6: Tinh Stop-loss ---
        stop_loss = round(spring.low_price - atr_val * 0.5, 0)

        # --- Buoc 7: Tinh Target ---
        target_price = self._find_target_price(df, base)

        # --- Buoc 8: Tinh R/R Ratio ---
        risk = entry_standard - stop_loss
        reward = target_price - entry_standard
        rr_ratio = round(reward / risk, 2) if risk > 0 else 0.0

        # --- Buoc 9: Tinh Z-Score cua Volume phien Spring ---
        z_score = indicators.z_score_latest(df["volume"].astype(float), period=252)

        # --- Buoc 10: Phan loai Market Regime cua ma nay ---
        regime = market_regime_calc.classify_symbol_regime(df["close"])

        # --- Buoc 11: Tinh Composite Score (0-100) ---
        score = 50.0
        if spring.volume_ratio >= 2.0:
            score += 20.0
        elif spring.volume_ratio >= 1.5:
            score += 10.0

        if rr_ratio >= 3.0:
            score += 15.0
        elif rr_ratio >= 2.0:
            score += 8.0

        if regime == "BULL":
            score += 10.0
        elif regime == "BEAR":
            score -= 15.0

        if retest is not None:
            score += 5.0

        if z_score is not None and z_score > 1.5:
            score += 5.0

        composite_score = max(0.0, min(100.0, score))

        signal_date = retest.date if retest else spring.date

        logger.info(
            "Wyckoff Signal [%s] %s: Type=%s, Score=%.1f, R/R=%.2f, Regime=%s",
            symbol, signal_date, signal_type, composite_score, rr_ratio, regime
        )

        return WyckoffSignalData(
            symbol=symbol,
            signal_date=signal_date,
            signal_type=signal_type,
            base=base,
            spring=spring,
            retest=retest,
            entry_aggressive=entry_aggressive,
            entry_standard=entry_standard,
            entry_optimal=entry_optimal,
            stop_loss=stop_loss,
            target_price=target_price,
            rr_ratio=rr_ratio,
            z_score=z_score,
            market_regime=regime,
            composite_score=composite_score
        )


wyckoff_generator = WyckoffSignalGenerator()
