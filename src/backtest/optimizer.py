import logging
from typing import List, Dict, Tuple, Optional
import pandas as pd
import numpy as np
import optuna

from src.backtest.engine import backtest_engine

logger = logging.getLogger("dominus-investor.backtest.optimizer")
optuna.logging.set_verbosity(optuna.logging.WARNING)

class WyckoffOptimizer:
    """
    Toi uu hoa tham so cho chien luoc Wyckoff Spring su dung Optuna va Walk-Forward.
    """

    def __init__(self):
        self.engine = backtest_engine

    def _wyckoff_strategy_fn(self, ohlcv_df: pd.DataFrame, params: dict) -> pd.Series:
        """Chien luoc Wyckoff: tin hieu Spring = BUY signal"""
        signals = pd.Series([False] * len(ohlcv_df))
        
        # Import dynamic de tranh circular import
        from src.wyckoff.base_detector import BaseDetector
        from src.wyckoff.spring_detector import SpringDetector
        
        base_det = BaseDetector()
        spring_det = SpringDetector()
        
        # Override cac tham so tinh trong detector bang tham so toi uu
        base_det.MIN_BASE_DAYS = params.get("L_base", 20)
        base_det.BASE_TIGHTNESS_RATIO = params.get("B_width", 0.6)
        spring_det.SPRING_VOLUME_MULTIPLIER = params.get("v_break", 1.5)
        spring_det.SPRING_LOOKAHEAD_DAYS = params.get("lookahead", 30)
        
        base = base_det.detect_base(ohlcv_df, lookback=60)
        if base is None:
            return signals
            
        spring = spring_det.detect_spring(ohlcv_df, base)
        if spring is None:
            return signals
            
        spring_idx = ohlcv_df.index[ohlcv_df["trade_date"] == spring.date].tolist()
        if spring_idx:
            signals.iloc[spring_idx[0]] = True
            
        return signals

    def run_optimization(self, symbol: str, ohlcv_df: pd.DataFrame, n_trials: int = 100) -> Tuple[dict, float]:
        """
        Chay toi uu hoa bang Optuna tim bo tham so tot nhat cho 1 co phieu.
        """
        if ohlcv_df is None or len(ohlcv_df) < 100:
            return {}, 0.0

        def objective(trial):
            # Khong gian tim kiem tham so (Search Space)
            params = {
                "L_base": trial.suggest_int("L_base", 20, 60, step=5),
                "B_width": trial.suggest_float("B_width", 0.4, 0.9, step=0.05),
                "v_break": trial.suggest_float("v_break", 1.2, 2.5, step=0.1),
                "lookahead": trial.suggest_int("lookahead", 15, 45, step=5),
                "stop_loss_pct": trial.suggest_float("stop_loss_pct", 0.04, 0.10, step=0.01),
                "take_profit_pct": trial.suggest_float("take_profit_pct", 0.10, 0.25, step=0.01)
            }

            result = self.engine.run(
                symbol=symbol,
                ohlcv_df=ohlcv_df,
                strategy_fn=self._wyckoff_strategy_fn,
                params=params,
                stop_loss_pct=params["stop_loss_pct"],
                take_profit_pct=params["take_profit_pct"]
            )

            if result.total_trades < 5:
                return -100.0  # Phat neu co qua it giao dich de tranh overfitting

            # Tinh Q_score
            q_score = (result.win_rate * 0.4) + (result.total_return_pct * 0.4) - (abs(result.max_drawdown_pct) * 0.2)
            return q_score

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=n_trials)
        
        return study.best_params, study.best_value

    def walk_forward_analysis(self, symbol: str, ohlcv_df: pd.DataFrame, folds: int = 3) -> List[dict]:
        """
        Thuc hien Walk-Forward Analysis (WFA) chia lam N ky.
        Moi ky gom In-Sample (70%) va Out-of-Sample (30%).
        """
        if ohlcv_df is None or len(ohlcv_df) < 200:
            return []

        df = ohlcv_df.sort_values("trade_date").reset_index(drop=True)
        total_len = len(df)
        fold_size = total_len // (folds + 1)
        
        results = []

        for f in range(folds):
            # Chia tap In-Sample (Train) va Out-of-Sample (Test)
            train_start = f * fold_size
            train_end = train_start + int(fold_size * 2.5) # ~70%
            test_start = train_end
            test_end = min(test_start + int(fold_size * 1.0), total_len) # ~30%

            train_df = df.iloc[train_start:train_end].copy().reset_index(drop=True)
            test_df = df.iloc[test_start:test_end].copy().reset_index(drop=True)

            logger.info("WFA Fold %d: Train (%s - %s), Test (%s - %s)", 
                        f + 1, train_df.iloc[0]["trade_date"], train_df.iloc[-1]["trade_date"],
                        test_df.iloc[0]["trade_date"], test_df.iloc[-1]["trade_date"])

            # 1. Train: Toi uu hoa tren In-Sample
            best_params, train_score = self.run_optimization(symbol, train_df, n_trials=50)

            if not best_params:
                continue

            # 2. Test: Chay thu nghiem tren Out-of-Sample bang bo tham so train duoc
            test_result = self.engine.run(
                symbol=symbol,
                ohlcv_df=test_df,
                strategy_fn=self._wyckoff_strategy_fn,
                params=best_params,
                stop_loss_pct=best_params["stop_loss_pct"],
                take_profit_pct=best_params["take_profit_pct"]
            )

            # Tinh Q_score cho test
            test_score = (test_result.win_rate * 0.4) + (test_result.total_return_pct * 0.4) - (abs(test_result.max_drawdown_pct) * 0.2)
            
            # Kiem tra do sut giam hieu suat
            stability = "STABLE" if test_score >= train_score * 0.85 else "DEGRADED"

            results.append({
                "fold": f + 1,
                "train_period": f"{train_df.iloc[0]['trade_date']} - {train_df.iloc[-1]['trade_date']}",
                "test_period": f"{test_df.iloc[0]['trade_date']} - {test_df.iloc[-1]['trade_date']}",
                "best_params": best_params,
                "train_score": round(train_score, 2),
                "test_score": round(test_score, 2),
                "test_return_pct": test_result.total_return_pct,
                "test_win_rate": test_result.win_rate,
                "stability": stability
            })

        return results

optimizer = WyckoffOptimizer()
