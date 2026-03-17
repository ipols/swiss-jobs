"""
Score all 4-digit Swiss occupations for AI exposure using Claude.

Uses the v2 prompt (prompt.md) with ESCO-enriched occupation data.
Produces two-tier rationale: short tooltip text + detailed analysis.

Incremental: saves after each occupation, skips already-scored codes.

Usage:
    uv run python score.py
    uv run python score.py --force           # Re-score all
    uv run python score.py --codes 7121 2512  # Score specific codes
    uv run python score.py --dry-run          # Show what would be scored
"""

import argparse
import json
import os
import time

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

SKILL_LEVEL_LABELS = {
    1: "No formal / primary education",
    2: "Upper secondary / apprenticeship",
    3: "Higher vocational / short-cycle tertiary",
    4: "Bachelor's degree or higher",
}

SCORES_FILE = "data/scores.json"


def load_data():
    """Load all required data sources."""
    with open("data/occupations_4digit.json") as f:
        se_data = {o["code"]: o for o in json.load(f)}

    with open("data/occupations.json") as f:
        wage_data = {o["code"]: o["wage_monthly"] for o in json.load(f)}

    esco_path = "data/esco/occupations_full.json"
    if os.path.exists(esco_path):
        with open(esco_path) as f:
            all_occs = json.load(f)
            esco_data = {}
            for o in all_occs:
                esco_data.setdefault(o["isco_code"], []).append(o)
    else:
        print("WARNING: ESCO data not found, scoring without enrichment")
        esco_data = {}

    return se_data, wage_data, esco_data


def _text(field):
    """Extract text from ESCO field (may be str or dict with 'literal' key)."""
    if isinstance(field, dict):
        return field.get("literal", field.get("en", str(field)))
    return str(field) if field else ""


def build_user_message(code, se_data, wage_data, esco_data):
    """Build the ESCO-enriched user message for one occupation."""
    occ = se_data.get(code)
    if not occ:
        return None

    msg = f"## {occ['title_de']} (ISCO {code})\n\n"
    msg += f"- **Employment in Switzerland:** {occ['employment']:,} workers\n"

    w = wage_data.get(code[:2])
    if w:
        msg += f"- **Median gross monthly wage:** CHF {w:,}\n"
    msg += f"- **Typical education level:** {SKILL_LEVEL_LABELS[occ['isco_skill_level']]}\n"

    esco_occs = esco_data.get(code, [])
    if esco_occs:
        d = _text(esco_occs[0].get("isco_group_description", ""))
        if d:
            msg += f"\n### ISCO-08 Official Description\n{d.strip()}\n"
        if len(esco_occs) > 1:
            msg += f"\n### ESCO Sub-occupations ({len(esco_occs)})\n"
            for eo in esco_occs:
                desc = _text(eo.get("occupation_description", ""))[:150]
                msg += f"- {eo['occupation_title']}: {desc}\n"

        es, ek, os_ = set(), set(), set()
        for eo in esco_occs:
            for s in eo.get("essential_skills", []):
                es.add(s["skill_title"])
            for s in eo.get("essential_knowledge", []):
                ek.add(s["skill_title"])
            for s in eo.get("optional_skills", []):
                os_.add(s["skill_title"])

        if es:
            msg += f"\n### Essential Skills ({len(es)})\n" + ", ".join(sorted(es)) + "\n"
        if ek:
            msg += f"\n### Essential Knowledge ({len(ek)})\n" + ", ".join(sorted(ek)) + "\n"
        if os_:
            ol = sorted(os_)[:25]
            msg += f"\n### Key Optional Skills (top {len(ol)} of {len(os_)})\n" + ", ".join(ol) + "\n"

    return msg


def load_scores():
    """Load existing scores for incremental processing."""
    if os.path.exists(SCORES_FILE):
        with open(SCORES_FILE) as f:
            return json.load(f)
    return []


