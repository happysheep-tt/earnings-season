#!/usr/bin/env python3
"""
fetch_prices.py — Step 1: real-time Tiger price fetcher

Fetches quotes from Tiger Brokers for explicitly-specified tickers and writes
market_data.json. Run this BEFORE run_workflow.py so price injection is accurate.

Usage
─────
  python3 fetch_prices.py APP U COST FUTU NVDA MCD
  python3 fetch_prices.py APP U COST FUTU NVDA MCD --hk 01810 09988
  python3 fetch_prices.py --show      # print cached market_data.json
  python3 fetch_prices.py --show --verbose

Why separate from run_workflow.py
──────────────────────────────────
Tickers can only be reliably extracted AFTER Claude reads the research PDF.
By that point the brief is already written — too late to inject a live price.
This script is run manually with explicit tickers so prices are pre-loaded
into market_data.json before any brief generation starts.
"""

import os, json, sys, argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta

BASE         = Path.home() / "Desktop/earnings season"
TIGER_CONFIG = os.getenv(
    "TIGER_CONFIG_PATH",
    str(Path.home() / "Desktop/stock-daily-2/tiger_openapi_config.properties"),
)
DATA_FILE = BASE / "market_data.json"
EDT       = timezone(timedelta(hours=-4))


# ── Internal helpers ─────────────────────────────────────────────────

def _tiger_sym(ticker: str) -> str:
    """HK digit tickers → zero-padded 5-char; strip .HK suffix."""
    t = ticker.replace(".HK", "").replace(".hk", "")
    return t.zfill(5) if t.isdigit() else t


def _build_display(close: float, prev_close: float, pct: float,
                   ext_price: float = None, ext_pct: float = None,
                   ext_tag: str = None, ext_time: str = None,
                   fetch_time: str = None) -> str:
    """Build the Chinese display string embedded in briefs, e.g.:
       '📈 收涨 $144.89 (-13.8%，前收 $168.00) [数据截至 05/09 16:00 EDT] | After-Hrs 盘后: $145.20 (+0.21%) [17:32 EDT]'
    """
    emoji  = "🚀" if pct >= 5 else ("📈" if pct > 0 else "📉")
    action = "大涨" if pct >= 5 else ("收涨" if pct > 0 else "收跌")
    time_label = f" [数据截至 {fetch_time}]" if fetch_time else ""
    s = f"{emoji} {action} ${close:,.2f} ({pct:+.1f}%，前收 ${prev_close:,.2f}){time_label}"
    if ext_price and ext_pct is not None and ext_tag:
        time_part = f" [{ext_time}]" if ext_time else ""
        s += f" | {ext_tag}: ${ext_price:,.2f} ({ext_pct:+.2f}%){time_part}"
    return s


def _session_tag() -> str:
    now = datetime.now(EDT)
    h, m = now.hour, now.minute
    if 4 <= h < 9 or (h == 9 and m < 30):
        return "Pre-Mkt 盘前"
    if h >= 16:
        return "After-Hrs 盘后"
    return "After-Hrs 盘后"  # default for overnight


# ── Public API ───────────────────────────────────────────────────────

