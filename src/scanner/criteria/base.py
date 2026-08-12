from abc import ABC, abstractmethod
from typing import Dict, Any

class BaseCriterion(ABC):
    def __init__(self, name: str, weight: float):
        self.name = name
        self.weight = weight  # Ti le phan tram (vi du: 0.3 cho Volume/Flow)

    @abstractmethod
    def evaluate(self, symbol: str, data: Dict[str, Any]) -> float:
        """
        Danh gia co phieu va tra ve so diem tu 0.0 den 100.0.
        """
        pass
