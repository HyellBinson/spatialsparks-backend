
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

print("Supabase URL configured:", bool(SUPABASE_URL))
print("Service key configured:", bool(SERVICE_KEY))

if not SUPABASE_URL or not SERVICE_KEY:
    raise SystemExit("Missing Supabase configuration.")

try:
    response = httpx.get(
        f"{SUPABASE_URL}/storage/v1/bucket",
        headers={
            "apikey": SERVICE_KEY,
            "Authorization": f"Bearer {SERVICE_KEY}",
        },
        timeout=20,
    )

    print("HTTP status:", response.status_code)
    print("Response:", response.text[:2000])

except httpx.RequestError as error:
    print("Connection error:", repr(error))
