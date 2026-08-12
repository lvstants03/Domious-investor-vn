from abc import ABC, abstractmethod
from typing import Tuple, Dict, Any, Optional
import pandas as pd

class BaseStrategy(ABC):
    def __init__(self, name: str, params: Optional[Dict[str, Any]] = None):
        self.name = name
        self.params = params or {}

    @abstractmethod
    def analyze(self, df: pd.DataFrame) -> Tuple[str, float, str, Dict[str, Any]]:
        """
        Phan tich du lieu lich su va tra ve tin hieu giao dich.
        
        Args:
            df: DataFrame chua thong tin ohlcv (index la Datetime index, 
                cac cot: 'open', 'high', 'low', 'close', 'volume')
                
        Returns:
            Tuple gom:
            - signal: 'BUY', 'SELL', hoac 'HOLD'
            - confidence: do tin cay (0.0 den 1.0)
            - reason: ly do kich hoat tin hieu
            - indicator_values: dict luu gia tri cac chi bao ky thuat tinh duoc
        """
        pass

    @abstractmethod
    def get_config_schema(self) -> Dict[str, Any]:
        """Tra ve JSON schema cho cac tham so cua chien luoc"""
        pass
