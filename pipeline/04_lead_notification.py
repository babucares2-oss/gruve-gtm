#!/usr/bin/env python3
"""Stage 4: email concise scored-lead alerts with action links."""

import argparse
import csv
import html
import json
import os
import re
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import urlencode


ROOT = Path(__file__).resolve().parents[1]
ACTION_NAMES = ("schedule_appointment", "remind_me_later", "ignore", "put_in_queue")
ACTION_LABELS = {
    "schedule_appointment": "Schedule an appointment",
    "remind_me_later": "Remind me later",
    "ignore": "Ignore",
    "put_in_queue": "Put in queue",
}
def why_now(lead: dict[str, str]) -> str:
    """Summarize only industry and buying signals present in the scored row."""
    industry = (lead.get("industry_type") or lead.get("industry") or "Industry").strip()
    parts = [industry, "fit"]
    evidence = (lead.get("signal_message") or lead.get("engagement_signal") or "").casefold()
    if "budget allocated" in evidence or "budget is allocated" in evidence:
        parts.append("budget allocated")
    elif "approved" in evidence:
        parts.append("budget approved")

    timeline = (lead.get("engagement_signal") or "").strip()
    quarter = re.search(r"\bq[1-4]\s*[,/-]?\s*20\d{2}\b", timeline, re.IGNORECASE)
    if quarter:
        parts.append(f"timeline {quarter.group(0).upper().replace(' ', '')}")
    try:
        if int(float(lead.get("company_request_count", "0") or 0)) > 1:
            parts.append("repeat requests")
    except ValueError:
        pass
    if "product launch" in evidence or "launch attendance" in evidence:
        parts.append("product launch attended")
    elif any(word in evidence for word in ("social media", "followed", "follows", "linkedin")):
        parts.append("social engagement")

    # Keep the alert line between five and ten words.
    words = " ".join(parts).split()
    if len(words) < 5:
        words.extend(["readiness", "signal", "captured"][:5 - len(words)])
    return " ".join(words[:10])


def deal_category(lead: dict[str, str]) -> str:
    return lead.get("deal_category", "").strip() or "Interesting Deal"


def action_url(base: str, action: str, lead: dict[str, str]) -> str:
    separator = "&" if "?" in base else "?"
    return base + separator + urlencode({
        "action": action,
        "lead_id": lead.get("lead_id", ""),
        "record_id": lead.get("record_id", ""),
    })


def build_mail(leads: list[dict[str, str]], action_base: str, sender: str, recipient: str):
    plain_sections = []
    html_sections = []
    for lead in leads:
        category = deal_category(lead)
        title = lead.get("title", "").strip()
        company = lead.get("company_name", "").strip()
        industry = (lead.get("industry_type") or lead.get("industry") or "").strip()
        score = lead.get("score_pct", "0")
        why = why_now(lead)
        actions = " | ".join(
            f"{ACTION_LABELS[action]}: {action_url(action_base, action, lead)}"
            for action in ACTION_NAMES
        )
        plain_sections.append(
            f"{category} | {title} | {company} | {industry}\n"
            f"Score: {score}\nWhy now? {why}\nAction: {actions}"
        )
        links = " &nbsp;|&nbsp; ".join(
            f'<a href="{html.escape(action_url(action_base, action, lead), quote=True)}">'
            f'{html.escape(ACTION_LABELS[action])}</a>'
            for action in ACTION_NAMES
        )
        html_sections.append(
            "<section style=\"margin:0 0 20px;padding:0 0 16px;border-bottom:1px solid #ddd\">"
            f"<strong>{html.escape(category)} | {html.escape(title)} | "
            f"{html.escape(company)} | {html.escape(industry)}</strong><br>"
            f"Score: {html.escape(score)}<br>Why now? {html.escape(why)}<br>"
            f"Action: {links}</section>"
        )

    message = MIMEMultipart("alternative")
    message["Subject"] = f"Lead alerts: {len(leads)} prioritized lead(s)"
    message["From"] = sender
    message["To"] = recipient
    message.attach(MIMEText("\n\n".join(plain_sections), "plain", "utf-8"))
    message.attach(MIMEText("<html><body>" + "".join(html_sections) + "</body></html>", "html", "utf-8"))
    return message


