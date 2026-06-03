#!/usr/bin/env python3
"""
generate_posters.py — HTML poster generator (English + Chinese)

Reads briefs from output/{date}_briefs.md, generates two posters per ticker
(English _en.html and Chinese _zh.html), saves to 海报/.

Push rule: trimmed brief text (header + title + price line + 1-sentence summary)
+ both posters in a single Feishu card.

Usage
─────
  python3 generate_posters.py                       # today's briefs
  python3 generate_posters.py --date 2026-05-09     # specific date
  python3 generate_posters.py --ticker DDOG ASML    # specific tickers
  python3 generate_posters.py --force               # overwrite existing
  python3 generate_posters.py --push                # push combined card to Feishu
"""

import os, sys, re, argparse, json
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import anthropic
except ImportError:
    sys.exit("anthropic SDK not found — pip install anthropic")

BASE   = Path.home() / "Desktop/earnings season"
OUTPUT = BASE / "output"
POSTER = BASE / "海报"
MODEL  = "claude-sonnet-4-6"

_WM_PATH = BASE / "小老虎.jpeg"

sys.path.insert(0, str(BASE))
import push_feishu as _push

try:
    import fetch_prices as _fp
    _PRICES_OK = True
except ImportError:
    _PRICES_OK = False


# ── Poster CSS (shared with run_workflow.py) ──────────────────────────

POSTER_CSS = """\
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:#d4d4d4;display:flex;justify-content:center;align-items:flex-start;min-height:100vh;padding:48px 24px}
.poster{width:900px;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 12px 48px rgba(0,0,0,.18)}
.header{padding:30px 40px 26px;border-bottom:1px solid #ececec;display:flex;align-items:flex-start;justify-content:space-between;gap:24px}
.header-left{flex:1}
.header h1{font-size:27px;font-weight:900;color:#0f0f0f;line-height:1.2;margin-bottom:8px;letter-spacing:-.5px}
.header h1 em{font-style:normal}
.header .sub{font-size:13px;color:#666;line-height:1.55;max-width:560px}
.stock-badge{flex-shrink:0;border-radius:10px;padding:12px 18px;text-align:center}
.sb-label{font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#aaa;margin-bottom:3px}
.sb-val{font-size:26px;font-weight:900;letter-spacing:-.5px;line-height:1}
.sb-sub{font-size:10.5px;color:#aaa;margin-top:3px}
.body{display:grid;grid-template-columns:1fr 1fr}
.col{padding:28px 36px}
.col-left{border-right:1px solid #ececec}
.keyword-tags{display:flex;flex-wrap:wrap;gap:7px;margin-top:20px}
.kw-tag{font-size:11px;font-weight:700;padding:4px 10px;border-radius:20px;border:1.5px solid;letter-spacing:.2px;white-space:nowrap}
.col-label{font-size:10.5px;font-weight:700;letter-spacing:1.6px;text-transform:uppercase;color:#aaa;margin-bottom:20px}
.big-num-block{margin-bottom:22px}
.bn-label{font-size:12px;color:#888;font-weight:500;margin-bottom:2px}
.bn-value{font-size:42px;font-weight:900;color:#0f0f0f;letter-spacing:-1.5px;line-height:1.05}
.bn-sub{display:flex;align-items:center;gap:8px;margin-top:5px;font-size:13px;color:#555}
.chip{display:inline-flex;font-size:11px;font-weight:700;padding:2px 8px;border-radius:4px;white-space:nowrap}
.chip.g{background:#e8f5e9;color:#2e7d32}
.chip.r{background:#fce4ec;color:#c62828}
.chip.b{background:#e3f2fd;color:#1565c0}
.chip.n{background:#f5f5f5;color:#555}
.comp-table{width:100%;border-collapse:collapse;margin-bottom:22px}
.comp-table tr{border-bottom:1px solid #f4f4f4}
.comp-table td{padding:9px 0;font-size:13px;vertical-align:middle}
.comp-table .cn{color:#666;width:130px}
.comp-table .ca{font-weight:700;color:#111}
.comp-table .cb{text-align:right}
.seg-title{font-size:10.5px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;color:#bbb;margin-bottom:12px}
.seg-bar-row{margin-bottom:12px}
.seg-bar-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;font-size:12.5px}
.seg-bar-name{display:flex;align-items:center;gap:9px;color:#444}
.seg-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.seg-bar-vals{display:flex;gap:8px;align-items:center}
.seg-val{font-weight:700;color:#111}
.seg-yoy{font-size:11.5px;font-weight:700}
.seg-track{height:7px;background:#f0f0f0;border-radius:4px;overflow:hidden}
.seg-fill{height:100%;border-radius:4px}
.guidance-box{border-radius:12px;padding:18px 22px;margin-bottom:14px}
.g-tag{font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:6px}
.g-value{font-size:44px;font-weight:900;color:#0f0f0f;letter-spacing:-1.5px;line-height:1.05}
.g-beat{font-size:13px;color:#555;margin-top:6px}
.g-beat strong{color:#2e7d32}
.g-detail{font-size:12px;color:#999;margin-top:5px}
.mini-stats{display:grid;grid-template-columns:1fr 1fr 1fr;gap:1px;background:#ececec;border-radius:10px;overflow:hidden;margin-bottom:14px}
.mini-stat{background:#fff;padding:14px 10px;text-align:center}
.mini-stat .ms-val{font-size:22px;font-weight:900;letter-spacing:-.5px;line-height:1}
.mini-stat .ms-label{font-size:10.5px;color:#888;margin-top:3px;line-height:1.3}
.theme-box{border-left:3px solid;border-radius:0 8px 8px 0;padding:13px 16px;font-size:13px;margin-bottom:10px}
.theme-box .tb-title{font-weight:700;color:#111;margin-bottom:4px}
.theme-box .tb-body{color:#555;line-height:1.55}
.theme-box .tb-body b{color:#333}
.bottom-bar{padding:15px 40px;display:flex;align-items:center;justify-content:space-between;gap:20px}
.bb-left{display:flex;align-items:center;gap:20px}
.bb-bank{font-size:13px;font-weight:700;color:#fff}
.bb-rating{font-size:11px;padding:3px 10px;border-radius:4px;font-weight:600}
.bb-note{font-size:12px;color:#888}
.bb-pt-block{text-align:right}
.bb-pt{font-size:38px;font-weight:900;color:#fff;letter-spacing:-1px;line-height:1}
.bb-pt-sub{font-size:11px;color:rgba(255,255,255,.6);text-transform:uppercase;letter-spacing:.8px;margin-bottom:4px}
.bb-brand{font-size:10px;font-weight:600;color:#555;letter-spacing:1px;text-transform:uppercase}"""

