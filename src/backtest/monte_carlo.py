import logging
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional
import pandas as pd

logger = logging.getLogger("dominus-investor.backtest.monte_carlo")

N_SIMULATIONS = 10_000
POSITIVE_SKEW_THRESHOLD = 0.60  # Can 60% simulation co loi nhuan duong

# Giai doan stress test (yyyy-mm-dd)
STRESS_PERIODS = [
    ("2022-01-01", "2022-06-30", "Crash Q1-Q2/2022"),
    ("2023-08-01", "2023-12-31", "Downtrend Q3-Q4/2023"),
]


@dataclass
class MonteCarloResult:
    """Ket qua Monte Carlo Simulation."""
    n_simulations: int
    mean_return_pct: float
    std_return_pct: float
    positive_skew_pct: float        # Ty le simulation co tong loi nhuan > 0
    max_drawdown_95th_pct: float    # Max DD percentile 95 (worst case 5%)
    verdict: str                    # VALID hoac RANDOM
    stress_test_results: List[dict] = field(default_factory=list)


class MonteCarloSimulator:
    """
    Kiem tra tinh ben vung (Robustness) cua mot chien luoc bang Monte Carlo.
    
    Phuong phap: Xao tron ngau nhien thu tu cac lenh giao dich 10,000 lan.
    Neu phan phoi loi nhuan co duoi duong (positive skew) > 60% -> Chien luoc co loi the that.
    Neu khong -> Chien luoc chi la may man (Random Walk).
    """

    def run(self, trade_pnl_pcts: List[float]) -> MonteCarloResult:
        """
        Input: Danh sach % loi nhuan cua cac lenh giao dich (tu BacktestResult.trade_records)
        Output: MonteCarloResult
        """
        if len(trade_pnl_pcts) < 5:
            return MonteCarloResult(
                n_simulations=0,
                mean_return_pct=0.0,
                std_return_pct=0.0,
                positive_skew_pct=0.0,
                max_drawdown_95th_pct=0.0,
                verdict="INSUFFICIENT_DATA"
            )

        arr = np.array(trade_pnl_pcts, dtype=float)
        sim_total_returns = []
        sim_max_drawdowns = []

        rng = np.random.default_rng(seed=42)

        for _ in range(N_SIMULATIONS):
            shuffled = rng.permutation(arr)
            # Tinh tong loi nhuan kep (compound)
            equity = 100.0
            peak = 100.0
            max_dd = 0.0
            for r in shuffled:
                equity *= (1 + r / 100)
                if equity > peak:
                    peak = equity
                dd = (equity - peak) / peak * 100
                if dd < max_dd:
                    max_dd = dd
            total_return = equity - 100.0
            sim_total_returns.append(total_return)
            sim_max_drawdowns.append(abs(max_dd))

        sim_returns_arr = np.array(sim_total_returns)
        sim_dd_arr = np.array(sim_max_drawdowns)

        positive_skew_pct = float(np.mean(sim_returns_arr > 0))
        verdict = "VALID" if positive_skew_pct >= POSITIVE_SKEW_THRESHOLD else "RANDOM"

        return MonteCarloResult(
            n_simulations=N_SIMULATIONS,
            mean_return_pct=round(float(sim_returns_arr.mean()), 2),
            std_return_pct=round(float(sim_returns_arr.std()), 2),
            positive_skew_pct=round(positive_skew_pct * 100, 1),
            max_drawdown_95th_pct=round(float(np.percentile(sim_dd_arr, 95)), 2),
            verdict=verdict
        )

    def run_stress_test(self, trade_records: list, ohlcv_df: pd.DataFrame) -> List[dict]:
        """
        Chay backtest rieng biet tren cac giai doan khung hoang lich su.
        trade_records: List[TradeRecord] tu BacktestResult.
        """
        results = []

        if ohlcv_df is None or ohlcv_df.empty or not trade_records:
            return results

        for start_str, end_str, label in STRESS_PERIODS:
            # Loc cac lenh giao dich trong giai doan nay
            stress_trades = [
                t for t in trade_records
                if t.entry_date is not None and start_str <= t.entry_date <= end_str
            ]
            if not stress_trades:
                results.append({"period": label, "trades": 0, "win_rate": None, "avg_pnl_pct": None})
                continue

            pnl_pcts = [t.pnl_pct for t in stress_trades if t.pnl_pct is not None]
            win_rate = round(len([p for p in pnl_pcts if p > 0]) / len(pnl_pcts) * 100, 1) if pnl_pcts else 0.0
            avg_pnl = round(float(np.mean(pnl_pcts)), 2) if pnl_pcts else 0.0

            results.append({
                "period": label,
                "trades": len(stress_trades),
                "win_rate": win_rate,
                "avg_pnl_pct": avg_pnl
            })

        return results


monte_carlo = MonteCarloSimulator()
