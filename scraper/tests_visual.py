"""Quick smoke tests cho visual_creator pure functions. Chạy: python scraper/tests_visual.py"""
import sys
sys.path.insert(0, "scraper")

from visual_creator import VisualCreator

vc = VisualCreator.__new__(VisualCreator)  # skip __init__

# Test 1: extract từ Draft VN có hashtags
record = {"fields": {
    "Draft VN": "Sao Thái mê bánh căn Nha Trang\n\nĐến Nha Trang là phải thử nước dừa tươi mát 🌴🍹\nBánh căn giòn rụm, chấm mắm nêm\n\n#NhaTrang #AmThuc #BanhCan",
    "Category": "Ẩm thực",
}}
title, caption, hashtags = vc._extract_text_parts(record)
assert "Sao Thái" in title, f"title wrong: {title}"
assert "nước dừa" in caption, f"caption wrong: {caption}"
assert "#NhaTrang" in hashtags, f"hashtags wrong: {hashtags}"
assert len(title) <= 60, f"title too long: {len(title)}"
print(f"✓ Test 1 passed: title={title!r}, hashtags={hashtags!r}")

# Test 2: Draft VN trống
record2 = {"fields": {"Draft VN": "", "Category": "Sự kiện"}}
result2 = vc._extract_text_parts(record2)
assert result2 == ("", "", ""), f"empty should return ('','',''): {result2}"
print("✓ Test 2 passed: empty Draft VN returns empty tuple")

# Test 3: build_image_url returns valid URL string
vc.cloud_name = "dxgq9cwkv"
url = vc._build_image_url("nhatrang/test123", "Bánh căn Nha Trang", "Thử ngay hôm nay 🍴", "#NhaTrang")
assert url.startswith("https://res.cloudinary.com/dxgq9cwkv/image/upload/"), f"bad URL: {url}"
assert "nhatrang/test123" in url, f"public_id missing: {url}"
print(f"✓ Test 3 passed: URL starts correctly")

print("\n✅ All tests passed")
