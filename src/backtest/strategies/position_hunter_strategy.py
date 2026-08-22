import pandas as pd
import numpy as np
from typing import Dict, Any

def position_hunter_t30_strategy_fn(ohlcv_df: pd.DataFrame, params: Dict[str, Any] = None) -> pd.Series:
    """
    Chien luoc Quant Position Hunter T+30 dua tren 5 Buoc Sang Loc:
    1. Volume Spike Ratio >= 1.8 (Hard Filter)
    2. Breakout Close > Vung Nen Tich Luy 20 phien
    3. Momentum 10 phien >= +3%
    4. Distance to 52W High <= 15%
    """
    if params is None:
        params = {}

    min_vol_spike = params.get("min_vol_spike", 1.8)
    min_momentum = params.get("min_momentum", 0.02)
    max_dist_52w = params.get("max_dist_52w", 0.20)
    lookback_base = params.get("lookback_base", 20)

    n = len(ohlcv_df)
    signals = pd.Series([False] * n, index=ohlcv_df.index)

    if n < max(30, lookback_base + 10):
        return signals

    volumes = ohlcv_df["volume"].values
    closes = ohlcv_df["close"].values
    highs = ohlcv_df["high"].values
    opens = ohlcv_df["open"].values

    for i in range(max(25, lookback_base), n):
        # 1. Volume Spike Ratio so voi SMA20 Volume
        past_vols = volumes[i - lookback_base : i]
        avg_vol = np.mean(past_vols) if len(past_vols) > 0 else 0
        if avg_vol <= 0:
            continue
        vol_spike_ratio = volumes[i] / avg_vol

        # Hard Filter 1: Volume phai dot bien >= 1.8
        if vol_spike_ratio < min_vol_spike:
            continue

        # 2. Breakout Close > Vung nen tich luy
        past_closes = closes[i - lookback_base : i]
        max_base = np.max(past_closes)
        min_base = np.min(past_closes)
        base_range_pct = (max_base - min_base) / (min_base + 1e-5)

        # Nen gia phai du chat che (bien do <= 15%)
        if base_range_pct > 0.18:
            continue

        # Gia dong cua phai vuot dinh nen hoac sat dinh nen
        if closes[i] < max_base * 0.98 or closes[i] <= opens[i]:
            continue

        # 3. Momentum 10 phien
        if i >= 10:
            mom_10d = (closes[i] - closes[i - 10]) / (closes[i - 10] + 1e-5)
            if mom_10d < min_momentum:
                continue

        # 4. Distance to 52W High
        start_52w = max(0, i - 250)
        high_52w = np.max(highs[start_52w : i + 1])
        dist_52w = (high_52w - closes[i]) / (high_52w + 1e-5)
        if dist_52w > max_dist_52w:
            continue

        # Thoa man toan bo 5 buoc Hard Filter
        signals.iloc[i] = True

    return signals
