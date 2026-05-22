import os
import requests
import time
import json
import threading
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

# ═══════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════

STORE = "https://www.rev.co.th"
TZ = timezone(timedelta(hours=7))

# ⚠️ UPDATE THIS TO THE REAL DROP DATE
DROP_TIME = datetime(2026, 5, 22, 10, 0, 0, tzinfo=TZ)

REQUIRED_KEYWORDS = ["endorphin", "minted"]
PREFERRED_SIZE = "US 10"

# Telegram
TG_TOKEN   = os.environ.get("TG_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")

# Profile for prefilled checkout
PROFILE = {
    "email":      os.environ.get("EMAIL", ""),
    "first_name": os.environ.get("FIRST_NAME", ""),
    "last_name":  os.environ.get("LAST_NAME", ""),
    "address1":   os.environ.get("ADDRESS1", ""),
    "address2":   os.environ.get("ADDRESS2", ""),
    "city":       os.environ.get("CITY", ""),
    "province":   os.environ.get("PROVINCE", ""),
    "zip":        os.environ.get("ZIP", ""),
    "country":    os.environ.get("COUNTRY", "TH"),
    "phone":      os.environ.get("PHONE", ""),
}

COUNTDOWN_INTERVAL = 600  # auto countdown every 10 minutes


# ═══════════════════════════════════════════════════════════
#  TIME
# ═══════════════════════════════════════════════════════════

def now_gmt7():
    return datetime.now(TZ)


# ═══════════════════════════════════════════════════════════
#  TELEGRAM
# ═══════════════════════════════════════════════════════════

def tg_send(text, parse_mode="HTML"):
    """Send a Telegram message."""
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data={
                "chat_id": TG_CHAT_ID,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": False,
            },
            timeout=5,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"  [!] TG send error: {e}")
        return False


def tg_alert_checkout(product_title, checkout_url, variant_info):
    """Rich alert when product is carted."""
    tg_send(
        f"🎯 <b>TARGET FOUND & IN CART!</b>\n\n"
        f"📦 <b>{product_title}</b>\n"
        f"👟 {variant_info}\n\n"
        f"👉 <a href=\"{checkout_url}\">OPEN CHECKOUT NOW</a>\n\n"
        f"⚡ Address is prefilled — just select payment!"
    )


def tg_alert_error(message):
    tg_send(f"🚨 <b>ERROR:</b> {message}")