def send_email(message, host: str, port: int, username: str, password: str) -> None:
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30) as server:
            server.login(username, password)
            server.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
            server.login(username, password)
            server.send_message(message)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "output" / "scored_leads.csv")
    parser.add_argument("--audit-metadata", type=Path, default=ROOT / "metadata" / "audit_metadata.json")
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    with args.input.open(encoding="utf-8-sig", newline="") as source:
        leads = list(csv.DictReader(source))
    leads.sort(key=lambda row: float(row.get("score_pct", "0") or 0), reverse=True)
    leads = leads[:max(args.top, 0)]

    audit_by_record_id = {}
    if args.audit_metadata.exists():
        try:
            audit_document = json.loads(args.audit_metadata.read_text(encoding="utf-8"))
            audit_by_record_id = {
                entry.get("record_id"): entry
                for entry in audit_document.get("records", [])
                if entry.get("record_id")
            }
        except (OSError, json.JSONDecodeError, AttributeError) as error:
            parser.error(f"Could not read audit metadata: {error}")

    now = datetime.now(timezone.utc)
    queued = []
    completed_or_ignored = 0
    notify = []
    for lead in leads:
        audit = audit_by_record_id.get(lead.get("record_id", ""), {})
        history = audit.get("action_history", [])
        latest_action = audit.get("selected_action")
        latest_reminder = audit.get("next_reminder_at")
        if not latest_action and history:
            latest_action = history[-1].get("action")
            latest_reminder = history[-1].get("next_reminder_at")
        lead["action_status"] = latest_action or "new"
        lead["next_reminder_at"] = latest_reminder or ""

        if latest_action in {"ignore", "prioritize_now", "schedule_appointment"}:
            completed_or_ignored += 1
            continue
        if latest_action:
            reminder_due = False
            if latest_reminder:
                try:
                    reminder_due = datetime.fromisoformat(
                        latest_reminder.replace("Z", "+00:00")
                    ).astimezone(timezone.utc) <= now
                except ValueError:
                    parser.error(f"Invalid reminder timestamp for record {lead.get('record_id')}")
            if reminder_due:
                lead["notification_reason"] = "Reminder due"
                notify.append(lead)
            else:
                if latest_action in {"remind_me_later", "put_in_queue", "schedule_next_week", "keep_in_queue"}:
                    queued.append((lead, latest_action))
                else:
                    completed_or_ignored += 1
            continue
        lead["notification_reason"] = "New lead"
        notify.append(lead)
    leads = notify

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("## Lead notification\n\n")
            if leads:
                for lead in leads:
                    summary.write(
                        f"- **{deal_category(lead)} | {lead.get('title', '')} | "
                        f"{lead.get('company_name', '')} | {lead.get('industry_type', '')}** — "
                        f"Score: {lead.get('score_pct', '')}; {lead.get('notification_reason', 'New lead')}; "
                        f"Why now? {why_now(lead)}\n"
                    )
            else:
                summary.write("No new or due leads to email.\n")
            if queued:
                summary.write("\n### Action queue\n\n")
                for lead, status in queued:
                    reminder = lead.get("next_reminder_at") or "No reminder scheduled"
                    summary.write(
                        f"- **{lead.get('company_name', '')}** ({lead.get('lead_id', '')}): "
                        f"{status}; next reminder: {reminder}\n"
                    )
            if completed_or_ignored:
                summary.write(f"\n{completed_or_ignored} lead(s) with completed or ignored actions were skipped.\n")

    if not leads:
        print(
            f"No new or due leads to email; {len(queued)} lead(s) remain queued and "
            f"{completed_or_ignored} completed or ignored lead(s) were skipped."
        )
        return 0

    settings = {
        "SMTP_HOST": os.environ.get("SMTP_HOST", ""),
        "SMTP_USERNAME": os.environ.get("SMTP_USERNAME", ""),
        "SMTP_PASSWORD": os.environ.get("SMTP_PASSWORD", ""),
        "LEAD_NOTIFICATION_FROM": os.environ.get("LEAD_NOTIFICATION_FROM", ""),
        "LEAD_NOTIFICATION_TO": os.environ.get("LEAD_NOTIFICATION_TO", ""),
        "LEAD_ACTION_BASE_URL": os.environ.get("LEAD_ACTION_BASE_URL", ""),
    }
    if not settings["SMTP_HOST"]:
        print("Email skipped: configure SMTP and notification settings to enable delivery.")
        return 0
    missing = [name for name, value in settings.items() if not value]
    if missing:
        parser.error("Email settings are incomplete: " + ", ".join(missing))
    try:
        port = int(os.environ.get("SMTP_PORT", "587"))
        message = build_mail(
            leads,
            settings["LEAD_ACTION_BASE_URL"],
            settings["LEAD_NOTIFICATION_FROM"],
            settings["LEAD_NOTIFICATION_TO"],
        )
        send_email(message, settings["SMTP_HOST"], port,
                   settings["SMTP_USERNAME"], settings["SMTP_PASSWORD"])
    except (OSError, ValueError, smtplib.SMTPException) as error:
        parser.error(f"Could not send lead notification email: {error}")
    print(f"Emailed {len(leads)} lead alert(s) to {settings['LEAD_NOTIFICATION_TO']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
