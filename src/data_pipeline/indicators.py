import logging
import pandas as pd
import pandas_ta as ta
import numpy as np
from typing import Optional

logger = logging.getLogger("dominus-investor.data_pipeline.indicators")


class TechnicalIndicators:
    """
    Tinh toan cac chi bao ky thuat dua tren du lieu OHLCV.
    Tat ca ham su dung pandas_ta de dam bao tinh chinh xac va toc do.
    """

    def rsi(self, close: pd.Series, period: int = 14) -> pd.Series:
        """RSI(period). Tra ve Series gia tri 0-100."""
        result = ta.rsi(close, length=period)
        return result if result is not None else pd.Series(dtype=float)

    def macd(self, close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
        """
        MACD. Tra ve DataFrame voi cot:
        - MACD_{fast}_{slow}_{signal}
        - MACDh_{fast}_{slow}_{signal}  (histogram)
        - MACDs_{fast}_{slow}_{signal}  (signal line)
        """
        result = ta.macd(close, fast=fast, slow=slow, signal=signal)
        return result if result is not None else pd.DataFrame()

    def atr(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """ATR(period) — Average True Range."""
        result = ta.atr(high, low, close, length=period)
        return result if result is not None else pd.Series(dtype=float)

    def bollinger(self, close: pd.Series, period: int = 20, std: float = 2.0) -> pd.DataFrame:
        """
        Bollinger Bands. Tra ve DataFrame voi cot:
        - BBL_{period}_{std}  (lower)
        - BBM_{period}_{std}  (middle)
        - BBU_{period}_{std}  (upper)
        - BBB_{period}_{std}  (bandwidth)
        - BBP_{period}_{std}  (percent)
        """
        result = ta.bbands(close, length=period, std=std)
        return result if result is not None else pd.DataFrame()

    def ema(self, close: pd.Series, period: int) -> pd.Series:
        """EMA(period)."""
        result = ta.ema(close, length=period)
        return result if result is not None else pd.Series(dtype=float)

    def linear_regression_slope(self, series: pd.Series, period: int = 10) -> Optional[float]:
        """
        Do doc hoi quy tuyen tinh (Linear Regression Slope) cua N diem cuoi.
        Duong tinh = xu huong tang, am = xu huong giam.
        Tra ve float hoac None neu khong du du lieu.
        """
        if len(series) < period:
            return None
        y = series.iloc[-period:].values
        x = np.arange(period)
        try:
            slope = float(np.polyfit(x, y, 1)[0])
            return slope
        except Exception:
            return None

    def z_score(self, series: pd.Series, period: int = 252) -> pd.Series:
        """
        Z-Score so sanh moi diem voi trung binh cua chinh no trong N phien truoc.
        period=252 ~ 1 nam giao dich.
        Cong thuc: (x - mean_N) / std_N
        """
        roll_mean = series.rolling(period, min_periods=30).mean()
        roll_std = series.rolling(period, min_periods=30).std()
        z = (series - roll_mean) / roll_std.replace(0, np.nan)
        return z

    def rsi_latest(self, close: pd.Series, period: int = 14) -> Optional[float]:
        """Lay gia tri RSI moi nhat. Tra ve float hoac None."""
        rsi_series = self.rsi(close, period)
        if rsi_series.empty or rsi_series.isna().all():
            return None
        return float(rsi_series.dropna().iloc[-1])

    def macd_latest(self, close: pd.Series) -> Optional[dict]:
        """Lay gia tri MACD moi nhat. Tra ve dict {macd, signal, hist} hoac None."""
        macd_df = self.macd(close)
        if macd_df.empty:
            return None
        last = macd_df.dropna().iloc[-1] if not macd_df.dropna().empty else None
        if last is None:
            return None
        cols = list(macd_df.columns)
        return {
            "macd": float(last[cols[0]]),
            "hist": float(last[cols[1]]),
            "signal": float(last[cols[2]])
        }

    def atr_latest(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> Optional[float]:
        """Lay ATR moi nhat."""
        atr_series = self.atr(high, low, close, period)
        if atr_series.empty or atr_series.isna().all():
            return None
        return float(atr_series.dropna().iloc[-1])

    def z_score_latest(self, series: pd.Series, period: int = 252) -> Optional[float]:
        """Lay Z-Score moi nhat."""
        z = self.z_score(series, period)
        if z.empty or z.isna().all():
            return None
        return round(float(z.dropna().iloc[-1]), 2)


indicators = TechnicalIndicators()