POSTER_SYSTEM = f"""You are an expert financial infographic designer. Generate a complete standalone HTML earnings poster.

⚠️ LANGUAGE RULE — NON-NEGOTIABLE, ENFORCED:
Every single visible word in the HTML output MUST be in English.
The earnings brief you receive is written in Chinese — treat it as a data source ONLY.
Extract numbers, metrics, analyst ratings, and key facts, then write ALL of the following in English.
Do NOT copy any Chinese characters into the HTML. Zero Chinese allowed.
If you output even one Chinese character, the poster is rejected and must be regenerated.

⚠️ PROPER NOUNS — VERIFY VIA WEB SEARCH, NEVER TRANSLITERATE:
The company name and any named product / project / program / strategy / platform must use
the OFFICIAL English name. Use web search to confirm the correct name before writing it.
NEVER romanize a Chinese name into pinyin (e.g. do NOT output "xinpinmu" / "Mawei").
If you cannot confirm an official English name, keep the term in its original form rather
than inventing a pinyin string.

⚠️ RATING FABRICATION — STRICTLY FORBIDDEN:
NEVER show BUY / SELL / NEUTRAL / HOLD / OUTPERFORM anywhere on the poster unless the brief
explicitly states that rating. If the report is "Not Rated", "未予评级", or has no rating:
  • Show a gray chip with "NOT RATED" in Zone 1 — do NOT invent a rating.
  • The Zone 4 bottom bar must NOT contain any rating chip at all.
This applies to ALL zones. Inventing a rating is a critical error.

LAYOUT (four zones, top to bottom):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ZONE 1 — ANALYST BAR  (brand color background, no logos, text only)
Three sections left → center → right inside <div class="analyst-bar">:

  LEFT — Bank + Rating:
    • Bank name: 28px font-weight 900 white, e.g. "Citi Research" / "Goldman Sachs"
      If the input contains multiple reports (separated by "--- REPORT 2 ---"),
      show all bank names joined with " · ", e.g. "Goldman Sachs · Morgan Stanley"
    • Rating chip below: BUY=green bg, SELL=red bg, NEUTRAL/HOLD=gray bg, 13px bold
      If multiple ratings, show the most bullish one, or both if they differ
    ⚠️ FABRICATION FORBIDDEN: Only show a rating chip if the brief explicitly states one.
      If the report is "Not Rated", "未予评级", or has no rating at all:
      show a gray chip with "NOT RATED" text — do NOT invent BUY/SELL/NEUTRAL.

  CENTER — Price Target (focal point of the whole poster):
    • Label "PRICE TARGET": 10px, letter-spacing 2px, rgba(255,255,255,0.6), uppercase
    • PT value: 52px font-weight 900 white, e.g. "$300"
    • Delta below: 12px rgba(255,255,255,0.65), e.g. "↑ from $270 · Maintained Buy"
      or "↓ from $320 · Downgraded" or "Maintained · $XXX target"
    ⚠️ If there is NO price target (unrated / Not Rated / strategy note):
      Do NOT write "Not Rated" or "Unrated". Instead show the report's key theme:
      • Label: "KEY THEME" (same styling as "PRICE TARGET" label)
      • Replace the big PT number with a 2–3 word bold headline, e.g. "AI INFLECTION"
        (26–32px, white, font-weight 900, line-height 1.1 — fits in the same space)
      • Delta line: one short phrase capturing the headline metric, e.g. "GPU Cloud +184% YoY"

  RIGHT — Subject company (text only):
    • Company full English name: 28px font-weight 900 white, e.g. "NVIDIA"
    • Ticker + exchange below: 13px rgba(255,255,255,0.65), e.g. "NASDAQ: NVDA"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ZONE 2 — HEADLINE BLOCK  (white background)
  • Bold h1 title: "CompanyName QuarterYear: <em>Theme</em>"
  • Subtitle: 1–2 sentence key takeaway
  • NO stock price badge. NO price or AH data anywhere in this zone.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ZONE 3 — TWO-COLUMN BODY  (white background)
  LEFT col label: "FINANCIAL PERFORMANCE VS. CONSENSUS"
    - Big number block (headline metric, e.g. revenue)
    - Comparison table: metric | actual | beat/miss chip
    - Segment bar chart (bars proportional to size)
    - KEYWORD TAGS (always include, fills remaining space organically):
        After the segment bars, add a <div class="keyword-tags"> block containing
        4–6 <span class="kw-tag"> pills. Each pill is one punchy data point or theme
        pulled from the brief — e.g. "GPU Cloud +184% YoY", "AI >52% Mix",
        "Capex ↑ RMB5.8B", "Apollo Go +120%", "OP +28% QoQ".
        Style: brand color border + brand color text, transparent background.
        These summarise the headline signals at a glance.

  RIGHT col label: "GUIDANCE & STRATEGIC OUTLOOK"
    - Guidance highlight box (large number, colored border)
    - Company logo block (centred visual element):
        Large inline SVG ~120×120px of the company's logo mark in brand color,
        Large inline SVG ~120×120px of the company's logo mark in brand color,
        + company wordmark below in brand color, 28px bold.
        Use the actual recognisable logo shape:
          NVDA → green eye/lens (#76b900) + "nvidia"
          AMD  → red "AMD" arrow mark
          AAPL → grey apple silhouette
          MSFT → four-color Windows squares
          GOOG → multicolor "G"
          META → blue ∞ loop
          AMZN → arrow-smile + "amazon"
          DDOG → "DD" in purple
          NET  → orange cloud outline
          COIN → blue "C" circle
          FUTU → red bull/F mark
          MDB  → green leaf mark + "MongoDB"
          CRM  → blue cloud + "Salesforce"
          HIMS → lowercase "hims" bold wordmark
          AVGO → "Broadcom" wave or wordmark
          AMAT → "Applied Materials" block letters
          RKLB / FLY → rocket silhouette
          Others → bold styled initial of company name in brand color
        Wrap in <div class="logo-hero">
    - 1–2 theme/catalyst boxes

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ZONE 4 — BOTTOM BAR  (brand color background)
  Left: one-line analyst valuation note (white 12px)
  Right: "Investing Community" in #FFE100 bold
  ⚠️ NO rating chip here. Bank name and rating live in Zone 1 only.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BRAND COLORS (Zone 1 + Zone 4 background):
  Tech/Semis:  NVDA=#76b900  AMD=#CC0000  AAPL=#555555  MSFT=#00a4ef  GOOG=#4285F4
               META=#0866FF  AMZN=#FF9900  ASML=#009FDB  MCHP=#E2231A  ON=#005E8B
               SMCI=#E05A00  ALAB=#3B4BC8  ANET=#0077C8  ARM=#0091BD
  SaaS/Cloud:  DDOG=#632CA6  NET=#F48120   TWLO=#F22F46  PLTR=#1B3A8C  U=#000000
               MDB=#00684A   CRM=#00A1E0
  Fintech:     COIN=#1652F0  PYPL=#003087  FUTU=#E83535
  Consumer:    MCD=#DA291C   COST=#005DAA  PTON=#202020  APP=#6C3CE1
  Social:      PINS=#E60023  RDDT=#FF4500
  Pharma:      LLY=#c8102e
  Other:       HIMS=#E8475F  AVGO=#CC0000  AMAT=#1A73E8  RKLB=#1B3A8C  FLY=#1A1A2E
  If ticker not listed, pick a professional dark color matching the company brand.

OTHER RULES:
- 900px fixed width, white card, border-radius 14px, Inter font, box-shadow
- Chips: .chip.g=green beat/buy, .chip.r=red miss/sell, .chip.b=blue neutral, .chip.n=gray
- All text in English. Date format: Q1 2026 / Q2 2026 etc.
- Investing Community (#FFE100) accent only in Zone 4 right side.

MANDATORY CSS — include verbatim inside <style>, then append company-specific rules:
```
{POSTER_CSS}
```
After mandatory CSS also add:
.analyst-bar{{display:flex;align-items:center;justify-content:space-between;padding:22px 40px;gap:16px}}
.ab-bank-name{{font-size:28px;font-weight:900;color:#fff;letter-spacing:-.5px;line-height:1.1}}
.ab-bank-sub{{display:inline-flex;font-size:13px;font-weight:700;padding:3px 12px;border-radius:4px;margin-top:8px}}
.ab-pt-block{{text-align:center}}
.ab-pt-label{{font-size:10px;font-weight:700;letter-spacing:2px;color:rgba(255,255,255,.55);text-transform:uppercase;margin-bottom:4px}}
.ab-pt-val{{font-size:52px;font-weight:900;color:#fff;letter-spacing:-2px;line-height:1}}
.ab-pt-delta{{font-size:12px;color:rgba(255,255,255,.65);margin-top:5px}}
.ab-company{{text-align:right}}
.ab-company-name{{font-size:28px;font-weight:900;color:#fff;letter-spacing:-.5px;line-height:1.1}}
.ab-company-sub{{font-size:13px;color:rgba(255,255,255,.65);margin-top:5px}}
.logo-hero{{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:24px 0;gap:12px}}
.logo-hero .logo-wordmark{{font-size:28px;font-weight:900;letter-spacing:-1px}}

OUTPUT: A complete HTML file only. Start with <!DOCTYPE html>, end with </html>.
Do NOT wrap in markdown code fences. Output raw HTML."""


