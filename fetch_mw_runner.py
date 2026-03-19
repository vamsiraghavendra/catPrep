"""
Standalone runner for fetch_saved_words_from_mw.
Runs in a separate process to avoid asyncio/event loop conflicts
when called from Streamlit on Windows.
Usage: python fetch_mw_runner.py
Reads MW_EMAIL and MW_PASSWORD from environment, prints JSON to stdout.
"""

import json
import os
import sys


def main():
    email = os.environ.get("MW_EMAIL", "").strip()
    password = os.environ.get("MW_PASSWORD", "").strip()
    if not email or not password:
        print(json.dumps({"error": "MW_EMAIL and MW_PASSWORD environment variables required"}))
        sys.exit(1)

    try:
        from merriamCode import fetch_saved_words_from_mw

        words, err = fetch_saved_words_from_mw(email=email, password=password, headless=True)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

    if err:
        print(json.dumps({"error": err}))
        sys.exit(1)

    print(json.dumps({"words": words}))


if __name__ == "__main__":
    main()
