import os
import requests
import time
import json
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

# ═══════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════

STORE = "https://www.rev.co.th"
TZ = timezone(timedelta(hours=7))

# ⚠️ UPDATE THIS TO THE REAL DATE
DROP_TIME = datetime(2026, 5, 22, 10, 0, 0, tzinfo=TZ)

REQUIRED_KEYWORDS = ["endorphin", "minted"]
PREFERRED_SIZE = "US 10"

TG_TOKEN   = os.environ.get("TG_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")

PROFILE = {
    "email":       os.environ.get("EMAIL", ""),
    "first_name":  os.environ.get("FIRST_NAME", ""),
    "last_name":   os.environ.get("LAST_NAME", ""),
    "address1":    os.environ.get("ADDRESS1", ""),
    "address2":    os.environ.get("ADDRESS2", ""),
    "city":        os.environ.get("CITY", ""),
    "province":    os.environ.get("PROVINCE", ""),
    "zip":         os.environ.get("ZIP", ""),
    "country":     os.environ.get("COUNTRY", "TH"),
    "phone":       os.environ.get("PHONE", ""),
}


# ═══════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════

def now_gmt7():
    return datetime.now(TZ)


def tg_send(text):
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=5,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[!] TG error: {e}")
        return False


def tg_alert_checkout(product_title, checkout_url, variant_info):
    tg_send(
        f"🎯 <b>IN CART!</b>\n\n"
        f"📦 {product_title}\n"
        f"👟 {variant_info}\n\n"
        f"👉 <a href=\"{checkout_url}\">OPEN CHECKOUT</a>\n\n"
        f"⚡ Address prefilled — just pay!"
    )


# ═══════════════════════════════════════════
#  SESSION
# ═══════════════════════════════════════════

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
})

etag = None
last_modified = None


# ═══════════════════════════════════════════
#  SCHEDULE
# ═══════════════════════════════════════════

def get_schedule():
    seconds_left = (DROP_TIME - now_gmt7()).total_seconds()

    if seconds_left > 3600:
        return None,    60.0, "sleeping"
    elif seconds_left > 300:
        return "start", 30.0, "chill"
    elif seconds_left > 120:
        return "start", 5.0,  "warming up"
    elif seconds_left > 30:
        return "start", 2.0,  "ready"
    elif seconds_left > 0:
        return "start", 0.8,  "locked in"
    elif seconds_left > -300:
        return "start", 0.5,  "drop window"
    else:
        return "start", 0.8,  "restock watch"


# ═══════════════════════════════════════════
#  FETCH (with proper error handling)
# ═══════════════════════════════════════════

def fetch_products():
    """Fetch products with conditional GET. Returns (status, data)."""
    global etag, last_modified

    url = f"{STORE}/products.json?limit=10&page=1"
    headers = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    try:
        resp = session.get(url, headers=headers, timeout=10)
    except Exception as e:
        return "error", str(e)

    if "ETag" in resp.headers:
        etag = resp.headers["ETag"]
    if "Last-Modified" in resp.headers:
        last_modified = resp.headers["Last-Modified"]

    if resp.status_code == 304:
        return "not_modified", None

    if resp.status_code == 200:
        try:
            data = resp.json()
            return "ok", data
        except Exception:
            # Not JSON — print what we actually got
            preview = resp.text[:200]
            print(f"  [!] Not JSON! Response: {preview}")
            return "bad_json", preview

    return "http_error", resp.status_code


def is_target(product):
    text = " ".join([
        product.get("title", ""),
        product.get("handle", ""),
        product.get("product_type", ""),
        " ".join(product.get("tags", [])),
    ]).lower()
    return all(kw in text for kw in REQUIRED_KEYWORDS)


# ═══════════════════════════════════════════
#  ATC + CHECKOUT
# ═══════════════════════════════════════════

def pick_variant(product):
    variants = product.get("variants", [])
    for v in variants:
        if PREFERRED_SIZE.lower() in v["title"].lower() and v["available"]:
            return v
    for v in variants:
        if v["available"]:
            return v
    return variants[0] if variants else None


def add_to_cart(variant_id):
    url = f"{STORE}/cart/add.js"
    data = {"form_type": "product", "id": str(variant_id), "quantity": "1"}
    for attempt in range(3):
        try:
            resp = session.post(url, data=data, timeout=5)
            if resp.status_code == 200:
                return True
            print(f"    ATC #{attempt+1}: {resp.status_code}")
        except Exception as e:
            print(f"    ATC #{attempt+1}: {e}")
        time.sleep(0.2)
    return False


