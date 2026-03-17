"""
Build site/data.json — flat Karpathy-style treemap data.

Produces 2-digit groups, each containing 4-digit leaf occupations directly.
Removes "onA" (not elsewhere classified) residual categories.
Adds English titles from ESCO data.

Merges:
  - data/occupation_tree.json (hierarchical employment data, levels 1-4)
  - data/scores.json (AI exposure scores at 4-digit level)
  - data/occupations.json (wages at 2-digit level)
  - data/esco/occupations_full.json (English titles)

Usage:
    uv run python build_site_data.py
"""

import json
import os


# ISCO-08 standard English titles for 2-digit sub-major groups
ISCO_2DIGIT_EN = {
    "01": "Commissioned Armed Forces Officers",
    "02": "Non-commissioned Armed Forces Officers",
    "03": "Armed Forces Occupations, Other Ranks",
    "11": "Chief Executives, Senior Officials and Legislators",
    "12": "Administrative and Commercial Managers",
    "13": "Production and Specialized Services Managers",
    "14": "Hospitality, Retail and Other Services Managers",
    "21": "Science and Engineering Professionals",
    "22": "Health Professionals",
    "23": "Teaching Professionals",
    "24": "Business and Administration Professionals",
    "25": "ICT Professionals",
    "26": "Legal, Social and Cultural Professionals",
    "31": "Science and Engineering Associate Professionals",
    "32": "Health Associate Professionals",
    "33": "Business and Administration Associate Professionals",
    "34": "Legal, Social, Cultural and Related Associate Professionals",
    "35": "ICT Technicians",
    "41": "General and Keyboard Clerks",
    "42": "Customer Services Clerks",
    "43": "Numerical and Material Recording Clerks",
    "44": "Other Clerical Support Workers",
    "51": "Personal Service Workers",
    "52": "Sales Workers",
    "53": "Personal Care Workers",
    "54": "Protective Services Workers",
    "61": "Market-oriented Skilled Agricultural Workers",
    "62": "Market-oriented Skilled Forestry, Fishery and Hunting Workers",
    "63": "Subsistence Farmers, Fishers, Hunters and Gatherers",
    "71": "Building and Related Trades Workers",
    "72": "Metal, Machinery and Related Trades Workers",
    "73": "Handicraft and Printing Workers",
    "74": "Electrical and Electronic Trades Workers",
    "75": "Food Processing, Wood, Garment and Other Craft Workers",
    "81": "Stationary Plant and Machine Operators",
    "82": "Assemblers",
    "83": "Drivers and Mobile Plant Operators",
    "91": "Cleaners and Helpers",
    "92": "Agricultural, Forestry and Fishery Labourers",
    "93": "Labourers in Mining, Construction, Manufacturing and Transport",
    "94": "Food Preparation Assistants",
    "95": "Street and Related Sales and Service Workers",
    "96": "Refuse Workers and Other Elementary Workers",
}

# Manual English titles for the 5 four-digit codes missing from ESCO
MANUAL_EN_TITLES = {
    "1321": "Manufacturing managers",
    "2142": "Civil engineers",
    "3221": "Nursing and midwifery associate professionals",
    "4414": "Scribes and related workers",
    "7549": "Craft and related workers not elsewhere classified",
}


