"""
Fast concurrent ESCO fetcher. Processes multiple ISCO codes in parallel.
Writes results incrementally to data/esco/occupations_full.json.

Usage:
    uv run python fetch_esco_fast.py
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

API_BASE = "https://ec.europa.eu/esco/api"
LANGUAGE = "en"
OUTPUT_DIR = Path(__file__).parent / "data" / "esco"
OUTPUT_FILE = OUTPUT_DIR / "occupations_full.json"

# Thread-safe write lock
write_lock = Lock()
all_occupations = []
processed_count = 0
total_codes = 0


def api_get(url, retries=3):
    """GET JSON from ESCO API with retries."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            if attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
            else:
                raise


def extract_en_text(field):
    """Extract English text from ESCO's multilingual fields."""
    if isinstance(field, str):
        return field
    if isinstance(field, dict):
        return field.get("en", field.get("en-us", str(field)))
    return str(field) if field else ""


def fetch_one_code(code):
    """Fetch all ESCO data for a single ISCO 4-digit code."""
    group_url = f"{API_BASE}/resource/concept?uri=http%3A%2F%2Fdata.europa.eu%2Fesco%2Fisco%2FC{code}&language={LANGUAGE}"

    try:
        group = api_get(group_url)
    except Exception:
        return code, []

    title = extract_en_text(group.get("title", ""))
    description = extract_en_text(group.get("description", ""))

    # Get narrower occupations
    links = group.get("_links", {})
    narrower = links.get("narrowerOccupation", [])
    if isinstance(narrower, dict):
        narrower = [narrower]

    if not narrower:
        return code, []

    occupations = []
    for link in narrower:
        occ_uri = link.get("uri", link.get("href", ""))
        if not occ_uri:
            continue

        occ_url = f"{API_BASE}/resource/occupation?uri={urllib.parse.quote(occ_uri, safe='')}&language={LANGUAGE}"
        try:
            occ = api_get(occ_url)
        except Exception:
            continue

        occ_title = extract_en_text(occ.get("title", ""))
        occ_desc = extract_en_text(occ.get("description", ""))
        occ_code = occ.get("code", "")

        # Extract alternative labels
        alt_labels = []
        for label in occ.get("alternativeLabel", {}).get("en", []):
            if isinstance(label, str):
                alt_labels.append(label)

        # Extract skills from _links
        occ_links = occ.get("_links", {})

        def extract_skills(relation_key):
            skills = []
            relations = occ_links.get(relation_key, [])
            if isinstance(relations, dict):
                relations = [relations]
            for rel in relations:
                skill_uri = rel.get("uri", rel.get("href", ""))
                skill_title = rel.get("title", "")
                skill_type = rel.get("skillType", "")
                if isinstance(skill_title, dict):
                    skill_title = skill_title.get("en", str(skill_title))
                skills.append({
                    "skill_uri": skill_uri,
                    "skill_title": skill_title,
                    "skill_type": skill_type,
                    "reuse_level": rel.get("skillReuseLevel", ""),
                })
            return skills

        essential_skills = extract_skills("hasEssentialSkill")
        essential_knowledge = extract_skills("hasEssentialKnowledge")
        optional_skills = extract_skills("hasOptionalSkill")
        optional_knowledge = extract_skills("hasOptionalKnowledge")

        occupations.append({
            "isco_code": code,
            "isco_group_title": title,
            "isco_group_description": description,
            "occupation_uri": occ_uri,
            "occupation_title": occ_title,
            "occupation_code": occ_code,
            "occupation_description": occ_desc,
            "alternative_labels": "; ".join(alt_labels),
            "essential_skills": essential_skills,
            "essential_knowledge": essential_knowledge,
            "optional_skills": optional_skills,
            "optional_knowledge": optional_knowledge,
        })

    return code, occupations


import urllib.parse


def main():
    global all_occupations, processed_count, total_codes

    # Load ISCO codes
    with open("data/occupations_4digit.json") as f:
        data = json.load(f)
    codes = sorted(o["code"] for o in data if o.get("employment"))
    total_codes = len(codes)

    print(f"Fetching ESCO data for {total_codes} ISCO codes (concurrent)...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Check for existing partial results
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE) as f:
            existing = json.load(f)
        existing_codes = {o["isco_code"] for o in existing}
        # Only keep test data if we're just starting
        if len(existing_codes) <= 12:
            all_occupations = []
            existing_codes = set()
        else:
            all_occupations = existing
        codes_to_fetch = [c for c in codes if c not in existing_codes]
        print(f"  Already have {len(existing_codes)} codes, fetching {len(codes_to_fetch)} remaining")
    else:
        codes_to_fetch = codes
        print(f"  Fetching all {len(codes_to_fetch)} codes")

    if not codes_to_fetch:
        print("All codes already fetched!")
        return

    errors = 0
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch_one_code, code): code for code in codes_to_fetch}

        for future in as_completed(futures):
            code = futures[future]
            processed_count += 1
            try:
                result_code, occupations = future.result()
                if occupations:
                    with write_lock:
                        all_occupations.extend(occupations)
                    print(f"  [{processed_count}/{len(codes_to_fetch)}] {code}: {len(occupations)} occupations")
                else:
                    print(f"  [{processed_count}/{len(codes_to_fetch)}] {code}: no data (404 or empty)")
            except Exception as e:
                errors += 1
                print(f"  [{processed_count}/{len(codes_to_fetch)}] {code}: ERROR {e}")

            # Save incrementally every 50 codes
            if processed_count % 50 == 0:
                with write_lock:
                    with open(OUTPUT_FILE, "w") as f:
                        json.dump(all_occupations, f, indent=2, ensure_ascii=False)
                    elapsed = time.time() - start_time
                    rate = processed_count / elapsed * 60
                    remaining = (len(codes_to_fetch) - processed_count) / rate if rate > 0 else 0
                    print(f"  --- Saved {len(all_occupations)} occupations ({rate:.0f} codes/min, ~{remaining:.0f} min remaining) ---")

    # Final save
    with open(OUTPUT_FILE, "w") as f:
        json.dump(all_occupations, f, indent=2, ensure_ascii=False)

    elapsed = time.time() - start_time
    isco_codes_found = len({o["isco_code"] for o in all_occupations})
    print(f"\nDone in {elapsed:.0f}s")
    print(f"  ISCO codes with data: {isco_codes_found}")
    print(f"  Total ESCO occupations: {len(all_occupations)}")
    print(f"  Errors: {errors}")
    print(f"  Saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