# ── Helpers ───────────────────────────────────────────────────────────

def validate_brief(brief: str, ticker: str, strict: bool = False) -> bool:
    """Pre-push validation gate. Runs 4 checks:

      ① Format    — header has (TICKER), $Company(TICKER)$ present, required sections, disclaimer
      ② Price     — price emoji (📈/📉/🚀) present
      ③ Freshness — market_data.json fetched within 4 hours
      ④ Deviation — brief price vs Tiger cache within 5%

    Non-strict: prints warnings, returns True. Strict: blocks on any failure.
    """
    issues = []

    lines = brief.strip().split('\n')
    if not re.search(r'\([A-Z0-9]{1,6}(?:\.[A-Z]{1,2})?\)', lines[0] if lines else ''):
        issues.append("① header missing (TICKER) pattern")
    if not re.search(r'\$[^(]+\([A-Z0-9]{1,6}(?:\.[A-Z]{1,2})?\)\$', brief):
        issues.append("① $Company(TICKER)$ line not found")
    for sec in ['**核心财务数据**', '**分析师观点**']:
        if sec not in brief:
            issues.append(f"① missing section: {sec}")
    if '仅供社区讨论' not in brief:
        issues.append("① disclaimer missing")

    if not any(e in brief for e in ('📈', '📉', '🚀')):
        issues.append("② no price emoji — price line may be missing")

    data_file = BASE / "market_data.json"
    cached_prices = {}
    if data_file.exists():
        try:
            raw     = json.loads(data_file.read_text(encoding='utf-8'))
            fetched = raw.get('fetched_at', '')
            if fetched:
                edt = timezone(timedelta(hours=-4))
                age = datetime.now(edt) - datetime.fromisoformat(fetched)
                if age.total_seconds() > 4 * 3600:
                    issues.append(f"③ market_data.json is {int(age.total_seconds()//3600)}h old")
            cached_prices = raw.get('prices', {})
        except Exception:
            pass
    else:
        issues.append("③ market_data.json not found — run fetch_prices.py first")

    if ticker and ticker in cached_prices:
        cached_close = cached_prices[ticker].get('close', 0)
        if cached_close > 0:
            m = re.search(r'[📈📉🚀][^$\n]*\$([\d,]+\.?\d*)', brief)
            if m:
                try:
                    brief_price = float(m.group(1).replace(',', ''))
                    deviation   = abs(brief_price - cached_close) / cached_close
                    if deviation > 0.05:
                        issues.append(
                            f"④ price mismatch: brief ${brief_price:,.2f} vs "
                            f"Tiger ${cached_close:,.2f} ({deviation*100:.1f}% off)"
                        )
                except ValueError:
                    pass

    if not issues:
        print(f"   ✅ validation passed")
        return True

    label = "🚫 BLOCKED" if strict else "⚠️  WARNING"
    for iss in issues:
        print(f"   {label} {iss}")
    return not strict


