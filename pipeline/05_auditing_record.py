#!/usr/bin/env python3
"""Stage 5: maintain pipeline and lead-action audit records."""

import argparse
import csv
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTIONS = ("schedule_appointment", "remind_me_later", "ignore", "put_in_queue")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str, option: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{option} must be an ISO 8601 date/time") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{option} must include a timezone, such as Z")
    return parsed.astimezone(timezone.utc)


def read_metadata(path: Path) -> dict:
    if not path.exists():
        return {"records": []}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document.get("records"), list):
            raise ValueError("records must be a list")
        return document
    except (json.JSONDecodeError, AttributeError, ValueError) as error:
        raise ValueError(f"Invalid audit metadata file {path}: {error}") from error


def write_metadata(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scored", type=Path, default=ROOT / "output" / "scored_leads.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "audit_record.json")
    parser.add_argument("--metadata", type=Path, default=ROOT / "metadata" / "audit_metadata.json")
    parser.add_argument("--action", choices=ACTIONS, help="Record an action selected from a lead alert.")
    parser.add_argument("--lead-id", help="Lead ID associated with the selected action.")
    parser.add_argument("--record-id", help="Stable record ID associated with the selected action.")
    parser.add_argument("--selected-by", help="Email or name of the lead/representative who selected it.")
    parser.add_argument("--selected-at", help="ISO 8601 timestamp; defaults to current UTC time.")
    parser.add_argument("--next-reminder-at", help="Optional ISO 8601 reminder timestamp.")
    parser.add_argument("--appointment-at", help="Optional ISO 8601 appointment timestamp.")
    args = parser.parse_args()

    try:
        document = read_metadata(args.metadata)
        if args.action:
            if not args.lead_id and not args.record_id:
                parser.error("--action requires --lead-id or --record-id.")
            if not args.selected_by:
                parser.error("--action requires --selected-by to identify the actor.")
            if not args.selected_by.strip():
                parser.error("--selected-by cannot be empty.")
            matches = [
                entry for entry in document["records"]
                if (args.record_id and entry.get("record_id") == args.record_id)
                or (args.lead_id and entry.get("lead_id") == args.lead_id)
            ]
            if len(matches) != 1:
                parser.error(f"Expected one matching audit entry; found {len(matches)}.")
            selected_at = parse_time(args.selected_at, "--selected-at") if args.selected_at else now_utc()
            reminder = parse_time(args.next_reminder_at, "--next-reminder-at") if args.next_reminder_at else None
            appointment = parse_time(args.appointment_at, "--appointment-at") if args.appointment_at else None
            if appointment and args.action != "schedule_appointment":
                parser.error("--appointment-at can only be used with schedule_appointment.")
            if reminder is None and args.action == "remind_me_later":
                reminder = selected_at + timedelta(days=7)
            event = {
                "action": args.action,
                "selected_by": args.selected_by.strip(),
                "selected_at": selected_at.isoformat(),
                "next_reminder_at": reminder.isoformat() if reminder else None,
                "appointment_at": appointment.isoformat() if appointment else None,
            }
            matches[0].setdefault("action_history", []).append(event)
            matches[0]["selected_action"] = args.action
            matches[0]["selected_by"] = event["selected_by"]
            matches[0]["action_selected_at"] = event["selected_at"]
            matches[0]["next_reminder_at"] = event["next_reminder_at"]
            matches[0]["appointment_at"] = event["appointment_at"]
            write_metadata(args.metadata, document)
            print(f"Recorded {args.action} for lead {matches[0].get('lead_id')} in {args.metadata}.")
            return 0

        with args.scored.open(encoding="utf-8-sig", newline="") as source:
            leads = list(csv.DictReader(source))
        timestamp = now_utc().isoformat()
        entries = {entry.get("record_id"): entry for entry in document["records"] if entry.get("record_id")}
        for lead in leads:
            record_id = (lead.get("record_id") or "").strip()
            if not record_id:
                parser.error(f"Scored lead {lead.get('lead_id', '')} has no record_id.")
            entry = entries.get(record_id)
            if entry is None:
                entry = {
                    "record_id": record_id,
                    "lead_id": lead.get("lead_id", ""),
                    "company_name": lead.get("company_name", ""),
                    "title": lead.get("title", ""),
                    "industry_type": lead.get("industry_type", ""),
                    "score_pct": lead.get("score_pct", ""),
                    "deal_category": lead.get("deal_category", ""),
                    "selected_action": None,
                    "selected_by": None,
                    "action_selected_at": None,
                    "next_reminder_at": None,
                    "appointment_at": None,
                    "last_notified_at": timestamp,
                    "action_history": [],
                }
                document["records"].append(entry)
                entries[record_id] = entry
            entry.update({
                "lead_id": lead.get("lead_id", ""),
                "company_name": lead.get("company_name", ""),
                "title": lead.get("title", ""),
                "industry_type": lead.get("industry_type", ""),
                "score_pct": lead.get("score_pct", ""),
                "deal_category": lead.get("deal_category", ""),
                "last_notified_at": timestamp,
            })
        document["records"].sort(key=lambda entry: str(entry.get("lead_id", "")))
        write_metadata(args.metadata, document)

        pipeline_audit = {
            "recorded_at_utc": timestamp,
            "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
            "workflow_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "event": os.environ.get("GITHUB_EVENT_NAME"),
            "commit": os.environ.get("GITHUB_SHA"),
            "source_file": "sources/lead_records.csv",
            "scoring_config": "scoring_config.json",
            "lead_count": len(leads),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(pipeline_audit, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as error:
        parser.error(str(error))

    print(f"Audit record saved to {args.output}; lead action metadata updated at {args.metadata}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
