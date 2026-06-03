#!/usr/bin/env python3
"""
preprocess_pdfs.py — Step 2: PDF text extraction cache

Scans 研报input/ for PDFs and extracts plain text using pdftotext,
saving sidecar .txt files to 研报input/.cache/.

Why this exists
───────────────
Some research PDFs have broken internal object trees or non-standard encodings
that cause the Claude API to reject them ("PDF not valid"). Pre-extracting text
lets run_workflow.py fall back to the text route automatically, so generation
never hard-fails on a bad PDF.

run_workflow.py calls get_text(pdf_path) which reads from this cache.

Usage
─────
  python3 preprocess_pdfs.py            # extract all PDFs in 研报input/
  python3 preprocess_pdfs.py --force    # re-extract even if cache exists
  python3 preprocess_pdfs.py --show     # print cache status
  python3 preprocess_pdfs.py --clear    # delete all cached .txt files
"""

import sys, subprocess, glob, argparse
from pathlib import Path

BASE  = Path.home() / "Desktop/earnings season"
INPUT = BASE / "研报input"
CACHE = INPUT / ".cache"


# ── Core extraction ──────────────────────────────────────────────────

def extract_text(pdf_path: str) -> str:
    """Extract text from a PDF using pdftotext (Latin1 output, UTF-8 safe decode).

    Returns the extracted string, or empty string if pdftotext fails.
    Requires poppler: brew install poppler
    """
    result = subprocess.run(
        ["pdftotext", "-enc", "Latin1", pdf_path, "-"],
        capture_output=True,
    )
    if result.returncode != 0 or not result.stdout:
        return ""
    # Decode as latin-1 (what pdftotext -enc Latin1 produces)
    return result.stdout.decode("latin-1", errors="replace").strip()


def get_text(pdf_path: str) -> str:
    """Return text for a PDF: reads cache if available, extracts fresh if not.

    This is the entry point used by run_workflow.py.
    Returns empty string if extraction fails (caller decides how to handle).
    """
    CACHE.mkdir(exist_ok=True)
    cache_file = CACHE / (Path(pdf_path).stem + ".txt")
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8")
    text = extract_text(pdf_path)
    if text:
        cache_file.write_text(text, encoding="utf-8")
    return text


# ── Batch processing ─────────────────────────────────────────────────

def process_all(force: bool = False) -> dict:
    """Extract text for every PDF in INPUT. Returns {filename: status}."""
    CACHE.mkdir(exist_ok=True)
    pdfs = sorted(glob.glob(str(INPUT / "*.pdf")))
    if not pdfs:
        print(f"No PDFs found in {INPUT}")
        return {}

    print(f"\nPreprocessing {len(pdfs)} PDF(s)  →  {CACHE}\n")
    results = {}
    for pdf_path in pdfs:
        name       = Path(pdf_path).name
        cache_file = CACHE / (Path(pdf_path).stem + ".txt")

        if cache_file.exists() and not force:
            size = len(cache_file.read_text(encoding="utf-8"))
            print(f"  ⓘ  cached   {name[:60]}  [{size:,} chars]")
            results[name] = "cached"
            continue

        print(f"  ⟳  {name[:60]} ...", end=" ", flush=True)
        text = extract_text(pdf_path)
        if text:
            cache_file.write_text(text, encoding="utf-8")
            print(f"✓  {len(text):,} chars")
            results[name] = "ok"
        else:
            print("✗  failed (check pdftotext is installed: brew install poppler)")
            results[name] = "failed"

    ok     = sum(1 for v in results.values() if v in ("ok", "cached"))
    failed = sum(1 for v in results.values() if v == "failed")
    print(f"\n{'─'*50}")
    print(f"✓ {ok} ready   {'✗ ' + str(failed) + ' failed' if failed else ''}\n")
    return results


# ── CLI ──────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="PDF text extraction cache for earnings workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 preprocess_pdfs.py           # extract all\n"
            "  python3 preprocess_pdfs.py --force   # re-extract all\n"
            "  python3 preprocess_pdfs.py --show    # cache status\n"
            "  python3 preprocess_pdfs.py --clear   # wipe cache\n"
        ),
    )
    ap.add_argument("--show",  action="store_true", help="Print cache status and exit")
    ap.add_argument("--clear", action="store_true", help="Delete all cached .txt files")
    ap.add_argument("--force", action="store_true", help="Re-extract even if cache exists")
    args = ap.parse_args()

    if args.clear:
        if CACHE.exists():
            removed = list(CACHE.glob("*.txt"))
            for f in removed:
                f.unlink()
            print(f"Cleared {len(removed)} cached file(s) from {CACHE}")
        else:
            print("Cache directory does not exist — nothing to clear.")
        return

    if args.show:
        txt_files = sorted(CACHE.glob("*.txt")) if CACHE.exists() else []
        if not txt_files:
            print("Cache is empty. Run: python3 preprocess_pdfs.py")
            return
        print(f"\nCache contents ({CACHE}):\n")
        for f in txt_files:
            size = len(f.read_text(encoding="utf-8"))
            print(f"  {f.stem[:60]:<60}  {size:>9,} chars")
        print()
        return

    process_all(force=args.force)


if __name__ == "__main__":
    main()
