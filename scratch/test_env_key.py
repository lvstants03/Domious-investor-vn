import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import settings

print(f"API Key from settings: {repr(settings.TCBS_API_KEY)}")
print(f"Length of API Key: {len(settings.TCBS_API_KEY)}")
# Kiem tra xem co chua ky tu xuong dong hoac khoang trang khong
print(f"Has whitespace: {any(c.isspace() for c in settings.TCBS_API_KEY)}")