def get_client() -> anthropic.Anthropic:
    key      = os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")
    base_url = os.getenv("ANTHROPIC_BASE_URL")
    if not key:
        sys.exit("\nError: set ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN\n")
    kwargs = {"api_key": key, "timeout": 300.0, "max_retries": 5}
    if base_url:
        kwargs["base_url"] = base_url
    return anthropic.Anthropic(**kwargs)


# Server-side web search — verify official company / project names, no transliteration.
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}


def _final_text(resp) -> str:
    """Extract the poster HTML from a response that may include web_search tool blocks."""
    blocks = list(resp.content)
    last_tool = -1
    for i, b in enumerate(blocks):
        if getattr(b, "type", "") in ("server_tool_use", "web_search_tool_result", "tool_use"):
            last_tool = i
    texts = [b.text for b in blocks[last_tool + 1:] if getattr(b, "type", "") == "text"]
    if not texts:
        texts = [b.text for b in blocks if getattr(b, "type", "") == "text"]
    return "".join(texts).strip()


def apply_name_glossary(text: str) -> str:
    """Enforce verified official company / project names via name_glossary.json.

    Same operator-maintained glossary used by run_workflow.py — applied to poster
    HTML as a safety net so the model cannot re-introduce a wrong name / pinyin.
    """
    gpath = BASE / "name_glossary.json"
    if not gpath.exists():
        return text
    try:
        g = json.loads(gpath.read_text(encoding="utf-8"))
    except Exception:
        return text
    for wrong, right in g.get("replacements", {}).items():
        if wrong:
            text = text.replace(wrong, right)
    return text


def has_chinese(text: str) -> bool:
    """Return True if any CJK character is present in visible text."""
    # Strip HTML tags first
    stripped = re.sub(r'<[^>]+>', ' ', text)
    return bool(re.search(r'[一-鿿㐀-䶿]', stripped))


def extract_ticker(brief: str) -> str:
    """Extract ticker from $Company(TICKER)$ pattern in brief."""
    m = re.search(r'\$[^(]+\(([A-Z0-9]{1,6}(?:\.[A-Z]{1,3})?)\)', brief)
    return m.group(1) if m else None


def normalize_ticker(ticker: str) -> str:
    """Normalize HK tickers so duplicates are detected: 0700.HK / 700 / 00700 → 00700."""
    t = ticker.replace('.HK', '').replace('.hk', '')
    if t.isdigit():
        return t.zfill(5)
    return ticker


def ticker_to_slug(ticker: str) -> str:
    return ticker.lower().replace('.', '_')


def split_briefs(md_text: str) -> list[str]:
    """Split combined briefs MD file into individual briefs."""
    parts = re.split(r'\n\n---\n\n', md_text)
    # Skip the header line "# Earnings Briefs — YYYY-MM-DD"
    briefs = []
    for p in parts:
        p = p.strip()
        if p.startswith('#'):
            # Strip the header line only
            lines = p.split('\n', 1)
            if len(lines) > 1:
                p = lines[1].strip()
        if p:
            briefs.append(p)
    return briefs


