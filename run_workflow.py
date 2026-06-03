#!/usr/bin/env python3
"""
run_workflow.py — Step 2: generate briefs, save to output/

Reads research PDFs/MDs from 研报input/, generates a Chinese narrative brief
for each, saves all briefs to output/{date}_briefs.md.
Does NOT push to Feishu — use generate_posters.py --push (Step 3) which sends
a combined card (brief text + English poster) in a single Feishu message.

Depends on:
  fetch_prices.py      — pre-fetched Tiger prices in market_data.json
  preprocess_pdfs.py   — PDF text cache in 研报input/.cache/

Usage
─────
  python3 run_workflow.py          # generate all briefs in 研报input/
"""

import os, sys, re, glob, argparse, base64, json
from datetime import datetime
from pathlib import Path

try:
    import anthropic
except ImportError:
    sys.exit("anthropic SDK not found — run: pip install anthropic")

# ── Paths ─────────────────────────────────────────────────────────────
BASE   = Path.home() / "Desktop/earnings season"
INPUT  = BASE / "研报input"
OUTPUT = BASE / "output"
MODEL  = "claude-sonnet-4-6"

# ── Sibling modules ───────────────────────────────────────────────────
sys.path.insert(0, str(BASE))

try:
    import fetch_prices as _fp
    _PRICES_OK = True
except ImportError:
    _PRICES_OK = False

try:
    import preprocess_pdfs as _pp
    _PDF_CACHE_OK = True
except ImportError:
    _PDF_CACHE_OK = False



# ── Brief prompts ─────────────────────────────────────────────────────

BRIEF_EXAMPLE = """
ON Semiconductor (ON)  (Goldman Sachs 中性 / Neutral，目标价 $80，前目标价 $60 — 上调 +33.3%)

安森美：汽车周期拐点信号 + AI电源芯片爆发，双重超预期

$安森美(ON)$ 财报公布后震荡走高，盘中一度转绿。📈 收涨 $62.45 (+3.1%，前收 $60.57) | 盘前: $63.20 (+1.2%) [06:15 EDT]

指引超出市场预期，但整体市场反应相对克制。

本次财报有两个被低估的信号值得关注：其一，汽车业务时隔七个季度首次实现YoY正增长，复苏趋势初步确立；其二，AI数据中心电源芯片营收QoQ暴涨+30%，大幅超越管理层"高十几"的指引，该业务2026年有望翻倍。

**核心财务数据**
营收：$1.51B，超预期 $1.49B（+1.3%超预期）
毛利率：38.5%（基本符合预期 38.6%）
EPS：$0.64，超预期 $0.62（+3.2%超预期）

**业务分部**
汽车：$797M（七季度来首次YoY增长）
工业：$417M（超高盛/市场预期）
AI数据中心：QoQ +30%（vs 管理层指引"高十几"）

**Q2指引**
营收：$1.59B vs 市场预期 $1.53B（+4%超预期）
EPS中值：$0.71 vs 市场预期 $0.66（+8%超预期）
产能利用率：持平至上升（每+1%利用率带来+25–30bps毛利率）

**分析师观点**
高盛维持中性评级，目标价从 $60 上调至 $80。

*仅供社区讨论，不构成投资建议。*
"""