def build_checkout_url():
    params = {
        "checkout[email]":                        PROFILE["email"],
        "checkout[shipping_address][first_name]": PROFILE["first_name"],
        "checkout[shipping_address][last_name]":  PROFILE["last_name"],
        "checkout[shipping_address][address1]":   PROFILE["address1"],
        "checkout[shipping_address][address2]":   PROFILE["address2"],
        "checkout[shipping_address][city]":       PROFILE["city"],
        "checkout[shipping_address][province]":   PROFILE["province"],
        "checkout[shipping_address][zip]":        PROFILE["zip"],
        "checkout[shipping_address][country]":    PROFILE["country"],
        "checkout[shipping_address][phone]":      PROFILE["phone"],
    }
    return f"{STORE}/checkout?{urlencode(params)}"


# ═══════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════

def main():
    print("═" * 58)
    print("  REV.CO.TH DROP MONITOR")
    print(f"  Target:  {' + '.join(REQUIRED_KEYWORDS).upper()}")
    print(f"  Size:    {PREFERRED_SIZE}")
    print(f"  Drop:    {DROP_TIME.strftime('%Y-%m-%d %H:%M:%S')} GMT+7")
    print("═" * 58)

    tg_send("🤖 Bot started!")

    sec_until = (DROP_TIME - now_gmt7()).total_seconds()
    print(f"  Now:     {now_gmt7().strftime('%Y-%m-%d %H:%M:%S')} GMT+7")
    print(f"  Until:   {sec_until:.0f}s ({sec_until/60:.1f} min)\n")

    # ── Diagnostic: test the URL right now ──
    print("[*] Testing products.json endpoint...")
    status, data = fetch_products()

    if status == "ok":
        products = data.get("products", [])
        known_handles = {p["handle"] for p in products}
        print(f"  [✓] Got {len(products)} products:")
        for h in sorted(known_handles):
            print(f"      • {h}")
    elif status == "not_modified":
        known_handles = set()
        print(f"  [✓] 304 (cached, normal)")
    elif status == "bad_json":
        print(f"  [✗] Site returned HTML, not JSON!")
        print(f"  [!] This might mean:")
        print(f"      - Site has a password page")
        print(f"      - /products.json is blocked")
        print(f"      - Site is not Shopify")
        print(f"  [!] Response: {data[:200]}")
        tg_send(f"⚠️ Site not returning JSON! Response:\n{data[:200]}")
        known_handles = set()
    else:
        print(f"  [✗] Error: {status} — {data}")
        tg_send(f"⚠️ Connection error: {status}")
        known_handles = set()

    print()

    # ── Polling loop ──
    check_count = 0

    while True:
        try:
            action, interval, mode = get_schedule()

            if action is None:
                left = (DROP_TIME - now_gmt7()).total_seconds() / 60
                print(f"  💤 {left:.0f} min to go. Sleeping {interval}s...")
                time.sleep(interval)
                continue

            check_count += 1
            now_str = now_gmt7().strftime("%H:%M:%S")
            sec_left = (DROP_TIME - now_gmt7()).total_seconds()

            status, data = fetch_products()

            if status == "not_modified":
                print(f"  [{now_str}] #{check_count:>4}  304  "
                      f"({mode})  [{sec_left:+.0f}s]")

            elif status == "ok":
                products = data.get("products", [])
                current_handles = {p["handle"] for p in products}
                new_handles = current_handles - known_handles

                if new_handles:
                    print(f"\n  🔄 NEW: {new_handles}")

                    for p in products:
                        if p["handle"] not in new_handles:
                            continue

                        if is_target(p):
                            variant = pick_variant(p)
                            info = f"{variant['title']} — ฿{variant['price']}"

                            print(f"\n  {'='*55}")
                            print(f"  🎯 TARGET: {p['title']}")
                            print(f"  {info}")
                            print(f"  {'='*55}")

                            print(f"  → Adding to cart...")
                            if add_to_cart(variant["id"]):
                                checkout_url = build_checkout_url()
                                tg_alert_checkout(p["title"], checkout_url, info)
                                print(f"  ✅ Done! Check Telegram.\n")
                                return
                            else:
                                tg_send(f"🚨 Found {p['title']} — ATC FAILED!")
                                return
                        else:
                            print(f"    (not target: {p['title']})")

                    known_handles = current_handles
                else:
                    print(f"  [{now_str}] #{check_count:>4}  200  "
                          f"({mode})  [{sec_left:+.0f}s]")
                    known_handles = current_handles

            elif status == "bad_json":
                print(f"  [{now_str}] #{check_count:>4}  BAD JSON  "
                      f"({mode})  [{sec_left:+.0f}s]")

            else:
                print(f"  [{now_str}] #{check_count:>4}  {status}  "
                      f"({mode})  [{sec_left:+.0f}s]")

            time.sleep(interval)

        except Exception as e:
            print(f"  [!] Loop error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