def save_scores(scores):
    """Save scores to disk."""
    with open(SCORES_FILE, "w") as f:
        json.dump(scores, f, indent=2, ensure_ascii=False)


def score_one(client, model, system_prompt, user_msg):
    """Call Claude and parse the JSON response."""
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        temperature=0,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]

    result = json.loads(text.strip())
    return result


def main():
    parser = argparse.ArgumentParser(description="Score occupations with v2 prompt")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--force", action="store_true", help="Re-score all")
    parser.add_argument("--codes", nargs="*", help="Score specific ISCO codes")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be scored")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay between requests")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY not set")
        return

    se_data, wage_data, esco_data = load_data()
    system_prompt = open("prompt.md").read()

    # Determine which codes to score
    if args.codes:
        codes = args.codes
    else:
        # All 4-digit codes with employment data, sorted by code
        codes = sorted(code for code, occ in se_data.items() if occ.get("employment"))

    # Load existing scores
    scores = [] if args.force else load_scores()
    scored_codes = {s["code"] for s in scores}
    to_score = [c for c in codes if c not in scored_codes]

    print(f"Model: {args.model}")
    print(f"Total 4-digit codes with employment: {len(codes)}")
    print(f"Already scored: {len(scored_codes)}")
    print(f"To score: {len(to_score)}")
    print(f"ESCO coverage: {len(esco_data)} ISCO codes")

    if args.dry_run:
        for c in to_score[:20]:
            occ = se_data[c]
            has_esco = "+" if c in esco_data else "-"
            print(f"  {c} {occ['title_de'][:50]} (ESCO: {has_esco})")
        if len(to_score) > 20:
            print(f"  ... and {len(to_score) - 20} more")
        return

    if not to_score:
        print("Nothing to score!")
        return

    print("-" * 70)
    client = Anthropic()
    errors = 0

    for i, code in enumerate(to_score):
        occ = se_data[code]
        msg = build_user_message(code, se_data, wage_data, esco_data)
        if not msg:
            continue

        try:
            result = score_one(client, args.model, system_prompt, msg)
            scores.append({
                "code": code,
                "title": occ["title_de"],
                "exposure": int(result["exposure"]),
                "confidence": result.get("confidence", "medium"),
                "rationale": result["rationale"],
                "analysis": result.get("analysis", ""),
            })
            scored_codes.add(code)
            save_scores(scores)
            print(f"  [{i+1}/{len(to_score)}] {code} {occ['title_de'][:40]} — {result['exposure']}/10 ({result.get('confidence', '?')})")

        except Exception as e:
            errors += 1
            print(f"  [{i+1}/{len(to_score)}] {code} {occ['title_de'][:40]} — ERROR: {e}")
            if errors > 10:
                print("Too many errors, stopping.")
                break

        if i < len(to_score) - 1:
            time.sleep(args.delay)

    # Summary
    print("\n" + "=" * 70)
    exposures = [s.get("exposure") or s.get("v2_score") for s in scores]
    exposures = [e for e in exposures if e is not None]
    print(f"Scored {len(scores)} occupations total")
    print(f"Average exposure: {sum(exposures)/len(exposures):.1f}")
    print(f"Errors: {errors}")
    print(f"\nDistribution:")
    for name, lo, hi in [
        ("Minimal (0-1)", 0, 1), ("Low (2-3)", 2, 3), ("Moderate (4-5)", 4, 5),
        ("High (6-7)", 6, 7), ("Very High (8-9)", 8, 9), ("Maximum (10)", 10, 10),
    ]:
        count = sum(1 for e in exposures if lo <= e <= hi)
        jobs = sum(s.get("employment", se_data.get(s["code"], {}).get("employment", 0))
                   for s in scores if lo <= (s.get("exposure") or s.get("v2_score", 0)) <= hi)
        print(f"  {name}: {count} occupations")


if __name__ == "__main__":
    main()