BRIEF_SYSTEM = f"""你是投资社区的财报简报分析师，为中文散户投资者撰写财报简报。
用中文写作，所有股票代码、财务数字、金融专业术语（YoY/QoQ/bps/EPS/PT等）保留英文原格式。
价格数据必须来自研报或提供的Tiger实时数据，严禁虚构任何数字。

严格按照以下格式输出（参考示例）：
{BRIEF_EXAMPLE}

格式规则：
1. 第一行（大标题）："英文公司全名 (TICKER)  (投行 中文评级 / English rating，目标价 $PT，前目标价 $旧PT — 上调/下调 ±X%)"
   - 如研报无明确前目标价，则写"目标价 $PT（新）"
   - 如研报无评级变动（维持），则写"维持评级"，不写上调/下调
   - 若研报无评级或标注"未予评级/Not Rated"，不得写"未评级"等负面表述；改为用第三行的中文叙述标题替代，格式："英文公司全名 (TICKER)  (投行 — [核心主题短语，如 GPU云收入+184% YoY·AI占比过半])"
   - 若为前瞻/策略类研报（无目标价），同上，用核心主题短语替代评级，不写"未予评级"
   - 【多家投行合并简报】若本篇整合了多份研报，第一行格式改为：
     "英文公司全名 (TICKER)  (投行A Rating $PT / 投行B Rating $PT / 投行C Rating $PT)"
     每家投行用" / "分隔，按目标价从高到低排列
2. 空行
3. 第三行（中文叙述标题）："公司中文名：[点出核心故事的一句话主题，含涨跌幅或关键数字]"
4. 空行
5. "$公司中文名(TICKER)$" + 一句描述股价表现的中文句子。
   若提供了Tiger价格数据，在同一行末尾附上，完整保留不修改。
   📈 收涨 / 📉 收跌 / 🚀 大涨（≥5%）
6. 空行
7. 一句话概述市场对财报/研报的整体反应
8. 空行
9. 叙述段落（2–3句）：报告中被市场低估的关键信号，有洞察力而非堆砌数据
10. 空行
11. **核心财务数据** — 营收（实际 vs 预期 + 超/低预期%）、毛利率、EPS
12. **业务分部** — 各主要业务亮点数据
13. **Q2/全年指引** — 营收、EPS，以及毛利率或关键经营指标
14. **分析师观点** — 评级、目标价变动、机构名称
    - 【多家投行合并简报】若本篇整合多份研报：
      主要来源的投行正常展开（评级+目标价变动+核心判断1句）；
      非主要来源的投行只需列出：机构名 + 评级 + 目标价，一行带过即可；
      确保本篇用到的所有投行 PT 全部出现，不得遗漏任何一家
15. 最后一行：*仅供社区讨论，不构成投资建议。*
16. 所有数字严格按照来源保留，不得修改
17. 【专有名词必须用官方正式名称，禁止音译】公司的官方中文名称，以及研报中提及的
    产品/项目/计划/战略/平台名称，必须使用官方正式中文名称，严禁音译（绝不可写成拼音）
    或自行臆造译名。例：Marvell 官方中文名为「迈威尔科技」，不可写成「马威科技」。
    若无法确定官方中文名，则保留英文/原文原名，依然不得音译。
    （名称的最终校正由 name_glossary.json 词典在生成后强制执行，见项目维护规则。）"""


# ── Helpers ───────────────────────────────────────────────────────────

def get_client() -> anthropic.Anthropic:
    key      = os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")
    base_url = os.getenv("ANTHROPIC_BASE_URL")
    if not key:
        sys.exit("\nError: set ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN\n")
    kwargs = {"api_key": key, "timeout": 300.0, "max_retries": 5}
    if base_url:
        kwargs["base_url"] = base_url
    return anthropic.Anthropic(**kwargs)


# Server-side web search tool — lets the model verify official company / project
# names instead of transliterating or inventing them (see BRIEF_SYSTEM rule 17).
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}


def _final_text(resp) -> str:
    """Extract the brief from a response that may include web_search tool blocks.

    With server-side web search the content list interleaves text / server_tool_use /
    web_search_tool_result blocks. The brief is the text emitted AFTER the last tool
    result; fall back to all text blocks when no search was performed.
    """
    blocks = list(resp.content)
    last_tool = -1
    for i, b in enumerate(blocks):
        if getattr(b, "type", "") in ("server_tool_use", "web_search_tool_result", "tool_use"):
            last_tool = i
    texts = [b.text for b in blocks[last_tool + 1:] if getattr(b, "type", "") == "text"]
    if not texts:
        texts = [b.text for b in blocks if getattr(b, "type", "") == "text"]
    return "".join(texts).strip()


_BANKS = {'JPM', 'GS', 'MS', 'CITI', 'UBS', 'BARC', 'CS', 'DB', 'RBC', 'TD', 'HSBC', 'WOLFE'}

def extract_ticker(path: str) -> str:
    """Best-effort ticker from filename; refined by extract_ticker_from_brief() after generation."""
    stem   = Path(path).stem
    m      = re.search(r'brief_([A-Z]{2,6})', stem)
    if m:
        return m.group(1)
    tokens = re.split(r'[_\-\s]+', stem)
    for tok in tokens:
        upper = tok.upper()
        if upper in _BANKS:
            continue
        if re.match(r'^[A-Z]{2,6}$', upper):
            return upper
    return stem[:8].upper()


def extract_ticker_from_brief(brief: str):
    """Pull ticker from '$CompanyName(TICKER)$' pattern."""
    m = re.search(r'\$[^(]+\(([A-Z0-9]{1,6}(?:\.[A-Z]{1,3})?)\)', brief)
    return m.group(1) if m else None


def ticker_to_slug(ticker: str) -> str:
    return ticker.lower().replace('.', '_')


