"""Fetch and clean real pages to check the text quality.

    python try_fetch.py URL [URL ...]
"""
import sys

from app.services.page_fetcher import fetch_page

sys.stdout.reconfigure(encoding="utf-8")

for url in sys.argv[1:]:
    r = fetch_page(url)
    print("=" * 80)
    print(url)
    if not r.ok:
        print("FAILED:", r.error)
        continue
    print(f"OK, {len(r.text)} chars\n")
    print(r.text[:1500])