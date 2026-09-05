import logging
import threading
from datetime import date, timedelta
from typing import Dict, Optional, Tuple

import pandas as pd

logger = logging.getLogger("dominus-investor.data_pipeline.ohlcv_cache")

_LOOKBACK_DAYS = 380        # ~252 phien giao dich + buffer nghi le
_CACHE_TTL_DAYS = 1         # Lam moi cache moi ngay giao dich


class OHLCVDailyCache:
    """
    Cache OHLCV ngay cho tung ma, TTL = 1 ngay giao dich.
    Cung cap get_52w_high() va get_base_info() cho PositionHunterPredictor.

    Thread-safe: dung threading.Lock de tranh race condition khi warm-up
    nhieu ma song song tu scheduler.
    """

    def __init__(self):
        self._store: Dict[str, Tuple[pd.DataFrame, date]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_ohlcv_df(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        Tra ve DataFrame OHLCV cua symbol (sorted asc theo trade_date).
        Tu dong fetch neu chua co hoac cache het han.
        Tra ve None neu fetch that bai.
        """
        sym = symbol.upper()
        today = date.today()

        with self._lock:
            if sym in self._store:
                df, cached_date = self._store[sym]
                if cached_date == today:
                    return df

        df = self._fetch(sym)
        if df is not None and not df.empty:
            with self._lock:
                self._store[sym] = (df, today)
        return df

    def get_52w_high(self, symbol: str) -> Optional[float]:
        """
        Tra ve gia cao nhat trong 252 phien (xap xi 1 nam giao dich).
        Tra ve None neu khong lay duoc du lieu.
        """
        df = self.get_ohlcv_df(symbol)
        if df is None or df.empty:
            return None
        try:
            window = df.tail(252)
            return float(window["high"].max())
        except Exception as e:
            logger.warning("Loi tinh 52w_high cho %s: %s", symbol, e)
            return None

    def get_base_info(self, symbol: str) -> Tuple[float, bool]:
        """
        Phat hien nen tich luy Wyckoff va tinh base_weeks thuc te.

        Tra ve (base_weeks: float, close_above_support: bool).
        Fallback: (0.0, False) neu khong co nen hoac loi fetch.
        """
        df = self.get_ohlcv_df(symbol)
        if df is None or len(df) < 30:
            return 0.0, False

        try:
            from src.wyckoff.base_detector import base_detector
            base = base_detector.detect_base(df, lookback=60)
            if base is None:
                return 0.0, False

            base_weeks = round(base.base_length_days / 5.0, 1)

            # Xem gia dong cua cuoi co nam trong vung nen hay khong
            last_close = float(df["close"].iloc[-1])
            close_above_support = last_close >= base.support_level

            return base_weeks, close_above_support

        except Exception as e:
            logger.warning("Loi detect_base cho %s: %s", symbol, e)
            return 0.0, False

    def warm_up(self, symbols: list) -> None:
        """
        Pre-fetch OHLCV cho danh sach symbols (goi sau 16:30 hang ngay).
        Chay dong bo, co delay de tranh rate limit vnstock VCI.
        """
        import time
        logger.info("OHLCVDailyCache warm-up bat dau cho %d ma...", len(symbols))
        success = 0
        for sym in symbols:
            try:
                df = self.get_ohlcv_df(sym)
                if df is not None:
                    success += 1
            except Exception as e:
                logger.debug("Loi warm-up %s: %s", sym, e)
            time.sleep(0.5)   # Rate limit vnstock VCI: 0.5s / request
        logger.info("OHLCVDailyCache warm-up hoan tat: %d/%d ma.", success, len(symbols))

    def invalidate(self, symbol: str) -> None:
        """Xoa cache cua 1 ma de force re-fetch."""
        sym = symbol.upper()
        with self._lock:
            self._store.pop(sym, None)

    def clear(self) -> None:
        """Xoa toan bo cache."""
        with self._lock:
            self._store.clear()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fetch(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV tu vnstock VCI qua OHLCVFetcher (sync version).
        Lay _LOOKBACK_DAYS ngay de dam bao co du 252 phien giao dich.
        """
        try:
            from src.data_pipeline.ohlcv_fetcher import ohlcv_fetcher
            end_date = date.today().strftime("%Y-%m-%d")
            start_date = (date.today() - timedelta(days=_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
            df = ohlcv_fetcher.fetch_history_sync(symbol, start_date, end_date)
            if df is not None and not df.empty:
                df = df.sort_values("trade_date").reset_index(drop=True)
                logger.debug("OHLCVCache: da fetch %d phien cho %s", len(df), symbol)
            return df
        except Exception as e:
            logger.warning("OHLCVCache: khong the fetch %s: %s", symbol, e)
            return None


ohlcv_cache = OHLCVDailyCache()