def extract_date(path: str) -> str:
    m = re.match(r'(\d{4}-\d{2}-\d{2})', Path(path).name)
    return m.group(1) if m else datetime.today().strftime('%Y-%m-%d')


def _is_price_fresh(display: str) -> bool:
    """Always trust the freshly fetched price in market_data.json.

    The cache's age is already guarded by preflight_check() (file mtime), and
    fetch_prices.py is run immediately before each session. The
    [数据截至 MM/DD] tag only reflects the last market close — markets are shut
    overnight, so that price is STILL the latest available. Comparing it
    against the local calendar date wrongly dropped valid overnight data and
    forced briefs back onto the research report's stale price (the FUTU bug
    class). Use the latest fetched price, always — never compare to local date.
    """
    return True


def _get_price_display(ticker: str, cached: dict) -> str:
    """Return Tiger display string. Priority: exact cache → base-ticker cache → live fallback → empty."""
    if ticker and ticker in cached:
        display = cached[ticker].get("display", "")
        if display and _is_price_fresh(display):
            return display
    # Strip exchange suffix (e.g. KC.O → KC) so US tickers resolved with a
    # ".O"/".N" suffix from the brief still match the cache key from fetch_prices.
    base = ticker.split('.')[0] if ticker else ticker
    if base and base != ticker and base in cached:
        display = cached[base].get("display", "")
        if display and _is_price_fresh(display):
            return display
    if ticker and _PRICES_OK:
        d = _fp.fetch_one(ticker)
        if d:
            display = d.get("display", "")
            if display and _is_price_fresh(display):
                return display
    return ""


def apply_name_glossary(brief: str) -> tuple:
    """Enforce official company / project names via name_glossary.json.

    The API gateway does not expose a web_search tool, so names cannot be verified
    live during generation. Instead, an operator-maintained glossary of verified
    names (company official Chinese names, project/program names) is applied as a
    post-generation string replacement. Returns (corrected_brief, [applied terms]).

    Glossary format:
      {"replacements": {"马威科技": "美满电子科技", "新品木": "新拼姆"}}
    Add a new entry whenever a brief mistranslates or transliterates a proper noun.
    """
    gpath = BASE / "name_glossary.json"
    if not gpath.exists():
        return brief, []
    try:
        g = json.loads(gpath.read_text(encoding="utf-8"))
    except Exception:
        return brief, []
    applied = []
    for wrong, right in g.get("replacements", {}).items():
        if wrong and wrong in brief:
            brief = brief.replace(wrong, right)
            applied.append(f"{wrong}→{right}")
    return brief, applied


def inject_price_into_brief(brief: str, display: str) -> str:
    """Post-generation: replace the price section on the $Company(TICKER)$ line
    with accurate Tiger real-time data, regardless of what the research report cited.
    """
    if not display:
        return brief
    lines = brief.split('\n')
    for i, line in enumerate(lines):
        if re.search(r'\$[^(]+\([A-Z0-9]{1,6}(?:\.[A-Z]{1,2})?\)\$', line):
            clean = re.sub(r'\s*[📈📉🚀].*$',              '', line)
            clean = re.sub(r'\s*Closed\s+\$[\d,.]+.*$',   '', clean)
            clean = re.sub(r'[，,]\s*报告日收盘价[^。\n]*', '', clean)
            clean = re.sub(r'\s*US\$[\d,.]+[^。\n]*$',     '', clean)
            clean = clean.rstrip('，。 \t')
            lines[i] = f"{clean} {display}"
            break
    return '\n'.join(lines)



def preflight_check(cached_prices: dict) -> None:
    """Warn and optionally abort if market_data.json is missing or stale.

    Multi-ticker reports: if a report covers AMD + INTC, include both when running
    fetch_prices.py — each ticker must be in the cache to get price display injected.
    If a ticker is absent, price display is silently omitted (not an error).
    """
    import time as _t
    cache_path = BASE / "market_data.json"

    if not cache_path.exists() or not cached_prices:
        print("\n" + "─" * 52)
        print("⛔  PRE-FLIGHT: market_data.json 未找到或为空")
        print("    请先运行: python3 fetch_prices.py TICKER1 TICKER2 ...")
        print("    若研报涉及多个标的，把每个 ticker 都列上")
        print("─" * 52)
        ans = input("    跳过行情数据继续运行? [y/N] ").strip().lower()
        if ans != "y":
            sys.exit("已中止。请先运行 fetch_prices.py")
        return

    age_h = (_t.time() - cache_path.stat().st_mtime) / 3600
    tickers_str = "  ".join(sorted(cached_prices))

    if age_h > 20:
        print("\n" + "─" * 52)
        print(f"⚠️   PRE-FLIGHT: 行情缓存已 {age_h:.0f}h 未更新（可能含昨日数据）")
        print(f"    已缓存标的: {tickers_str}")
        print(f"    建议重跑:   python3 fetch_prices.py {tickers_str}")
        print("    若有新增标的，把它们也加到命令里")
        print("─" * 52)
        ans = input("    使用旧缓存继续? [y/N] ").strip().lower()
        if ans != "y":
            sys.exit("已中止。请先运行 fetch_prices.py")
    else:
        print(f"✓  行情缓存: {tickers_str}  （{age_h:.1f}h 前更新）")


