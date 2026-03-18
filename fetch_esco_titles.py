"""
Fetch ESCO occupation titles for a specific language.

Lightweight alternative to fetch_esco_fast.py — only fetches titles,
not skills/knowledge/descriptions. Used to get French (or other) titles.

Usage:
    uv run python fetch_esco_titles.py --language fr
    uv run python fetch_esco_titles.py --language de
"""

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

API_BASE = "https://ec.europa.eu/esco/api"
OUTPUT_DIR = Path(__file__).parent / "data" / "esco"

write_lock = Lock()


def api_get(url, retries=3):
    """GET JSON from ESCO API with retries."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            if attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
            else:
                raise


def extract_text(field):
    """Extract text from ESCO's multilingual fields."""
    if isinstance(field, str):
        return field
    if isinstance(field, dict):
        for key in ("en", "fr", "de", "it"):
            if key in field:
                val = field[key]
                if isinstance(val, dict):
                    return val.get("literal", str(val))
                return val
        return str(field)
    return str(field) if field else ""


def fetch_title(code, language):
    """Fetch the ISCO group title for a single code in the given language."""
    uri = f"http://data.europa.eu/esco/isco/C{code}"
    url = f"{API_BASE}/resource/concept?uri={urllib.parse.quote(uri, safe='')}&language={language}"
    try:
        data = api_get(url)
        # The 'title' field is already in the requested language.
        # 'preferredLabel' is a multi-language dict — extract target language from it.
        title = data.get("title", "")
        if isinstance(title, str) and title:
            return code, title
        pref = data.get("preferredLabel", {})
        if isinstance(pref, dict) and language in pref:
            val = pref[language]
            if isinstance(val, dict):
                return code, val.get("literal", str(val))
            return code, val
        return code, extract_text(pref) if pref else None
    except Exception as e:
        return code, None


def main():
    parser = argparse.ArgumentParser(description="Fetch ESCO titles for a language")
    parser.add_argument("--language", required=True, help="Language code (fr, de, it, etc.)")
    args = parser.parse_args()
    lang = args.language

    # Load all codes (2-digit + 4-digit)
    with open("data/occupations_4digit.json") as f:
        codes_4d = sorted(o["code"] for o in json.load(f) if o.get("employment"))

    # Also get 2-digit codes
    with open("data/occupation_tree.json") as f:
        raw = json.load(f)
        tree = raw["occupations"] if isinstance(raw, dict) and "occupations" in raw else raw

    codes_2d = set()
    for major in tree:
        for node in major.get("children", []):
            if len(node["code"]) == 2:
                codes_2d.add(node["code"])

    all_codes = sorted(codes_2d) + codes_4d
    print(f"Fetching {len(all_codes)} ESCO titles in '{lang}'...")

    titles = {}
    errors = 0
    start_time = time.time()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / f"titles_{lang}.json"

    # Check for existing partial results
    if output_file.exists():
        with open(output_file) as f:
            titles = json.load(f)
        remaining = [c for c in all_codes if c not in titles]
        print(f"  Already have {len(titles)} titles, fetching {len(remaining)} remaining")
    else:
        remaining = all_codes

    if not remaining:
        print("All titles already fetched!")
        return

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch_title, code, lang): code for code in remaining}

        for i, future in enumerate(as_completed(futures), 1):
            code = futures[future]
            try:
                result_code, title = future.result()
                if title:
                    with write_lock:
                        titles[result_code] = title
                    if i % 50 == 0:
                        print(f"  [{i}/{len(remaining)}] ...")
                        with open(output_file, "w") as f:
                            json.dump(titles, f, indent=2, ensure_ascii=False)
                else:
                    errors += 1
                    print(f"  {code}: no title found")
            except Exception as e:
                errors += 1
                print(f"  {code}: ERROR {e}")

    # Final save
    with open(output_file, "w") as f:
        json.dump(titles, f, indent=2, ensure_ascii=False)

    elapsed = time.time() - start_time
    print(f"\nDone in {elapsed:.0f}s")
    print(f"  Titles fetched: {len(titles)}")
    print(f"  Errors: {errors}")
    print(f"  Saved to {output_file}")


if __name__ == "__main__":
    main()
