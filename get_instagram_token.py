"""
Script lấy Instagram Business Login token (chạy 1 lần).
Sau khi chạy, lưu INSTAGRAM_ACCESS_TOKEN vào .env
"""
import urllib.parse
import urllib.request
import json

APP_ID = "955578673538079"
APP_SECRET = "d495a4763ee29544c3273262383f0ea9"
REDIRECT_URI = "https://localhost"
SCOPES = "instagram_business_basic,instagram_business_content_publish"

# Bước 1: In auth URL
auth_url = (
    f"https://www.instagram.com/oauth/authorize"
    f"?client_id={APP_ID}"
    f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
    f"&scope={SCOPES}"
    f"&response_type=code"
)

print("=" * 60)
print("BƯỚC 1: Mở URL sau trong browser:")
print()
print(auth_url)
print()
print("Sau khi authorize, browser sẽ redirect tới https://localhost?code=xxx")
print("(Browser báo lỗi là bình thường — copy URL đó lại)")
print("=" * 60)

redirect_url = input("\nPaste redirect URL vào đây: ").strip()

# Parse code từ URL
parsed = urllib.parse.urlparse(redirect_url)
params = urllib.parse.parse_qs(parsed.query)
if "code" not in params:
    print("Không tìm thấy 'code' trong URL. Thử lại.")
    exit(1)

code = params["code"][0]
print(f"\nCode: {code[:20]}...")

# Bước 2: Exchange code → short-lived token
print("\nBước 2: Đổi code lấy short-lived token...")
data = urllib.parse.urlencode({
    "client_id": APP_ID,
    "client_secret": APP_SECRET,
    "grant_type": "authorization_code",
    "redirect_uri": REDIRECT_URI,
    "code": code,
}).encode()

req = urllib.request.Request("https://api.instagram.com/oauth/access_token", data=data)
with urllib.request.urlopen(req) as resp:
    result = json.loads(resp.read())

short_token = result["access_token"]
user_id = result["user_id"]
print(f"User ID: {user_id}")
print(f"Short-lived token: {short_token[:30]}...")

# Bước 3: Exchange short-lived → long-lived token (60 ngày)
print("\nBước 3: Đổi lấy long-lived token (60 ngày)...")
params_ll = urllib.parse.urlencode({
    "grant_type": "ig_exchange_token",
    "client_secret": APP_SECRET,
    "access_token": short_token,
})
url = f"https://graph.instagram.com/access_token?{params_ll}"

req2 = urllib.request.Request(url)
with urllib.request.urlopen(req2) as resp:
    result2 = json.loads(resp.read())

long_token = result2["access_token"]
expires_in = result2.get("expires_in", 0)
expires_days = expires_in // 86400

print("\n" + "=" * 60)
print("THÀNH CÔNG!")
print(f"Instagram User ID : {user_id}")
print(f"Long-lived token  : {long_token}")
print(f"Hết hạn sau       : {expires_days} ngày")
print()
print("Thêm vào .env:")
print(f"INSTAGRAM_USER_ID={user_id}")
print(f"INSTAGRAM_ACCESS_TOKEN={long_token}")
print("=" * 60)
