#!/usr/bin/env python3
"""
Parse BFS Strukturerhebung Excel file into hierarchical JSON occupation tree.

Reads the "2019-2021" sheet from beruf_se_24311552.xlsx and produces:
  - data/occupation_tree.json    (hierarchical tree, levels 1-4)
  - data/occupations_4digit.json (flat list of 4-digit occupations)
"""

import json
import os
import openpyxl

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FILE = os.path.join(SCRIPT_DIR, "data", "beruf_se_24311552.xlsx")
SHEET_NAME = "2019-2021"
OUTPUT_TREE = os.path.join(SCRIPT_DIR, "data", "occupation_tree.json")
OUTPUT_FLAT = os.path.join(SCRIPT_DIR, "data", "occupations_4digit.json")

# Data rows: 7 = first occupation row, 1495 = last real occupation row
# (Row 1496 is "Ausgeübter Beruf unbekannt" with X in level columns -- skip)
DATA_ROW_START = 7
DATA_ROW_END = 1495  # inclusive

# ISCO skill-level mapping by major group (1-digit code)
SKILL_LEVEL_MAP = {
    "0": 2,  # Armed Forces -- varies, use 2
    "1": 4,  # Managers
    "2": 4,  # Professionals
    "3": 3,  # Technicians & Associate Professionals
    "4": 2,  # Clerical Support Workers
    "5": 2,  # Services & Sales Workers
    "6": 2,  # Skilled Agricultural, Forestry & Fishery Workers
    "7": 2,  # Craft & Related Trades Workers
    "8": 2,  # Plant & Machine Operators, Assemblers
    "9": 1,  # Elementary Occupations
}


def clean_cell(value):
    """Strip surrounding single quotes from cell values produced by BFS export."""
    if value is None:
        return None
    if isinstance(value, str):
        # The workbook stores strings like "'Führungskräfte'" -- strip outer quotes
        if value.startswith("'") and value.endswith("'"):
            return value[1:-1]
        return value
    return value


def parse_employment(raw):
    """Convert employment value: float (thousands) -> int, 'X' -> None."""
    val = clean_cell(raw)
    if val is None or val == "" or val == "X":
        return None
    try:
        return round(float(val) * 1000)
    except (ValueError, TypeError):
        return None


def determine_level_and_code(row_cells):
    """
    Given columns 1-5 (indices 0-4), determine which ISCO level this row
    represents and return (level, code).

    Level indicators:
      col 1 -> 1-digit code (level 1)
      col 2 -> 2-digit code (level 2)
      col 3 -> 3-digit code (level 3)
      col 4 -> 4-digit code (level 4)
      col 5 -> 5-digit code (level 5)

    Empty columns contain '' (empty string after cleaning).
    """
    for col_idx in range(5):  # columns 0..4
        val = clean_cell(row_cells[col_idx])
        if val is not None and val != "":
            code = str(val).strip()
            if code:
                return (col_idx + 1, code)
    return (None, None)


def isco_skill_level(code):
    """Return ISCO skill level for a given code based on its first digit."""
    if not code:
        return None
    major = code[0]
    return SKILL_LEVEL_MAP.get(major, None)


