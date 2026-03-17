"""Test prompt_v2 on 12 occupations and compare with v1 results."""
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

TEST_CODES = ["7121", "7112", "9112", "5120", "2221", "5412",
              "2411", "2341", "1212", "2512", "2166", "4132"]


def load_data():
    with open("data/occupations_4digit.json") as f:
        se_data = {o["code"]: o for o in json.load(f)}
    with open("data/occupations.json") as f:
        wage_data = {o["code"]: o["wage_monthly"] for o in json.load(f)}
    with open("data/esco/occupations_full.json") as f:
        all_occs = json.load(f)
        esco_data = {}
        for o in all_occs:
            esco_data.setdefault(o["isco_code"], []).append(o)
    with open("data/scoring_test_results.json") as f:
        v1_results = {r["code"]: r for r in json.load(f)}
    return se_data, wage_data, esco_data, v1_results


def build_rich_message(code, se_data, wage_data, esco_data):
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
        d = esco_occs[0].get("isco_group_description", "")
        if d:
            msg += f"\n### ISCO-08 Official Description\n{d.strip()}\n"
        if len(esco_occs) > 1:
            msg += f"\n### ESCO Sub-occupations ({len(esco_occs)})\n"
            for eo in esco_occs:
                msg += f"- {eo['occupation_title']}: {eo['occupation_description'][:150]}\n"

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


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY not set")
        return

    se_data, wage_data, esco_data, v1_results = load_data()
    system_prompt = open("prompt.md").read()
    client = Anthropic()

    results = []
    print("=" * 95)
    print("PROMPT V2 TEST — Council-designed prompt")
    print("=" * 95)

    for code in TEST_CODES:
        msg = build_rich_message(code, se_data, wage_data, esco_data)
        if not msg:
            continue
        occ = se_data[code]
        print(f"  {code} {occ['title_de']}...", end=" ", flush=True)

        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": msg}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        r = json.loads(text.strip())

        v1 = v1_results.get(code, {})
        v1_score = v1.get("rich_score", "?")
        delta = r["exposure"] - v1_score if isinstance(v1_score, int) else "?"
        delta_s = f"+{delta}" if isinstance(delta, int) and delta > 0 else str(delta) if delta != 0 else "="

        print(f"v2={r['exposure']}/10 (v1={v1_score}, delta={delta_s}) conf={r.get('confidence', '?')}")
        results.append({
            "code": code,
            "title": occ["title_de"],
            "v2_score": r["exposure"],
            "v1_score": v1_score,
            "delta": delta,
            "confidence": r.get("confidence", "?"),
            "rationale": r["rationale"],
            "analysis": r.get("analysis", ""),
        })
        time.sleep(0.3)

    print("\n" + "=" * 95)
    print(f"{'Code':<6} {'Occupation':<45} {'v1':>4} {'v2':>4} {'D':>4} {'Conf':<6}")
    print("-" * 95)
    for r in results:
        d = f"+{r['delta']}" if isinstance(r['delta'], int) and r['delta'] > 0 else str(r['delta']) if r['delta'] != 0 else "="
        print(f"{r['code']:<6} {r['title'][:43]:<45} {r['v1_score']:>4} {r['v2_score']:>4} {d:>4} {r['confidence']:<6}")

    v2s = [r["v2_score"] for r in results]
    v1s = [r["v1_score"] for r in results if isinstance(r["v1_score"], int)]
    print("-" * 95)
    print(f"{'':6} {'AVERAGE':<45} {sum(v1s)/len(v1s):>4.1f} {sum(v2s)/len(v2s):>4.1f}")

    print("\n" + "=" * 95)
    print("V2 TOOLTIP RATIONALES")
    print("=" * 95)
    for r in results:
        words = len(r["rationale"].split())
        print(f"\n{r['code']} -- {r['title']} ({r['v2_score']}/10, {r['confidence']}) [{words}w]")
        print(f"  {r['rationale']}")

    print("\n" + "=" * 95)
    print("V2 DETAILED ANALYSES")
    print("=" * 95)
    for r in results:
        if r["analysis"]:
            print(f"\n{r['code']} -- {r['title']} ({r['v2_score']}/10)")
            print(f"  {r['analysis'][:300]}...")

    with open("data/scoring_test_v2_results.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print("\nSaved to data/scoring_test_v2_results.json")


if __name__ == "__main__":
    main()