def main():
    # Load occupation tree
    with open("data/occupation_tree.json") as f:
        raw = json.load(f)
        tree = raw["occupations"] if isinstance(raw, dict) and "occupations" in raw else raw

    # Load scores
    scores_by_code = {}
    if os.path.exists("data/scores.json"):
        with open("data/scores.json") as f:
            scores = json.load(f)
        scores_by_code = {s["code"]: s for s in scores}
        print(f"Loaded {len(scores_by_code)} scores")
    else:
        print("WARNING: data/scores.json not found")

    # Load wages (2-digit level)
    wages_by_code = {}
    if os.path.exists("data/occupations.json"):
        with open("data/occupations.json") as f:
            wages_by_code = {o["code"]: o["wage_monthly"] for o in json.load(f)}
        print(f"Loaded {len(wages_by_code)} wage entries")

    # Load English titles from ESCO
    en_titles = {}
    esco_path = "data/esco/occupations_full.json"
    if os.path.exists(esco_path):
        with open(esco_path) as f:
            for o in json.load(f):
                code = o["isco_code"]
                if code not in en_titles:
                    en_titles[code] = o["isco_group_title"]
        print(f"Loaded {len(en_titles)} English titles from ESCO")
    en_titles.update(MANUAL_EN_TITLES)
    en_titles.update(ISCO_2DIGIT_EN)

    # Collect all 4-digit leaf nodes from the tree, excluding onA
    def collect_leaves(node):
        """Recursively collect 4-digit leaf nodes."""
        children = node.get("children", [])
        if not children:
            # This is a leaf
            return [node]
        leaves = []
        for child in children:
            leaves.extend(collect_leaves(child))
        return leaves

    # Collect all 2-digit groups and their 4-digit leaves
    groups = {}  # code -> {group info, leaves: [...]}

    for major in tree:
        for node_2d in major.get("children", []):
            code_2d = node_2d["code"]
            if len(code_2d) != 2:
                continue

            # Collect all 4-digit leaves under this 2-digit group
            leaves = collect_leaves(node_2d)

            # Filter: must have employment, must not be onA
            filtered = []
            for leaf in leaves:
                if not leaf.get("employment"):
                    continue
                if "onA" in leaf.get("title_de", ""):
                    continue
                if len(leaf["code"]) != 4:
                    continue
                filtered.append(leaf)

            if not filtered:
                continue

            groups[code_2d] = {
                "code": code_2d,
                "title_de": node_2d["title_de"],
                "title": en_titles.get(code_2d, node_2d["title_de"]),
                "wage_monthly": wages_by_code.get(code_2d),
                "leaves": filtered,
            }

    # Also handle 1-digit codes that might directly contain 4-digit leaves
    # (like code "0" for armed forces)
    for major in tree:
        code_1d = major["code"]
        # Check if this 1-digit group has 2-digit children already handled
        has_2d = any(
            len(c["code"]) == 2 for c in major.get("children", [])
        )
        if has_2d:
            continue
        # This major group has no 2-digit intermediaries — treat it as a group itself
        leaves = collect_leaves(major)
        filtered = [
            l for l in leaves
            if l.get("employment") and "onA" not in l.get("title_de", "") and len(l["code"]) == 4
        ]
        if filtered:
            groups[code_1d] = {
                "code": code_1d,
                "title_de": major["title_de"],
                "title": en_titles.get(code_1d, major["title_de"]),
                "wage_monthly": wages_by_code.get(code_1d),
                "leaves": filtered,
            }

    # Build output
    ona_skipped = 0
    total_leaves = 0
    site_data = []

    for code in sorted(groups.keys()):
        g = groups[code]
        children = []
        group_emp = 0
        exp_pairs = []

        for leaf in g["leaves"]:
            lcode = leaf["code"]
            score = scores_by_code.get(lcode, {})
            exposure = score.get("exposure") or score.get("v2_score")

            child = {
                "code": lcode,
                "title": en_titles.get(lcode, leaf["title_de"]),
                "title_de": leaf["title_de"],
                "employment": leaf["employment"],
                "exposure": exposure,
                "confidence": score.get("confidence"),
                "rationale": score.get("rationale", ""),
                "skill_level": leaf.get("isco_skill_level"),
                "wage_monthly": g["wage_monthly"],  # inherit from 2-digit group
            }
            children.append(child)
            emp = leaf["employment"] or 0
            group_emp += emp
            if exposure is not None:
                exp_pairs.append((exposure, emp))

        # Sort children by employment
        children.sort(key=lambda c: c.get("employment") or 0, reverse=True)

        # Aggregate exposure
        group_exposure = None
        if exp_pairs:
            total_emp = sum(e for _, e in exp_pairs)
            if total_emp > 0:
                group_exposure = round(
                    sum(exp * emp for exp, emp in exp_pairs) / total_emp, 1
                )

        site_data.append({
            "code": g["code"],
            "title": g["title"],
            "title_de": g["title_de"],
            "employment": group_emp,
            "exposure": group_exposure,
            "wage_monthly": g["wage_monthly"],
            "children": children,
        })
        total_leaves += len(children)

    # Sort groups by employment
    site_data.sort(key=lambda g: g["employment"], reverse=True)

    # Stats
    total_emp = sum(g["employment"] for g in site_data)

    os.makedirs("site", exist_ok=True)
    with open("site/data.json", "w") as f:
        json.dump(site_data, f, indent=2, ensure_ascii=False)

    print(f"\nWrote site/data.json")
    print(f"  2-digit groups: {len(site_data)}")
    print(f"  4-digit occupations: {total_leaves}")
    print(f"  Total employment: {total_emp:,}")

    # Check for missing English titles
    missing_en = [
        g for group in site_data
        for g in group["children"]
        if g["title"] == g.get("title_de")
    ]
    if missing_en:
        print(f"\n  WARNING: {len(missing_en)} occupations still using German title:")
        for m in missing_en[:10]:
            print(f"    {m['code']} {m['title']}")


if __name__ == "__main__":
    main()
