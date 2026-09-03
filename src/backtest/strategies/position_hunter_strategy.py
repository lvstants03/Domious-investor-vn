import pandas as pd
import numpy as np
from typing import Dict, Any

def position_hunter_t30_strategy_fn(ohlcv_df: pd.DataFrame, params: Dict[str, Any] = None) -> pd.Series:
    """
    Chien luoc Quant Position Hunter T+30 nang cap 5-Layer toan dien:
    1. Hard Filter SMA200: Close >= SMA200 (hoac SMA50 neu du lieu < 200 phien) de loai bo Bull Trap downtrend
    2. Hard Filter Base Tightness: Base Range <= 15% trong 20 phien
    3. Volume Spike Ratio >= 1.8x SMA20
    4. Solid Breakout Candle (Chong no Vol cut dau / rau tren dai):
       - Rau nen tren <= 35% chieu dai nen: (High - Close) / (High - Low) <= 0.35
       - Do lon than nen tang >= +2.0%: Close >= Open * 1.02
       - Close vuot dinh nen: Close >= 0.995x Max Base
    5. Momentum 10 phien >= +2%
    6. Khoang cach toi dinh 52 tuan <= 18%
    """
    if params is None:
        params = {}

    min_vol_spike = params.get("min_vol_spike", 1.8)
    min_momentum = params.get("min_momentum", 0.02)
    max_dist_52w = params.get("max_dist_52w", 0.18)
    lookback_base = params.get("lookback_base", 20)
    use_sma200 = params.get("use_sma200_filter", True)
    max_upper_wick_ratio = params.get("max_upper_wick_ratio", 0.35)
    min_body_pct = params.get("min_body_pct", 0.02)

    n = len(ohlcv_df)
    signals = pd.Series([False] * n, index=ohlcv_df.index)

    if n < max(30, lookback_base + 10):
        return signals

    volumes = ohlcv_df["volume"].values
    closes = ohlcv_df["close"].values
    highs = ohlcv_df["high"].values
    lows = ohlcv_df["low"].values
    opens = ohlcv_df["open"].values

    # Tinh toan SMA200 va SMA50 cho toan chuoi
    sma200 = pd.Series(closes).rolling(200, min_periods=50).mean().values
    sma50 = pd.Series(closes).rolling(50, min_periods=20).mean().values

    for i in range(max(25, lookback_base), n):
        # 1. Hard Filter SMA200 / Trend Filter
        if use_sma200:
            trend_ma = sma200[i] if not np.isnan(sma200[i]) else sma50[i]
            if not np.isnan(trend_ma) and closes[i] < trend_ma * 0.98:
                continue

        # 2. Volume Spike Ratio so voi SMA20 Volume
        past_vols = volumes[i - lookback_base : i]
        avg_vol = np.mean(past_vols) if len(past_vols) > 0 else 0
        if avg_vol <= 0:
            continue
        vol_spike_ratio = volumes[i] / avg_vol

        if vol_spike_ratio < min_vol_spike:
            continue

        # 3. Base Tightness (Nen gia phai chat che <= 15%)
        past_closes = closes[i - lookback_base : i]
        max_base = np.max(past_closes)
        min_base = np.min(past_closes)
        base_range_pct = (max_base - min_base) / (min_base + 1e-5)

        if base_range_pct > 0.15:
            continue

        # 4. Solid Breakout Candle (Chong no Vol cut dau)
        candle_range = highs[i] - lows[i]
        if candle_range > 0:
            upper_wick = highs[i] - closes[i]
            upper_wick_ratio = upper_wick / candle_range
            if upper_wick_ratio > max_upper_wick_ratio:
                continue  # Bi ban nguoc cut dau - loai bo

        # Than nen tang thuc chat >= 2% va dong tren dinh nen
        if closes[i] < opens[i] * (1.0 + min_body_pct) or closes[i] < max_base * 0.995:
            continue

        # 5. Momentum 10 phien
        if i >= 10:
            mom_10d = (closes[i] - closes[i - 10]) / (closes[i - 10] + 1e-5)
            if mom_10d < min_momentum:
                continue

        # 6. Distance to 52W High
        start_52w = max(0, i - 250)
        high_52w = np.max(highs[start_52w : i + 1])
        dist_52w = (high_52w - closes[i]) / (high_52w + 1e-5)
        if dist_52w > max_dist_52w:
            continue

        signals.iloc[i] = True

    return signals