def generate_poster(brief: str, ticker: str, client: anthropic.Anthropic,
                    max_retries: int = 2) -> str:
    """Generate English-only HTML poster. Retries if Chinese characters detected."""
    prompt = (
        f"Ticker: {ticker}\n\n"
        f"Earnings Brief (Chinese — use as data source, output English only):\n{brief}"
    )

    for attempt in range(1, max_retries + 2):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=8000,
            system=[{"type": "text", "text": POSTER_SYSTEM,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
        )
        html = _final_text(resp)

        html = re.sub(r'^\s*```(?:html)?\s*\n?', '', html)
        html = re.sub(r'\n?\s*```\s*$',          '', html)
        html = html.strip()

        if not has_chinese(html):
            return apply_name_glossary(html)

        print(f"   ⚠ attempt {attempt}: Chinese characters detected, retrying...")
        # Strengthen the prompt for the retry
        prompt = (
            f"Ticker: {ticker}\n\n"
            f"REMINDER: Output ONLY English. No Chinese characters whatsoever.\n\n"
            f"Earnings Brief (data source — translate everything to English):\n{brief}"
        )

    raise RuntimeError(f"Could not generate English-only poster after {max_retries + 1} attempts")


def trim_brief_for_push(brief: str) -> str:
    """Keep only the first 4 paragraph blocks for the Feishu text card.

    Structure kept: header | narrative title | price line | one-sentence summary.
    The detailed financial sections (**核心财务数据** etc.) are shown in the poster.
    """
    paragraphs = re.split(r'\n\n+', brief.strip())
    return '\n\n'.join(paragraphs[:4])


# ── Chinese poster ────────────────────────────────────────────────────

POSTER_SYSTEM_ZH = f"""You are an expert financial infographic designer. Generate a complete standalone HTML earnings poster in CHINESE.

⚠️ LANGUAGE RULE — NON-NEGOTIABLE:
ALL visible text MUST be in Chinese, EXCEPT:
- Ticker symbols (BABA, NVDA, etc.)
- Financial numbers ($208, +1.5%, RMB 30bn, etc.)
- Standard finance abbreviations: EPS, YoY, QoQ, bps, ARR, EBITDA
- Bank / institution names: Citi, Goldman Sachs, JPMorgan, UBS, Morgan Stanley, etc.
- Quarter/year labels: Q1 2026, FY2026, etc.

⚠️ 专有名词 — 必须 web search 核实，禁止音译：
公司中文名必须与简报一致且为官方中文名；研报提及的产品/项目/计划/战略/平台名称，
必须用 web search 核实其官方中文名后再写入，严禁音译成拼音（如「xinpinmu」）或自行编造译名。
例：Marvell 官方中文名为「迈威尔科技」。若无法确认官方中文名，保留英文原文，仍不得音译。

⚠️ 评级编造 — 严格禁止：
海报上任何位置均不得出现"买入/卖出/中性/增持"等评级，除非简报明确写有该评级。
若研报为"未予评级"或无评级：Zone 1 只显示灰色chip写"未予评级"；Zone 4底栏不放任何评级chip。
编造评级是严重错误。

LAYOUT (four zones, identical structure to English poster):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ZONE 1 — 分析师栏  (brand color background, text only)
Three sections left → center → right inside <div class="analyst-bar">:

  LEFT — 投行 + 评级:
    • Bank name: 28px font-weight 900 white
      Multiple reports: "Goldman Sachs · Morgan Stanley"
    • Rating chip below: 买入=green bg, 卖出=red bg, 中性/持有=gray bg, 13px bold
    ⚠️ 禁止编造评级：只有当简报明确写有评级时才显示chip。
      若研报为"未予评级"或无评级，显示灰色chip写"未予评级" — 不得自行写"买入/卖出/中性"。

  CENTER — 目标价:
    • Label "目标价": 10px, letter-spacing 2px, rgba(255,255,255,0.6), uppercase
    • PT value: 52px font-weight 900 white, e.g. "$300"
    • Delta below: 12px rgba(255,255,255,0.65), e.g. "↑ 前目标价 $270 · 维持买入"
      or "↓ 前目标价 $320 · 下调" or "维持 · $XXX"
    ⚠️ 若无目标价（未予评级 / 策略类研报）：
      禁止写"未评级"或"未予评级"。改为展示报告核心主题：
      • Label 改为"核心主题"（相同样式）
      • 大字改为 2–3 个字的主题词，例如"AI 转型"（26–32px，白色，font-weight 900）
      • Delta 行：一个捕捉核心指标的短语，例如"GPU云收入 +184% YoY"

  RIGHT — 公司:
    • Company Chinese name (+ English in parentheses if useful): 28px font-weight 900 white
    • Ticker + exchange: 13px rgba(255,255,255,0.65), e.g. "NASDAQ: NVDA"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ZONE 2 — 标题区块  (white background)
  • h1: Chinese narrative title (use the brief's Chinese title line directly)
  • Subtitle: 1–2 sentence Chinese key takeaway
  • NO stock price badge. NO price data anywhere in this zone.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ZONE 3 — 双栏正文  (white background)
  LEFT col label: "财务数据 VS. 市场预期"
    - Big number block (headline metric, e.g. 营收)
    - Comparison table: metric | 实际 | beat/miss chip (chips: 超预期/符合/低于预期)
    - Segment bar chart
    - 关键词标签（必须包含，自然填充剩余空间）：
        在分段柱状图后，加一个 <div class="keyword-tags"> 块，包含
        4–6 个 <span class="kw-tag"> pill 标签。每个标签是一个简短的数据亮点，
        例如："GPU云 +184% YoY"、"AI占比 >52%"、"资本支出 ↑ RMB5.8B"、
        "Apollo Go +120%"、"OP +28% QoQ"。
        样式：品牌色边框 + 品牌色文字，透明背景。

  RIGHT col label: "业绩指引与战略展望"
    - Guidance highlight box (large number, Chinese label, colored border)
    - Company logo block (same SVG mark as English poster) — 若logo已移至左列则此处省略:
        Large inline SVG ~120×120px of the company's logo mark in brand color,
        + Chinese company name below in brand color, 28px bold.
        Same logo shapes as English version (NVDA green eye, AAPL apple, etc.)
        Wrap in <div class="logo-hero">
    - 1–2 theme/catalyst boxes in Chinese

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ZONE 4 — 底栏  (brand color background)
  Left: one-line analyst valuation note in Chinese (white 12px)
  Right: "投资社区" in #FFE100 bold
  ⚠️ 底栏不放评级chip，评级只在Zone 1分析师栏显示。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BRAND COLORS (Zone 1 + Zone 4 background) — same as English version:
  Tech/Semis:  NVDA=#76b900  AMD=#CC0000  AAPL=#555555  MSFT=#00a4ef  GOOG=#4285F4
               META=#0866FF  AMZN=#FF9900  ASML=#009FDB  MCHP=#E2231A  ON=#005E8B
               SMCI=#E05A00  ALAB=#3B4BC8  ANET=#0077C8  ARM=#0091BD
  SaaS/Cloud:  DDOG=#632CA6  NET=#F48120   TWLO=#F22F46  PLTR=#1B3A8C  U=#000000
               MDB=#00684A   CRM=#00A1E0
  Fintech:     COIN=#1652F0  PYPL=#003087  FUTU=#E83535
  Consumer:    MCD=#DA291C   COST=#005DAA  PTON=#202020  APP=#6C3CE1
  Social:      PINS=#E60023  RDDT=#FF4500
  Pharma:      LLY=#c8102e
  HK/CN:       BABA=#FF6A00  00700=#00B0EA  JD=#CC0000  MNSO=#FF3A20  BIDU=#2932E1
  Other:       HIMS=#E8475F  AVGO=#CC0000  AMAT=#1A73E8  RKLB=#1B3A8C  FLY=#1A1A2E
  If ticker not listed, pick a professional dark color matching the company brand.

OTHER RULES:
- 900px fixed width, white card, border-radius 14px, Inter font, box-shadow
- All labels and descriptive text in Chinese; numbers/tickers/abbreviations stay as-is
- Date format: Q1 2026 / FY2026 (keep as-is) or "2026年一季度" if context is Chinese
- "投资社区" (#FFE100) accent only in Zone 4 right side

MANDATORY CSS — include verbatim inside <style>, then append company-specific rules:
```
{POSTER_CSS}
```
After mandatory CSS also add:
.analyst-bar{{display:flex;align-items:center;justify-content:space-between;padding:22px 40px;gap:16px}}
.ab-bank-name{{font-size:28px;font-weight:900;color:#fff;letter-spacing:-.5px;line-height:1.1}}
.ab-bank-sub{{display:inline-flex;font-size:13px;font-weight:700;padding:3px 12px;border-radius:4px;margin-top:8px}}
.ab-pt-block{{text-align:center}}
.ab-pt-label{{font-size:10px;font-weight:700;letter-spacing:2px;color:rgba(255,255,255,.55);text-transform:uppercase;margin-bottom:4px}}
.ab-pt-val{{font-size:52px;font-weight:900;color:#fff;letter-spacing:-2px;line-height:1}}
.ab-pt-delta{{font-size:12px;color:rgba(255,255,255,.65);margin-top:5px}}
.ab-company{{text-align:right}}
.ab-company-name{{font-size:28px;font-weight:900;color:#fff;letter-spacing:-.5px;line-height:1.1}}
.ab-company-sub{{font-size:13px;color:rgba(255,255,255,.65);margin-top:5px}}
.logo-hero{{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:24px 0;gap:12px}}
.logo-hero .logo-wordmark{{font-size:28px;font-weight:900;letter-spacing:-1px}}

OUTPUT: A complete HTML file only. Start with <!DOCTYPE html>, end with </html>.
Do NOT wrap in markdown code fences. Output raw HTML."""


def generate_poster_zh(brief: str, ticker: str, client: anthropic.Anthropic) -> str:
    """Generate Chinese-language HTML poster from the brief."""
    prompt = (
        f"Ticker: {ticker}\n\n"
        f"Earnings Brief (source material — output Chinese poster):\n{brief}"
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=[{"type": "text", "text": POSTER_SYSTEM_ZH,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}],
    )
    html = _final_text(resp)

    html = re.sub(r'^\s*```(?:html)?\s*\n?', '', html)
    html = re.sub(r'\n?\s*```\s*$',          '', html)
    return apply_name_glossary(html.strip())


# ── Main ──────────────────────────────────────────────────────────────

# ── Collection poster (multi-ticker conference / sector roundup) ──────

_COLL_CSS = """
.coll-head{padding:26px 36px}
.coll-src{font-size:11px;font-weight:800;letter-spacing:2px;text-transform:uppercase;color:rgba(255,255,255,.6)}
.coll-title{font-size:32px;font-weight:900;color:#fff;letter-spacing:-.5px;line-height:1.1;margin:6px 0}
.coll-sub{font-size:14px;color:rgba(255,255,255,.82);line-height:1.4}
.tk-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:28px 36px}
.tk-card{border:1px solid #e3e8f0;border-radius:12px;padding:18px 20px;background:#fff}
.tk-top{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:4px}
.tk-name{font-size:18px;font-weight:900;color:#14213d;line-height:1.1}
.tk-chip{font-size:13px;font-weight:800;padding:4px 10px;border-radius:6px;color:#fff;white-space:nowrap}
.tk-chip.up{background:#15a34a}
.tk-chip.down{background:#dc2626}
.tk-chip.flat{background:#6b7280}
.tk-sub{font-size:12px;color:#6b7280;margin-bottom:10px}
.tk-card ul{margin:0;padding-left:16px}
.tk-card li{font-size:13px;color:#374151;margin:4px 0;line-height:1.42}
.coll-foot{display:flex;justify-content:space-between;align-items:center;padding:16px 36px}
.coll-foot .left{font-size:12px;color:rgba(255,255,255,.85)}
.coll-foot .right{font-size:14px;font-weight:900;color:#FFE100}
"""

POSTER_SYSTEM_COLLECTION = f"""You are an expert financial infographic designer. Generate ONE standalone HTML poster
that summarizes a MULTI-COMPANY research note (a conference recap or sector roundup), in ENGLISH ONLY.

⚠️ LANGUAGE: every visible word MUST be English. The brief is Chinese — data source only. Zero Chinese characters.
⚠️ PROPER NOUNS: use official English company / product names. NEVER pinyin-transliterate.
⚠️ NO FABRICATION: only use prices, ratings and facts present in the brief.

The brief covers SEVERAL tickers, each with its own price line and the bank's view. Lay it out as a
SCANNABLE GRID OF CARDS so a reader grasps every name in seconds.

LAYOUT:
ZONE 1 — HEADER BAND (dark brand background, class="coll-head"):
  • <div class="coll-src"> = the bank / source, e.g. "JEFFERIES RESEARCH"
  • <div class="coll-title"> = the event / theme, e.g. "Software, Internet & AI Conference"
  • <div class="coll-sub"> = one-sentence core conclusion drawn from the brief
ZONE 2 — TICKER CARD GRID (<div class="tk-grid">), one <div class="tk-card"> per ticker:
  • <div class="tk-top"><span class="tk-name">Company English Name</span>
       <span class="tk-chip up|down|flat">$PRICE ±X%</span></div>
       (use the brief's price number verbatim; green chip if up, red if down)
  • <div class="tk-sub">EXCHANGE: TICKER</div>   (e.g. NYSE: SNOW)
  • <ul> with 2–3 <li> — the bank's key view on THIS company, pulled from the brief
ZONE 3 — BOTTOM BAR (dark brand background, class="coll-foot"):
  • left: one-line overall takeaway or key risk
  • right: "Investing Community"

Use a neutral professional dark brand color for the bands: #1B2A4A.

MANDATORY CSS — include verbatim inside <style>, then the collection rules below:
```
{POSTER_CSS}
```
Append verbatim:
```
{_COLL_CSS}
```
All visible content MUST be wrapped in a single <div class="poster"> … </div> (900px white card);
the three zones are direct children of it. This wrapper is required for rendering.
OUTPUT: raw HTML only. Start <!DOCTYPE html>, end </html>. No markdown fences."""

POSTER_SYSTEM_COLLECTION_ZH = f"""你是专业的金融信息图设计师。为一篇【多标的研报】(券商大会综述或行业横评)生成一张独立 HTML 海报，用中文。

⚠️ 语言：除 ticker、数字、EPS/YoY/QoQ 等缩写、投行名外，所有可见文字用中文。
⚠️ 专有名词：公司中文名与简报一致且为官方名，严禁音译成拼音；无法确认则保留英文原文。
⚠️ 禁止编造：只用简报中出现的价格、评级与事实。

本简报覆盖多个标的，每个标的有各自行情与大行观点。请做成【可快速扫读的卡片网格】，让读者几秒看完每个标的。

布局：
ZONE 1 — 头部条 (深色背景, class="coll-head")：
  • <div class="coll-src"> = 投行/来源，如「Jefferies 研究」
  • <div class="coll-title"> = 大会/主题，如「软件 · 互联网 · AI 大会回顾」
  • <div class="coll-sub"> = 从简报提炼的一句话核心结论
ZONE 2 — 标的卡片网格 (<div class="tk-grid">)，每个标的一个 <div class="tk-card">：
  • <div class="tk-top"><span class="tk-name">公司中文名</span>
       <span class="tk-chip up|down|flat">$价格 ±X%</span></div>
       (价格数字照搬简报；涨用绿 chip，跌用红 chip)
  • <div class="tk-sub">交易所: TICKER</div>
  • <ul> 2–3 条 <li> — 大行对该标的的核心观点，取自简报
ZONE 3 — 底栏 (深色背景, class="coll-foot")：
  • 左：一句话总体结论或关键风险
  • 右：「Investing Community」

深色品牌色统一用 #1B2A4A。

必须内联以下 CSS (原样放入 <style>)，再追加合集样式：
```
{POSTER_CSS}
```
追加：
```
{_COLL_CSS}
```
所有可见内容必须包裹在单个 <div class="poster"> … </div> (900px 白卡) 内，三个 ZONE 为其直接子元素；该外层是渲染所必需的。
输出：仅原始 HTML，<!DOCTYPE html> 开头、</html> 结尾，不要 markdown 代码围栏。"""


def is_collection(brief: str) -> bool:
    """A brief covering ≥3 distinct $Name(TICKER)$ tickers → multi-ticker collection."""
    tks = set(re.findall(r'\$[^()$]+\(([A-Z0-9]{1,6}(?:\.[A-Z]{1,3})?)\)\$', brief))
    return len(tks) >= 3


def generate_collection_poster(brief: str, client: anthropic.Anthropic, max_retries: int = 2) -> str:
    """English modular poster for a multi-ticker collection brief."""
    prompt = f"Multi-company research brief (Chinese — data source, output English only):\n{brief}"
    for attempt in range(1, max_retries + 2):
        resp = client.messages.create(
            model=MODEL, max_tokens=8000,
            system=[{"type": "text", "text": POSTER_SYSTEM_COLLECTION,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
        )
        html = _final_text(resp)
        html = re.sub(r'^\s*```(?:html)?\s*\n?', '', html)
        html = re.sub(r'\n?\s*```\s*$', '', html).strip()
        if not has_chinese(html):
            return apply_name_glossary(html)
        print(f"   ⚠ attempt {attempt}: Chinese detected in collection poster, retrying...")
        prompt = f"REMINDER: English only, zero Chinese.\n\n{prompt}"
    raise RuntimeError(f"Could not generate English-only collection poster after {max_retries + 1} attempts")


def generate_collection_poster_zh(brief: str, client: anthropic.Anthropic) -> str:
    """Chinese modular poster for a multi-ticker collection brief."""
    resp = client.messages.create(
        model=MODEL, max_tokens=8000,
        system=[{"type": "text", "text": POSTER_SYSTEM_COLLECTION_ZH,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": f"多标的研报简报：\n{brief}"}],
    )
    html = _final_text(resp)
    html = re.sub(r'^\s*```(?:html)?\s*\n?', '', html)
    html = re.sub(r'\n?\s*```\s*$', '', html).strip()
    return apply_name_glossary(html)


def main():
    ap = argparse.ArgumentParser(description="Generate English + Chinese earnings posters")
    ap.add_argument("--date",   default=datetime.today().strftime('%Y-%m-%d'),
                    help="Brief date (default: today)")
    ap.add_argument("--ticker", nargs='+', metavar='TICKER',
                    help="Only process these tickers")
    ap.add_argument("--force",  action="store_true", help="Overwrite existing posters")
    ap.add_argument("--push",   action="store_true",
                    help="Push trimmed brief + both posters to Feishu in one card")
    ap.add_argument("--strict", action="store_true", help="Block push if brief validation fails")
    args = ap.parse_args()

    briefs_file = OUTPUT / f"{args.date}_briefs.md"
    if not briefs_file.exists():
        sys.exit(f"Briefs file not found: {briefs_file}\nRun run_workflow.py first.")

    POSTER.mkdir(exist_ok=True)
    client = get_client()

    raw    = briefs_file.read_text(encoding='utf-8')
    briefs = split_briefs(raw)

    if not briefs:
        sys.exit("No briefs found in file.")

    print(f"\nPoster Generation  —  {args.date}")
    print(f"Source: {briefs_file.name}   Briefs: {len(briefs)}")
    if args.push and not _push.FEISHU_APP_SECRET:
        sys.exit("🚫 FEISHU_APP_SECRET not set — run: source ~/.zshrc")
    print(f"{'─'*50}\n")

    # Group briefs by normalised ticker — same ticker → one poster
    from collections import OrderedDict
    groups: OrderedDict = OrderedDict()
    for brief in briefs:
        ticker = extract_ticker(brief)
        if not ticker:
            print(f"⚠  Could not extract ticker, skipping:\n   {brief[:80]}")
            continue
        key = normalize_ticker(ticker)
        groups.setdefault(key, []).append((ticker, brief))

    ok, fail = 0, 0
    wm = str(_WM_PATH) if _WM_PATH.exists() else None

    for norm_ticker, items in groups.items():
        ticker = items[0][0]
        slug   = ticker_to_slug(norm_ticker)

        if args.ticker and norm_ticker not in [normalize_ticker(t) for t in args.ticker]:
            continue

        if len(items) > 1:
            print(f"▶  {norm_ticker}  ({len(items)} reports — merging)")
            combined_brief = "\n\n--- REPORT 2 ---\n\n".join(b for _, b in items)
            push_brief     = items[0][1]
        else:
            print(f"▶  {ticker}")
            combined_brief = items[0][1]
            push_brief     = combined_brief

        ppath_en = POSTER / f"poster_{slug}_{args.date}_en.html"
        ppath_zh = POSTER / f"poster_{slug}_{args.date}_zh.html"

        coll = is_collection(combined_brief)
        if coll:
            print(f"   ◧ collection poster (multi-ticker)")

        # ── Generate English poster ──────────────────────────────────
        if args.force or not ppath_en.exists():
            try:
                html = (generate_collection_poster(combined_brief, client) if coll
                        else generate_poster(combined_brief, ticker, client))
                ppath_en.write_text(html, encoding='utf-8')
                print(f"   ✓ {ppath_en.name}")
                ok += 1
            except Exception as e:
                print(f"   ✗ EN: {e}")
                fail += 1
                ppath_en = None
        else:
            print(f"   ⓘ EN exists — skipping (use --force)")

        # ── Generate Chinese poster ──────────────────────────────────
        if args.force or not ppath_zh.exists():
            try:
                html = (generate_collection_poster_zh(combined_brief, client) if coll
                        else generate_poster_zh(combined_brief, ticker, client))
                ppath_zh.write_text(html, encoding='utf-8')
                print(f"   ✓ {ppath_zh.name}")
            except Exception as e:
                print(f"   ✗ ZH: {e}")
                ppath_zh = None
        else:
            print(f"   ⓘ ZH exists — skipping (use --force)")

        # ── Push: trimmed brief + both posters in one card ───────────
        # HARD RULE: a Feishu card MUST carry brief text + both posters together.
        # If either poster failed to generate, NEVER fall back to a text-only push.
        if args.push:
            poster_htmls = [str(p) for p in [ppath_en, ppath_zh]
                            if p is not None and Path(p).exists()]
            if len(poster_htmls) < 2:
                print(f"   🚫 推送跳过 — 海报未齐（{len(poster_htmls)}/2），不发纯文字简报。"
                      f"修复后用 --ticker {norm_ticker} 重跑")
                fail += 1
            elif not validate_brief(push_brief, ticker, strict=args.strict):
                print(f"   🚫 push skipped (validation failed)")
            else:
                # Collection briefs keep every ticker in the text card; single-name briefs are trimmed.
                trimmed = push_brief if coll else trim_brief_for_push(push_brief)
                _push.feishu_push(trimmed, ticker,
                                  poster_htmls=poster_htmls,
                                  watermark_path=wm)

    print(f"\n{'─'*50}")
    print(f"Done  ✓{ok}  {'✗' + str(fail) if fail else ''}\n")


if __name__ == "__main__":
    main()