def fetch_one(ticker: str):
    """Fetch real-time quote for a single ticker.

    Returns a dict with keys: ticker, close, prev_close, pct_change, display,
    and optionally: ext_price, ext_pct, ext_tag, ext_time.
    Returns None on any failure.
    """
    if not Path(TIGER_CONFIG).exists():
        print(f"  ⚠  Tiger config not found: {TIGER_CONFIG}", file=sys.stderr)
        return None
    try:
        from tigeropen.tiger_open_config import TigerOpenClientConfig
        from tigeropen.quote.quote_client import QuoteClient

        cfg    = TigerOpenClientConfig(props_path=TIGER_CONFIG)
        client = QuoteClient(cfg)
        tsym   = _tiger_sym(ticker)

        df = client.get_stock_briefs([tsym], include_hour_trading=True)
        if df is None or df.empty:
            return None
        row        = df.iloc[0]
        close      = float(row.get("latest_price") or 0)
        prev_close = float(row.get("pre_close")    or 0)
        if close <= 0 or prev_close <= 0:
            return None
        pct = (close - prev_close) / prev_close * 100

        result: dict = dict(
            ticker     = ticker,
            close      = close,
            prev_close = prev_close,
            pct_change = round(pct, 2),
        )

        # Extended-hours data (US stocks only)
        is_us = not ticker.replace(".HK", "").replace(".hk", "").isdigit()
        if is_us:
            # Primary: hour_trading_* fields from get_stock_briefs(include_hour_trading=True).
            # These reliably carry the live pre-/post-market move (e.g. an earnings pop),
            # which get_quote_overnight often misses during the pre-market session.
            ht_px  = float(row.get("hour_trading_latest_price") or 0)
            ht_rate = row.get("hour_trading_change_rate")
            ht_tag = str(row.get("hour_trading_tag") or "")
            ht_ts  = str(row.get("hour_trading_latest_time") or "")
            if ht_px > 0 and ht_rate is not None:
                tag = "Pre-Mkt 盘前" if "pre" in ht_tag.lower() else "After-Hrs 盘后"
                result.update(
                    ext_price = ht_px,
                    ext_pct   = round(float(ht_rate) * 100, 2),
                    ext_tag   = tag,
                    ext_time  = ht_ts,
                )
            else:
                try:
                    df2 = client.get_quote_overnight([tsym])
                    if df2 is not None and not df2.empty:
                        r2    = df2.iloc[0]
                        oh_px = float(r2.get("latest_price") or 0)
                        oh_ts = str(r2.get("latest_time", ""))
                        if oh_px > 0:
                            oh_pct = (oh_px - close) / close * 100
                            result.update(
                                ext_price = oh_px,
                                ext_pct   = round(oh_pct, 2),
                                ext_tag   = _session_tag(),
                                ext_time  = oh_ts,
                            )
                except Exception:
                    pass

        fetch_time = datetime.now(EDT).strftime("%m/%d %H:%M EDT")
        result["display"] = _build_display(
            close, prev_close, pct,
            result.get("ext_price"), result.get("ext_pct"),
            result.get("ext_tag"),   result.get("ext_time"),
            fetch_time=fetch_time,
        )
        return result

    except Exception as e:
        print(f"  ✗  {ticker}: {e}", file=sys.stderr)
        return None


def fetch_all(tickers: list) -> dict:
    """Fetch multiple tickers; returns {ticker: data_dict}."""
    results = {}
    for t in tickers:
        print(f"  ⟳  {t:<10}", end=" ", flush=True)
        d = fetch_one(t)
        if d:
            results[t] = d
            print(d["display"])
        else:
            print("no data")
    return results


def load(path: Path = DATA_FILE) -> dict:
    """Load cached market_data.json → {ticker: data_dict}. Empty dict on miss."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("prices", {})
    except Exception:
        return {}


def save(prices: dict, path: Path = DATA_FILE):
    """Write prices dict to market_data.json."""
    path.write_text(
        json.dumps(
            {"fetched_at": datetime.now(EDT).isoformat(), "prices": prices},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n✓  {len(prices)} tickers saved → {path.name}")


# ── CLI ──────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Fetch Tiger real-time prices → market_data.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 fetch_prices.py APP U COST FUTU NVDA MCD\n"
            "  python3 fetch_prices.py APP NVDA --hk 01810 09988\n"
            "  python3 fetch_prices.py --show\n"
        ),
    )
    ap.add_argument("tickers", nargs="*", help="US/non-HK ticker symbols (e.g. APP NVDA FUTU)")
    ap.add_argument("--hk",   nargs="*", default=[], metavar="SYM",
                    help="HK stock codes, digits only (e.g. 01810 09988)")
    ap.add_argument("--show",    action="store_true", help="Print cached prices and exit")
    ap.add_argument("--verbose", action="store_true", help="Show full dict per ticker with --show")
    args = ap.parse_args()

    if args.show:
        prices = load()
        if not prices:
            print("No cached prices. Run: python3 fetch_prices.py <TICKERS>")
            return
        try:
            raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            print(f"\nCached prices (fetched {raw.get('fetched_at','')})\n")
        except Exception:
            print("\nCached prices:\n")
        for t, d in prices.items():
            print(f"  {t:<10}  {d['display']}")
            if args.verbose:
                for k, v in d.items():
                    if k not in ("ticker", "display"):
                        print(f"             {k}: {v}")
        return

    all_tickers = [t.upper() for t in args.tickers] + list(args.hk)
    if not all_tickers:
        ap.print_help()
        print("\n⚠  No tickers specified.")
        sys.exit(0)

    print(f"\nFetching {len(all_tickers)} ticker(s) from Tiger Brokers...\n")
    existing = load()
    fresh    = fetch_all(all_tickers)
    save({**existing, **fresh})   # fresh values overwrite stale cached ones


if __name__ == "__main__":
    main()
