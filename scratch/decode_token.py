import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tcbs.auth import auth_provider

print("Token:", repr(auth_provider._token[:50] + "..."))
print("Parsed Custody Code:", repr(auth_provider.get_custody_code()))