def send_countdown():
    """Send countdown to Telegram."""
    sec_left = (DROP_TIME - now_gmt7()).total_seconds()

    if sec_left > 86400:
        days = int(sec_left // 86400)
        hours = int((sec_left % 86400) // 3600)
        time_str = f"{days}d {hours}h"
    elif sec_left > 3600:
        hours = int(sec_left // 3600)
        mins = int((sec_left % 3600) // 60)
        time_str = f"{hours}h {mins}m"
    elif sec_left > 0:
        mins = int(sec_left // 60)
        secs = int(sec_left % 60)
        time_str = f"{mins}m {secs}s"
    else:
        time_str = "⏰ PAST DROP TIME!"

    tg_send(
        f"⏰ Countdown: <b>{time_str}</b>\n"
        f"🕐 Server time: {now_gmt7().strftime('%Y-%m-%d %H:%M:%S')} GMT+7\n"
        f"🎯 Target: {' + '.join(REQUIRED_KEYWORDS).upper()}"
    )


# ═══════════════════════════════════════════════════════════
#  SESSION
# ═══════════════════════════════════════════════════════════

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9,th;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.rev.co.th/",
    "Origin": "https://www.rev.co.th",
})

etag = None
last_modified = None


# ═══════════════════════════════════════════════════════════
#  SCHEDULE
# ═══════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════
#  FETCH — CONDITIONAL GET
# ═══════════════════════════════════════════════════════════

def fetch_products():
    """Fetch page 1 (newest 10 products) with conditional GET.
    Returns (status_string, data).
    status: "ok", "not_modified", "bad_json", "http_error", "error"
    """
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
            preview = resp.text[:200]
            print(f"  [!] Not JSON! Response: {preview}")
            return "bad_json", preview

    return "http_error", resp.status_code


def fetch_all_products(pages=3):
    """Fetch multiple pages. Used by /test command."""
    all_products = []
    for page in range(1, pages + 1):
        url = f"{STORE}/products.json?limit=250&page={page}"
        try:
            resp = session.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                products = data.get("products", [])
                all_products.extend(products)
                print(f"    Page {page}: {len(products)} products")
            else:
                print(f"    Page {page}: status {resp.status_code}")
        except Exception as e:
            print(f"    Page {page}: error {e}")
        time.sleep(0.3)
    return all_products


# ═══════════════════════════════════════════════════════════
#  MATCHING
# ═══════════════════════════════════════════════════════════

def is_target(product):
    """Both 'endorphin' AND 'minted' must appear."""
    text = " ".join([
        product.get("title", ""),
        product.get("handle", ""),
        product.get("product_type", ""),
        " ".join(product.get("tags", [])),
    ]).lower()
    return all(kw in text for kw in REQUIRED_KEYWORDS)


# ═══════════════════════════════════════════════════════════
#  ATC + CHECKOUT
# ═══════════════════════════════════════════════════════════

def pick_variant(product):
    """Pick preferred size, fallback to first available, then first."""
    variants = product.get("variants", [])

    for v in variants:
        if PREFERRED_SIZE.lower() in v["title"].lower() and v["available"]:
            return v

    for v in variants:
        if v["available"]:
            return v

    return variants[0] if variants else None


def add_to_cart(variant_id):
    """POST to /cart/add.js with retries."""
    url = f"{STORE}/cart/add.js"
    data = {"form_type": "product", "id": str(variant_id), "quantity": "1"}

    for attempt in range(3):
        try:
            resp = session.post(url, data=data, timeout=5)
            if resp.status_code == 200:
                return True
            print(f"    ATC #{attempt+1}: status {resp.status_code}")
        except Exception as e:
            print(f"    ATC #{attempt+1}: {e}")
        time.sleep(0.2)

    return False


def build_checkout_url():
    """Build prefilled checkout URL."""
    params = {
        "checkout[email]":                            PROFILE["email"],
        "checkout[shipping_address][first_name]":     PROFILE["first_name"],
        "checkout[shipping_address][last_name]":      PROFILE["last_name"],
        "checkout[shipping_address][address1]":       PROFILE["address1"],
        "checkout[shipping_address][address2]":       PROFILE["address2"],
        "checkout[shipping_address][city]":           PROFILE["city"],
        "checkout[shipping_address][province]":       PROFILE["province"],
        "checkout[shipping_address][zip]":            PROFILE["zip"],
        "checkout[shipping_address][country]":        PROFILE["country"],
        "checkout[shipping_address][phone]":          PROFILE["phone"],
    }
    return f"{STORE}/checkout?{urlencode(params)}"


# ═══════════════════════════════════════════════════════════
#  /TEST COMMAND — SEARCH 3 PAGES FOR ENDORPHIN
# ═══════════════════════════════════════════════════════════

def handle_test_command():
    """Search 3 pages of products.json for endorphin."""
    tg_send("🔍 Testing: searching 3 pages for endorphin...")

    all_products = fetch_all_products(pages=3)

    if not all_products:
        tg_send(
            f"❌ Got 0 products from 3 pages!\n"
            f"Site might be blocking us or endpoint changed."
        )
        return

    matches = []
    for p in all_products:
        text = " ".join([
            p.get("title", ""),
            p.get("handle", ""),
            " ".join(p.get("tags", [])),
        ]).lower()

        if "endorphin" in text:
            variants = p.get("variants", [])
            variant_lines = []
            for v in variants:
                avail_icon = "✅" if v["available"] else "❌"
                variant_lines.append(
                    f"    {v['id']} | {v['title']} | "
                    f"฿{v['price']} | {avail_icon}"
                )

            matches.append({
                "title": p["title"],
                "handle": p["handle"],
                "published": p.get("published_at", "NOT SET"),
                "status": p.get("status", "unknown"),
                "variants": "\n".join(variant_lines),
            })

    if matches:
        lines = [f"🎯 Found {len(matches)} endorphin product(s) "
                 f"in {len(all_products)} total:\n"]
        for m in matches:
            lines.append(f"📦 <b>{m['title']}</b>")
            lines.append(f"   Handle: {m['handle']}")
            lines.append(f"   Status: {m['status']}")
            lines.append(f"   Published: {m['published']}")
            lines.append(f"   URL: {STORE}/products/{m['handle']}")
            lines.append(f"   Variants:")
            lines.append(f"{m['variants']}")
            lines.append("")

        # Check if our specific target is among them
        minted_found = any(
            "minted" in m["title"].lower() or "minted" in m["handle"].lower()
            for m in matches
        )
        if minted_found:
            lines.append("🏆 MINTED/CHROME MODEL IS LISTED!")
        else:
            lines.append("❌ No minted/chrome model yet — "
                        "not published!")

        report = "\n".join(lines)
    else:
        report = (
            f"❌ No endorphin found in {len(all_products)} products.\n"
            f"Target not published yet!"
        )

    # Telegram 4096 char limit — split if needed
    if len(report) > 4000:
        chunks = [report[i:i+4000] for i in range(0, len(report), 4000)]
        for chunk in chunks:
            tg_send(chunk)
    else:
        tg_send(report)

    print("  [CMD] /test complete")


# ═══════════════════════════════════════════════════════════
#  TELEGRAM COMMAND LISTENER
# ═══════════════════════════════════════════════════════════

def telegram_listener():
    """Listen for Telegram commands in background thread."""
    last_update_id = 0

    while True:
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
                params={
                    "offset": last_update_id + 1,
                    "timeout": 30,
                    "allowed_updates": ["message"],
                },
                timeout=35,
            )

            if resp.status_code != 200:
                time.sleep(5)
                continue

            data = resp.json()
            if not data.get("ok"):
                time.sleep(5)
                continue

            for update in data.get("result", []):
                last_update_id = update["update_id"]

                message = update.get("message", {})
                text = message.get("text", "").strip().lower()
                chat_id = str(message.get("chat", {}).get("id", ""))

                # Only accept from YOUR chat
                if chat_id != TG_CHAT_ID:
                    continue

                if text == "/test":
                    print("  [CMD] /test received")
                    handle_test_command()

                elif text in ("/countdown", "/time"):
                    print("  [CMD] /countdown received")
                    send_countdown()

                elif text == "/start":
                    tg_send(
                        "🤖 Bot is running!\n\n"
                        "Commands:\n"
                        "/test — search for endorphin\n"
                        "/countdown — time until drop"
                    )

        except Exception as e:
            print(f"  [!] Listener error: {e}")
            time.sleep(5)


# ═══════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════

def main():
    print("═" * 58)
    print("  REV.CO.TH DROP MONITOR")
    print(f"  Target:  {' + '.join(REQUIRED_KEYWORDS).upper()}")
    print(f"  Size:    {PREFERRED_SIZE}")
    print(f"  Drop:    {DROP_TIME.strftime('%Y-%m-%d %H:%M:%S')} GMT+7")
    print("═" * 58)

    # ── Startup message ──
    tg_send(
        "🤖 <b>Bot started!</b>\n\n"
        f"🎯 Target: {' + '.join(REQUIRED_KEYWORDS).upper()}\n"
        f"👟 Size: {PREFERRED_SIZE}\n"
        f"📅 Drop: {DROP_TIME.strftime('%Y-%m-%d %H:%M')} GMT+7\n\n"
        f"Commands:\n"
        f"/test — search for endorphin\n"
        f"/countdown — time until drop"
    )

    sec_until = (DROP_TIME - now_gmt7()).total_seconds()
    print(f"  Now:     {now_gmt7().strftime('%Y-%m-%d %H:%M:%S')} GMT+7")
    print(f"  Until:   {sec_until:.0f}s ({sec_until/60:.1f} min)\n")

    # ── Start Telegram listener ──
    listener_thread = threading.Thread(
        target=telegram_listener, daemon=True
    )
    listener_thread.start()
    print("[✓] Telegram listener started (send /test or /countdown)\n")

    # ── Test the endpoint ──
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
        print(f"  [✓] 304 cached (normal)")
    elif status == "bad_json":
        known_handles = set()
        print(f"  [✗] Site returned non-JSON!")
        print(f"  [!] Response: {data[:200]}")
        tg_send(f"⚠️ Site not returning JSON!\n{data[:200]}")
    else:
        known_handles = set()
        print(f"  [✗] Error: {status} — {data}")
        tg_send(f"⚠️ Connection error: {status}")
    print()

    # ── First countdown ──
    send_countdown()
    last_countdown_time = time.time()

    # ── Polling loop ──
    check_count = 0

    while True:
        try:
            action, interval, mode = get_schedule()

            # ── Sleep if too early ──
            if action is None:
                left = (DROP_TIME - now_gmt7()).total_seconds() / 60
                print(f"  💤 {left:.0f} min to go. "
                      f"Sleeping {interval}s...")
                time.sleep(interval)
                continue

            # ── Auto countdown every 10 min ──
            if time.time() - last_countdown_time > COUNTDOWN_INTERVAL:
                send_countdown()
                last_countdown_time = time.time()

            check_count += 1
            now_str = now_gmt7().strftime("%H:%M:%S")
            sec_left = (DROP_TIME - now_gmt7()).total_seconds()

            status, data = fetch_products()

            # ── 304: nothing changed ──
            if status == "not_modified":
                print(f"  [{now_str}] #{check_count:>4}  304  "
                      f"({mode})  [{sec_left:+.0f}s]")

            # ── 200: check for new products ──
            elif status == "ok":
                products = data.get("products", [])
                current_handles = {p["handle"] for p in products}
                new_handles = current_handles - known_handles

                if new_handles:
                    print(f"\n  🔄 NEW PRODUCTS: {new_handles}")

                    for p in products:
                        if p["handle"] not in new_handles:
                            continue

                        if is_target(p):
                            variant = pick_variant(p)
                            info = (f"{variant['title']} — "
                                    f"฿{variant['price']}")

                            print(f"\n  {'='*55}")
                            print(f"  🎯🎯🎯 TARGET FOUND!")
                            print(f"  Title:    {p['title']}")
                            print(f"  Handle:   {p['handle']}")
                            print(f"  Variant:  {variant['id']} "
                                  f"| {variant['title']}")
                            print(f"  Price:    ฿{variant['price']}")
                            print(f"  Available:{variant['available']}")
                            print(f"  URL:      "
                                  f"{STORE}/products/{p['handle']}")
                            print(f"  {'='*55}")

                            # ── Add to cart ──
                            print(f"\n  → Adding {variant['title']} "
                                  f"to cart...")
                            if add_to_cart(variant["id"]):
                                checkout_url = build_checkout_url()
                                print(f"  ✅ IN CART!")
                                print(f"  → Sending Telegram alert...")

                                tg_alert_checkout(
                                    product_title=p["title"],
                                    checkout_url=checkout_url,
                                    variant_info=info,
                                )

                                print(f"  ✅ Telegram sent!")
                                print(f"  ✅ Check your phone NOW!\n")
                                return  # Done
                            else:
                                print(f"  ❌ ATC FAILED after 3 tries")
                                tg_alert_error(
                                    f"Found {p['title']} but "
                                    f"ATC failed! Try manually:\n"
                                    f"{STORE}/products/{p['handle']}"
                                )
                                return

                        else:
                            print(f"    (new but not target: "
                                  f"{p['title']})")

                    # Update known set
                    known_handles = current_handles

                else:
                    print(f"  [{now_str}] #{check_count:>4}  200  "
                          f"({mode})  [{sec_left:+.0f}s]")
                    known_handles = current_handles

            # ── Bad JSON ──
            elif status == "bad_json":
                print(f"  [{now_str}] #{check_count:>4}  "
                      f"BAD JSON  ({mode})  [{sec_left:+.0f}s]")

            # ── HTTP error ──
            elif status == "http_error":
                print(f"  [{now_str}] #{check_count:>4}  "
                      f"HTTP {data}  ({mode})  [{sec_left:+.0f}s]")

            # ── Connection error ──
            else:
                print(f"  [{now_str}] #{check_count:>4}  "
                      f"ERR  ({mode})  [{sec_left:+.0f}s]")

            time.sleep(interval)

        except Exception as e:
            print(f"  [!] Loop error: {e}")
            time.sleep(5)


# ═══════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    main()
