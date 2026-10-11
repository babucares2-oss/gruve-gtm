#!/usr/bin/env python3
"""Read the source lead CSV and write it for the next pipeline stage."""

import argparse
import csv
import json
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METADATA = ROOT / "metadata" / "record_metadata.json"


def company_key(name: str) -> str:
    return " ".join(name.casefold().split())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "sources" / "lead_records.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "polled_leads.csv")
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    args = parser.parse_args()

    if not args.source.is_file():
        parser.error(f"Source CSV does not exist: {args.source}")

    with args.source.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    required = {"lead_id", "company_name"}
    missing = required - set(fieldnames)
    if missing:
        parser.error("CSV is missing required column(s): " + ", ".join(sorted(missing)))

    records_by_lead_id: dict[str, dict[str, object]] = {}
    if args.metadata.exists():
        try:
            document = json.loads(args.metadata.read_text(encoding="utf-8"))
            for record in document["records"]:
                lead_id, record_id = record["lead_id"], record["record_id"]
                if not lead_id or not record_id or lead_id in records_by_lead_id:
                    raise ValueError("record metadata has empty or duplicate lead IDs")
                records_by_lead_id[lead_id] = record
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            parser.error(f"Invalid record metadata file {args.metadata}: {error}")

    companies: dict[str, dict[str, object]] = {}
    source_company_by_lead = {
        (row.get("lead_id") or "").strip(): (row.get("company_name") or "").strip()
        for row in rows
    }
    for record in records_by_lead_id.values():
        current_name = source_company_by_lead.get(str(record["lead_id"]), str(record["company_name"]))
        record["company_name"] = current_name
        key = company_key(current_name)
        company = companies.setdefault(key, {
            "company_id": record["company_id"],
            "company_name": record["company_name"],
            "request_count": 0,
        })
        company["request_count"] = int(company["request_count"]) + 1

    seen: set[str] = set()
    for row in rows:
        lead_id = (row.get("lead_id") or "").strip()
        name = (row.get("company_name") or "").strip()
        if not lead_id or not name:
            parser.error("Every source row must have a lead_id and company_name.")
        if lead_id in seen:
            parser.error(f"Input contains duplicate lead_id: {lead_id}")
        seen.add(lead_id)
        key = company_key(name)
        company = companies.get(key)
        if company is None:
            company = {"company_id": str(uuid4()), "company_name": name, "request_count": 0}
            companies[key] = company
        company["company_name"] = name
        record = records_by_lead_id.get(lead_id)
        if record is None:
            record = {
                "record_id": str(uuid4()),
                "lead_id": lead_id,
                "company_id": company["company_id"],
                "company_name": name,
            }
            records_by_lead_id[lead_id] = record
            company["request_count"] = int(company["request_count"]) + 1
        else:
            record["company_name"] = name
            record["company_id"] = company["company_id"]
        row["record_id"] = record["record_id"]
        row["company_id"] = company["company_id"]

    for row in rows:
        company = companies[company_key((row.get("company_name") or "").strip())]
        row["company_request_count"] = company["request_count"]

    for record in records_by_lead_id.values():
        company = companies[company_key(str(record["company_name"]))]
        record["company_id"] = company["company_id"]
        record["request_count"] = int(company["request_count"])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    output_fields = [*fieldnames, "record_id", "company_id", "company_request_count"]
    with args.output.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=list(dict.fromkeys(output_fields)), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    metadata_document = {"records": sorted(records_by_lead_id.values(), key=lambda item: str(item["lead_id"]))}
    temporary_metadata = args.metadata.with_suffix(args.metadata.suffix + ".tmp")
    temporary_metadata.write_text(json.dumps(metadata_document, indent=2) + "\n", encoding="utf-8")
    temporary_metadata.replace(args.metadata)

    print(f"Read {len(rows)} source record(s), updated {args.metadata}, and wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