def main():
    print(f"Reading {INPUT_FILE} ...")
    wb = openpyxl.load_workbook(INPUT_FILE, data_only=True)
    ws = wb[SHEET_NAME]

    # ------------------------------------------------------------------
    # Pass 1: Extract all occupation entries (levels 1-4)
    # ------------------------------------------------------------------
    entries = []  # list of dicts with code, level, title_de, employment
    stats = {1: 0, 2: 0, 3: 0, 4: 0}
    suppressed = {1: 0, 2: 0, 3: 0, 4: 0}

    for row_idx in range(DATA_ROW_START, DATA_ROW_END + 1):
        row_cells = [ws.cell(row=row_idx, column=c).value for c in range(1, 12)]
        level, code = determine_level_and_code(row_cells)

        if level is None or level > 4:
            continue  # skip 5-digit and anomalous rows

        title = clean_cell(row_cells[5])  # column 6 = occupation name
        employment = parse_employment(row_cells[6])  # column 7 = total
        men = parse_employment(row_cells[7])          # column 8
        women = parse_employment(row_cells[8])        # column 9

        entry = {
            "code": code,
            "level": level,
            "title_de": title if title else "",
            "employment": employment,
            "employment_men": men,
            "employment_women": women,
            "isco_skill_level": isco_skill_level(code),
        }
        entries.append(entry)
        stats[level] += 1
        if employment is None:
            suppressed[level] += 1

    print(f"Extracted {len(entries)} entries (levels 1-4)")

    # ------------------------------------------------------------------
    # Pass 2: Build hierarchical tree
    # ------------------------------------------------------------------
    tree = []  # top-level list of level-1 nodes
    # Stacks to track current parent at each level
    current = {1: None, 2: None, 3: None, 4: None}

    for entry in entries:
        node = {
            "code": entry["code"],
            "level": entry["level"],
            "title_de": entry["title_de"],
            "employment": entry["employment"],
            "employment_men": entry["employment_men"],
            "employment_women": entry["employment_women"],
            "isco_skill_level": entry["isco_skill_level"],
        }

        lvl = entry["level"]

        if lvl == 1:
            node["children"] = []
            tree.append(node)
            current[1] = node
            current[2] = None
            current[3] = None
            current[4] = None
        elif lvl == 2:
            node["children"] = []
            if current[1] is not None:
                current[1]["children"].append(node)
            current[2] = node
            current[3] = None
            current[4] = None
        elif lvl == 3:
            node["children"] = []
            if current[2] is not None:
                current[2]["children"].append(node)
            current[3] = node
            current[4] = None
        elif lvl == 4:
            # Level 4 nodes are leaves (we skip level 5)
            if current[3] is not None:
                current[3]["children"].append(node)
            current[4] = node

    tree_output = {"occupations": tree}

    # ------------------------------------------------------------------
    # Pass 3: Flat list of 4-digit occupations
    # ------------------------------------------------------------------
    flat_4digit = []
    for entry in entries:
        if entry["level"] == 4:
            flat_4digit.append({
                "code": entry["code"],
                "title_de": entry["title_de"],
                "employment": entry["employment"],
                "employment_men": entry["employment_men"],
                "employment_women": entry["employment_women"],
                "isco_skill_level": entry["isco_skill_level"],
            })

    # ------------------------------------------------------------------
    # Save outputs
    # ------------------------------------------------------------------
    with open(OUTPUT_TREE, "w", encoding="utf-8") as f:
        json.dump(tree_output, f, ensure_ascii=False, indent=2)
    print(f"Saved hierarchical tree -> {OUTPUT_TREE}")

    with open(OUTPUT_FLAT, "w", encoding="utf-8") as f:
        json.dump(flat_4digit, f, ensure_ascii=False, indent=2)
    print(f"Saved flat 4-digit list -> {OUTPUT_FLAT}")

    # ------------------------------------------------------------------
    # Summary statistics
    # ------------------------------------------------------------------
    print("\n=== Summary Statistics ===")
    print(f"{'Level':<10} {'Count':<10} {'With data':<12} {'Suppressed (X)':<15}")
    print("-" * 50)
    total_entries = 0
    total_with_data = 0
    total_suppressed = 0
    for lvl in [1, 2, 3, 4]:
        count = stats[lvl]
        sup = suppressed[lvl]
        with_data = count - sup
        total_entries += count
        total_with_data += with_data
        total_suppressed += sup
        print(f"{lvl:<10} {count:<10} {with_data:<12} {sup:<15}")
    print("-" * 50)
    print(f"{'Total':<10} {total_entries:<10} {total_with_data:<12} {total_suppressed:<15}")

    print(f"\nTop-level (1-digit) groups: {stats[1]}")
    print(f"4-digit occupations: {stats[4]} ({stats[4] - suppressed[4]} with data, {suppressed[4]} suppressed)")

    # Quick sanity check: print first few tree entries
    print("\n=== First 2 major groups (preview) ===")
    for mg in tree[:2]:
        print(f"  {mg['code']} - {mg['title_de']} (employment: {mg['employment']})")
        for child in mg["children"][:2]:
            print(f"    {child['code']} - {child['title_de']} (employment: {child['employment']})")
            for sub in child["children"][:2]:
                print(f"      {sub['code']} - {sub['title_de']} (employment: {sub['employment']})")
                for leaf in sub["children"][:2]:
                    print(f"        {leaf['code']} - {leaf['title_de']} (employment: {leaf['employment']})")


if __name__ == "__main__":
    main()