def call(client: anthropic.Anthropic, system: str, user: str, max_tokens: int) -> str:
    resp = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
    )
    return _final_text(resp)


def generate_brief(content: str, client: anthropic.Anthropic,
                   pdf_path: str = None, price_ctx: str = "") -> str:
    """Generate a brief from research content.

    For PDFs: tries Claude's native PDF API first. If that fails (e.g. broken
    structure), falls back to preprocess_pdfs text cache or fresh pdftotext.
    """
    price_note = (
        f"\n\n⚠️ REAL-TIME PRICE (Tiger Brokers — 必须原封不动用在 $TICKER$ 行末):\n"
        f"{price_ctx}\n严禁使用研报内的历史价格。实时数据优先级最高。"
    ) if price_ctx else ""

    if pdf_path:
        try:
            pdf_b64 = base64.standard_b64encode(Path(pdf_path).read_bytes()).decode()
            resp = client.messages.create(
                model=MODEL, max_tokens=2400,
                system=[{"type": "text", "text": BRIEF_SYSTEM,
                         "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": [
                    {"type": "document",
                     "source": {"type": "base64", "media_type": "application/pdf",
                                "data": pdf_b64}},
                    {"type": "text",
                     "text": f"Generate a brief from this research report.{price_note}"}
                ]}],
            )
            return _final_text(resp)
        except Exception as e:
            # Claude rejected the PDF — fall back to extracted text
            print(f"   ⚠ PDF API rejected ({e.__class__.__name__}), trying text fallback...")
            fallback = (_pp.get_text(pdf_path) if _PDF_CACHE_OK else "")
            if not fallback.strip():
                raise RuntimeError(
                    f"PDF unreadable by both Claude API and pdftotext.\n"
                    f"Run: python3 preprocess_pdfs.py  (requires: brew install poppler)"
                )
            content = fallback[:18000]

    return call(client, BRIEF_SYSTEM,
                f"Generate a brief from this research content:{price_note}\n\n{content}", 2400)


# ── Collection (multi-ticker) reports ─────────────────────────────────
# Conference recaps / sector roundups cover several tickers. Declare each in
# collections.json; the brief then lists EVERY declared ticker with its own
# Tiger price + the bank's view, and generate_posters.py auto-renders a modular
# collection poster (it treats any brief with ≥3 $Name(TICKER)$ lines as one).
# Operator still fetches those tickers first (python3 fetch_prices.py SNOW CRWV ...).
#   collections.json:
#   {"collections": [
#     {"match": "Jefferies", "source": "Jefferies",
#      "title": "软件 · 互联网 · AI 大会回顾",
#      "tickers": ["SNOW", "CRWV", "TEAM", "PCOR"]}
#   ]}
# match = substring of the input filename that flags it as this collection.

def load_collections() -> list:
    cpath = BASE / "collections.json"
    if not cpath.exists():
        return []
    try:
        return json.loads(cpath.read_text(encoding="utf-8")).get("collections", [])
    except Exception:
        return []


def match_collection(path: str, collections: list):
    name = Path(path).name
    for c in collections:
        if c.get("match") and c["match"] in name:
            return c
    return None


