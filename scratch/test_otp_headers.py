import asyncio
import httpx
import sys

sys.stdout.reconfigure(encoding='utf-8')

async def main():
    api_key = "10000319258-34c2530a-b48b-4915-9250-2756f3613b0c"
    base_url = "https://openapi.tcbs.com.vn"
    url = f"{base_url}/gaia/v1/oauth2/openapi/token"
    
    # Truong hop 1: Gui apiKey va otp ma khong co otpId
    print("Testing Case 1: apiKey + dummy otp (no otpId)")
    body_1 = {
        "apiKey": api_key,
        "otp": "123456"
    }
    
    # Truong hop 2: Gui apiKey, dummy otp va dummy otpId
    print("Testing Case 2: apiKey + dummy otp + dummy otpId")
    body_2 = {
        "apiKey": api_key,
        "otp": "123456",
        "otpId": "mock-otp-id"
    }
    
    async with httpx.AsyncClient() as client:
        for idx, body in enumerate([body_1, body_2]):
            print(f"Case {idx + 1} Body: {body}")
            try:
                r = await client.post(url, json=body, timeout=10.0)
                print(f"Status: {r.status_code}")
                print(f"Response: {r.text}")
            except Exception as e:
                print(f"Error: {e}")
            print("-" * 50)

if __name__ == "__main__":
    asyncio.run(main())
