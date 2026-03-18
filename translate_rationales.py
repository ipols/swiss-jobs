"""
Batch translate AI exposure rationales into French and German using Claude.

Reads rationales from data/scores.json and outputs translated versions
to data/rationales_fr.json and data/rationales_de.json.

Usage:
    uv run python translate_rationales.py              # both languages
    uv run python translate_rationales.py --language fr # French only
    uv run python translate_rationales.py --language de # German only
"""

import argparse
import json
import os
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

SCORES_FILE = Path("data/scores.json")
OUTPUT_DIR = Path("data")
BATCH_SIZE = 20
MODEL = "claude-sonnet-4-6"

LANGUAGE_NAMES = {"fr": "French", "de": "German"}

SYSTEM_PROMPT = """You are a professional translator specializing in labor market and AI technology terminology.
Translate the provided AI exposure rationales accurately and concisely.
Each rationale is a 1-2 sentence assessment of how AI affects a specific Swiss occupation.
Maintain the same tone, precision, and length as the original.
Return ONLY a valid JSON object with the same keys (ISCO codes) mapping to translated strings.
Do not add any explanation or markdown formatting."""


def translate_batch(client, batch, language):
    """Translate a batch of rationales into the target language."""
    lang_name = LANGUAGE_NAMES[language]
    prompt = f"Translate these occupation AI exposure rationales from English to {lang_name}.\n\n{json.dumps(batch, ensure_ascii=False, indent=2)}"

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]

    return json.loads(text.strip())


def translate_language(client, rationales, language):
    """Translate all rationales into a single language."""
    output_file = OUTPUT_DIR / f"rationales_{language}.json"
    lang_name = LANGUAGE_NAMES[language]

    # Load existing translations for incremental progress
    existing = {}
    if output_file.exists():
        with open(output_file) as f:
            existing = json.load(f)

    remaining = {k: v for k, v in rationales.items() if k not in existing}
    if not remaining:
        print(f"  {lang_name}: all {len(existing)} rationales already translated")
        return existing

    print(f"  {lang_name}: translating {len(remaining)} rationales ({len(existing)} already done)")

    translated = dict(existing)
    codes = list(remaining.keys())
    errors = 0

    for i in range(0, len(codes), BATCH_SIZE):
        batch_codes = codes[i : i + BATCH_SIZE]
        batch = {c: remaining[c] for c in batch_codes}
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(codes) + BATCH_SIZE - 1) // BATCH_SIZE

        try:
            result = translate_batch(client, batch, language)
            translated.update(result)
            print(f"    Batch {batch_num}/{total_batches}: {len(result)} translated")
        except Exception as e:
            errors += 1
            print(f"    Batch {batch_num}/{total_batches}: ERROR {e}")
            if errors > 5:
                print("    Too many errors, stopping.")
                break

        # Save incrementally
        with open(output_file, "w") as f:
            json.dump(translated, f, indent=2, ensure_ascii=False)

        # Small delay to avoid rate limits
        time.sleep(0.5)

    print(f"  {lang_name}: {len(translated)} total translations saved to {output_file}")
    return translated


def main():
    parser = argparse.ArgumentParser(description="Translate rationales with Claude")
    parser.add_argument("--language", choices=["fr", "de"], help="Translate one language only")
    args = parser.parse_args()

    # Load rationales
    with open(SCORES_FILE) as f:
        scores = json.load(f)

    rationales = {}
    for s in scores:
        r = s.get("rationale", "").strip()
        if r:
            rationales[s["code"]] = r

    print(f"Loaded {len(rationales)} rationales from {SCORES_FILE}")

    client = anthropic.Anthropic()
    languages = [args.language] if args.language else ["fr", "de"]

    for lang in languages:
        translate_language(client, rationales, lang)

    print("\nDone!")


if __name__ == "__main__":
    main()