def generate_collection_brief(fp: str, entry: dict, cached_prices: dict,
                              client: anthropic.Anthropic) -> str:
    """Generate a multi-ticker collection brief: each declared ticker gets its
    own $Name(TICKER)$ line carrying its Tiger price + the bank's view on it."""
    tickers = entry.get("tickers", [])
    price_block = "\n".join(
        f"{t}: {_get_price_display(t, cached_prices) or '(无行情)'}" for t in tickers
    )
    source, title = entry.get("source", ""), entry.get("title", "")
    header_tickers = " · ".join(tickers)

    instruction = f"""这是一份{source}的多标的研报（会议综述/行业横评），覆盖多家公司。
请生成一篇【多标的合集简报】，重点覆盖以下标的：{'、'.join(tickers)}。

格式要求（区别于单公司财报简报）：
1. 第一行大标题：「{source} {title} ({header_tickers})」
2. 空行
3. 第三行中文叙述标题：一句话点出该研报核心结论
4. 空行
5. 一段总览（2-3句）：整体基调与被低估的关键信号
6. 然后为每个标的各写一个小节，格式：
   「**$公司中文名(TICKER)$** + 该公司在本报告中的核心看点（1-2句）」
   并在该公司名所在行末尾，原封不动附上下面提供的对应实时价格字符串。
7. 最后一行：*仅供社区讨论，不构成投资建议。*

各标的 Tiger 实时价格（必须原封不动分别用在各自公司行末，严禁改动或编造）：
{price_block}

严禁使用研报内的历史价格；公司中文名用官方名称，禁止音译。最终只输出简报正文。"""

    if fp.lower().endswith(".pdf"):
        pdf_b64 = base64.standard_b64encode(Path(fp).read_bytes()).decode()
        resp = client.messages.create(
            model=MODEL, max_tokens=2400,
            system=[{"type": "text", "text": BRIEF_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": [
                {"type": "document", "source": {"type": "base64",
                 "media_type": "application/pdf", "data": pdf_b64}},
                {"type": "text", "text": instruction},
            ]}],
        )
        brief = _final_text(resp)
    else:
        text = Path(fp).read_text(encoding="utf-8")
        brief = call(client, BRIEF_SYSTEM, f"{instruction}\n\n研报正文：\n{text}", 2400)

    brief, _ = apply_name_glossary(brief)
    return brief


# ── Main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Earnings Season Workflow — Step 2: brief generation")
    args = parser.parse_args()

    OUTPUT.mkdir(exist_ok=True)

    files = sorted(
        glob.glob(str(INPUT / "*.md")) +
        glob.glob(str(INPUT / "*.pdf"))
    )
    if not files:
        sys.exit(f"No files found in {INPUT}")

    client = get_client()
    today  = datetime.today().strftime('%Y-%m-%d')
    briefs = []
    ok, fail = 0, 0

    # Load pre-fetched price cache + pre-flight check
    cached_prices = _fp.load() if _PRICES_OK else {}
    preflight_check(cached_prices)
    collections = load_collections()

    print(f"\nEarnings Workflow  —  {today}")
    print(f"Input:  {INPUT}   Files: {len(files)}\n{'─'*50}")

    for fp in files:
        ticker = extract_ticker(fp)
        fdate  = extract_date(fp)
        print(f"\n▶  {Path(fp).name}")

        is_pdf  = fp.lower().endswith('.pdf')
        content = "" if is_pdf else Path(fp).read_text(encoding='utf-8')
        coll_entry = match_collection(fp, collections)

        # Brief generation
        try:
            if coll_entry:
                # Multi-ticker collection report → list every declared ticker w/ its price
                print(f"   ◧ 合集型 → {'、'.join(coll_entry.get('tickers', []))}")
                brief = generate_collection_brief(fp, coll_entry, cached_prices, client)
            else:
                # Pass 1 price hint (ticker may be wrong from filename for Chinese PDFs)
                price_ctx = _get_price_display(ticker, cached_prices)
                if price_ctx:
                    print(f"   📊 {price_ctx}")

                brief = generate_brief(content, client,
                                       pdf_path=fp if is_pdf else None,
                                       price_ctx=price_ctx)

                # Pass 2: re-resolve ticker from brief, inject accurate price
                refined = extract_ticker_from_brief(brief)
                if refined:
                    ticker        = refined
                    final_display = _get_price_display(ticker, cached_prices)
                    if final_display:
                        brief = inject_price_into_brief(brief, final_display)
                        print(f"   💉 {final_display}")

                # Enforce verified official names (company / project) via glossary
                brief, applied = apply_name_glossary(brief)
                if applied:
                    print(f"   📝 名称校正: {', '.join(applied)}")

            print(f"   ✓ brief  [{ticker}]")
            ok += 1
        except Exception as e:
            print(f"   ✗ brief failed: {e}")
            fail += 1
            briefs.append("")
            continue
        briefs.append(brief)


    # Save combined brief file
    if briefs:
        out = OUTPUT / f"{today}_briefs.md"
        out.write_text(
            f"# Earnings Briefs — {today}\n\n---\n\n" + "\n\n---\n\n".join(briefs),
            encoding='utf-8',
        )
        print(f"\n{'─'*50}\n✓  {out.name}")

    print(f"\nDone  ✓{ok}  {'✗' + str(fail) if fail else ''}\n")


if __name__ == "__main__":
    main()
