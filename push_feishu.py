#!/usr/bin/env python3
"""
push_feishu.py — Feishu group bot push module

Handles all Feishu webhook interactions:
  - HMAC-SHA256 request signing
  - Interactive card construction (brief text + optional poster image)
  - HTML poster → PNG screenshot via Playwright headless Chromium
  - Image upload to Feishu CDN (requires App Secret)
  - Final card delivery to group webhook

Entry point (called by run_workflow.py):
  feishu_push(brief, ticker, poster_html=None)

Standalone connectivity test:
  python3 push_feishu.py --test
"""

import os, re, base64, hmac, hashlib, time, tempfile, random
from datetime import datetime
from pathlib import Path

try:
    import httpx as _httpx
except ImportError:
    _httpx = None

# ── Config (override via environment variables) ──────────────────────
FEISHU_WEBHOOK    = os.getenv("FEISHU_WEBHOOK", "")
FEISHU_APP_ID     = os.getenv("FEISHU_APP_ID",  "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
FEISHU_SIGN_KEY   = os.getenv("FEISHU_SIGN_KEY", "")


# ── Request signing ──────────────────────────────────────────────────

def _signed(body: dict) -> dict:
    """Add HMAC-SHA256 timestamp + signature to a webhook payload."""
    ts  = str(int(time.time()))
    msg = f"{ts}\n{FEISHU_SIGN_KEY}".encode("utf-8")
    sig = base64.b64encode(hmac.new(msg, digestmod=hashlib.sha256).digest()).decode()
    return {**body, "timestamp": ts, "sign": sig}


# ── Card builder ─────────────────────────────────────────────────────

def build_card(brief: str, ticker: str, image_keys: list = None) -> dict:
    """Build a Feishu interactive card from a brief string.

    Card header title  = line 0 of the brief
                         (format: 'Company (TICKER)  (Bank Rating, PT)')
    Card accent color  = green if 📈/🚀 found anywhere, red if 📉, else blue
    Body               = full brief with $...$ wrappers replaced by **bold**
                         (Feishu interprets $ as math otherwise)
    image_keys         = list of uploaded image keys to embed (EN + ZH posters)
    """
    lines = brief.strip().split("\n")
    title = lines[0].strip() if lines else ticker

    color = ("green" if any(e in brief for e in ("📈", "🚀"))
             else "red" if "📉" in brief
             else "blue")

    body = re.sub(r"\$([^$\n]+)\$", lambda m: f"**{m.group(1)}**", brief.strip())

    elements = [{"tag": "div", "text": {"tag": "lark_md", "content": body}}]
    for key in (image_keys or []):
        elements += [
            {"tag": "hr"},
            {"tag": "img",
             "img_key": key,
             "alt": {"tag": "plain_text", "content": f"{ticker} Earnings Poster"},
             "mode": "fit_horizontal",
             "preview": True},
        ]
    elements += [
        {"tag": "hr"},
        {"tag": "note", "elements": [
            {"tag": "plain_text",
             "content": f"Investing Community · {datetime.today().strftime('%Y-%m-%d')}"}
        ]},
    ]
    return {
        "config":   {"wide_screen_mode": True},
        "header":   {"title": {"tag": "plain_text", "content": title},
                     "template": color},
        "elements": elements,
    }


# ── Poster image helpers ─────────────────────────────────────────────

def _html_to_png(html_path: str, watermark_path: str = None) -> str:
    """Render an HTML poster to PNG using headless Chromium. Returns temp file path.

    If watermark_path is provided, composites the image at the bottom-right
    corner of the poster (64 px, 85% opacity) using Pillow.
    """
    from playwright.sync_api import sync_playwright
    png = str(Path(tempfile.gettempdir()) / (Path(html_path).stem + ".png"))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page    = browser.new_page(viewport={"width": 1000, "height": 2000})
        # Block external font requests so rendering never hangs on network
        page.route("**fonts.googleapis.com**", lambda r: r.abort())
        page.route("**fonts.gstatic.com**",    lambda r: r.abort())
        page.goto(f"file://{html_path}", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        page.locator(".poster").screenshot(path=png, timeout=15000)
        browser.close()

    if watermark_path and Path(watermark_path).exists():
        try:
            from PIL import Image
            poster = Image.open(png).convert("RGBA")
            wm     = Image.open(watermark_path).convert("RGBA")
            size   = 110
            wm     = wm.resize((size, size), Image.LANCZOS)
            r, g, b, a = wm.split()
            a = a.point(lambda v: int(v * 0.85))
            wm = Image.merge("RGBA", (r, g, b, a))
            margin = 12
            poster.paste(wm, (poster.width - size - margin, poster.height - size - margin), wm)
            poster.convert("RGB").save(png)
        except Exception as e:
            print(f"   ⚠ watermark failed: {e}")

    return png


def _feishu_token() -> str:
    """Fetch a short-lived tenant access token using App ID + App Secret."""
    r = _httpx.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
        timeout=10,
    )
    d = r.json()
    if d.get("code", -1) != 0:
        raise RuntimeError(f"Feishu token error: {d}")
    return d["tenant_access_token"]


def _upload_image(png_path: str, token: str) -> str:
    """Upload a PNG to Feishu CDN; returns image_key for embedding in cards."""
    with open(png_path, "rb") as fh:
        r = _httpx.post(
            "https://open.feishu.cn/open-apis/im/v1/images",
            headers={"Authorization": f"Bearer {token}"},
            data={"image_type": "message"},
            files={"image": ("poster.png", fh, "image/png")},
            timeout=30,
        )
    d = r.json()
    if d.get("code", -1) != 0:
        raise RuntimeError(f"Feishu image upload error: {d}")
    return d["data"]["image_key"]


# ── Main entry point ─────────────────────────────────────────────────

def feishu_push(brief: str, ticker: str, poster_htmls: list = None, watermark_path: str = None):
    """Send brief + optional posters as a single interactive card to the Feishu group.

    Args:
        brief:        Generated Chinese brief (Markdown, trimmed to intro section).
        ticker:       Stock ticker symbol (used for poster alt text).
        poster_htmls: List of absolute paths to HTML poster files (EN + ZH).
                      Requires FEISHU_APP_SECRET to upload images.
        watermark_path: Path to watermark image composited onto each poster.
    """
    if _httpx is None:
        print("   ⚠ httpx not installed — pip install httpx")
        return

    image_keys = []
    if poster_htmls and FEISHU_APP_SECRET:
        try:
            token = _feishu_token()
            for html_path in poster_htmls:
                png = _html_to_png(html_path, watermark_path=watermark_path)
                key = _upload_image(png, token)
                Path(png).unlink(missing_ok=True)
                image_keys.append(key)
            print(f"   ✓ {len(image_keys)} poster(s) uploaded")
        except Exception as e:
            print(f"   ⚠ poster upload failed: {e}")
    elif poster_htmls and not FEISHU_APP_SECRET:
        print("   ⓘ posters skipped — set FEISHU_APP_SECRET to enable image upload")

    card    = build_card(brief, ticker, image_keys=image_keys or None)
    payload = _signed({"msg_type": "interactive", "card": card})
    for attempt in range(3):
        r = _httpx.post(FEISHU_WEBHOOK, json=payload, timeout=10)
        d = r.json()
        if d.get("code", d.get("StatusCode", -1)) == 11232:
            # Feishu frequency limit — back off and retry
            wait = 3 + attempt * 2 + random.uniform(0, 1)
            print(f"   ↺ rate limited, retrying in {wait:.1f}s...")
            time.sleep(wait)
            continue
        break
    if d.get("StatusCode", d.get("code", -1)) != 0:
        print(f"   ✗ Feishu send failed: {d}")
    else:
        suffix = f" + 海报×{len(image_keys)}" if image_keys else ""
        print(f"   ✓ Feishu 消息已发送{suffix}")


# ── Standalone test ──────────────────────────────────────────────────

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Test Feishu webhook connectivity")
    ap.add_argument("--test", action="store_true", help="Send a test card to the group")
    args = ap.parse_args()

    if args.test:
        print(f"Sending test message to webhook...")
        test_brief = (
            "Investing Community (TEST)  (连通性测试 — webhook check)\n\n"
            "测试消息 📈 收涨 $100.00 (+1.0%，前收 $99.00)\n\n"
            "*仅供测试，不构成投资建议。*"
        )
        feishu_push(test_brief, "TEST")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
