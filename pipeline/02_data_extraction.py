#!/usr/bin/env python3
"""Stage 2: validate and enrich inbound lead records."""

import argparse
import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "output" / "polled_leads.csv"
DEFAULT_OUTPUT = ROOT / "output" / "enriched_leads.csv"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    with args.input.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"lead_id", "company_name", "title", "industry", "first_name", "last_name",
                    "company_size_tracked", "company_size_self_reported", "engagement_signal", "form_message"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            parser.error("CSV is missing required column(s): " + ", ".join(sorted(missing)))
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    passthrough_fields = [
        "record_id", "company_id", "industry_type", "company_size", "signal_message",
        "company_request_count",
    ]
    output_fields = [*fieldnames, *[name for name in passthrough_fields if name not in fieldnames]]
    enriched_rows = []
    for row in rows:
        enriched = dict(row)
        enriched.update({
            "industry_type": row.get("industry", ""),
            "company_size": row.get("company_size_tracked", "").strip()
                            or row.get("company_size_self_reported", "").strip(),
            "signal_message": " ".join(
                value for value in (
                    row.get("engagement_signal", "").strip(),
                    row.get("form_message", "").strip(),
                ) if value
            ),
        })
        enriched_rows.append(enriched)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=output_fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(enriched_rows)

    print(f"Enriched {len(enriched_rows)} record(s); enriched data written to {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
