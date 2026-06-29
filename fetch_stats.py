"""
Fetch Brevo stats and update crm_data.json statuses.
Runs daily via GitHub Actions after the prospector.
"""

import os
import json
import requests
from datetime import datetime, timedelta

BREVO_API_KEY = os.environ["BREVO_API_KEY"]
CRM_FILE      = "crm_data.json"

# Status priority — higher index = more advanced state (never downgrade)
STATUS_PRIORITY = ["sent", "delivered", "opened", "bounced"]

BREVO_EVENT_MAP = {
    "delivered":   "delivered",
    "opened":      "opened",
    "hardBounces": "bounced",
    "softBounces": "bounced",
    "blocked":     "bounced",
    "invalid":     "bounced",
}


def load_crm():
    if os.path.exists(CRM_FILE):
        with open(CRM_FILE) as f:
            return json.load(f)
    return []


def save_crm(data):
    with open(CRM_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fetch_brevo_events(days=30):
    """Fetch all prospector events from Brevo for the last N days."""
    events = []
    offset = 0
    limit  = 100
    start  = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    while True:
        r = requests.get(
            "https://api.brevo.com/v3/smtp/statistics/events",
            headers={"api-key": BREVO_API_KEY},
            params={
                "tags":      "prospector",
                "startDate": start,
                "limit":     limit,
                "offset":    offset,
                "sort":      "desc",
            },
            timeout=15,
        )
        if r.status_code != 200:
            print(f"[fetch_stats] ⚠️  Brevo API error {r.status_code}: {r.text[:200]}")
            break

        batch = r.json().get("events", [])
        if not batch:
            break

        events.extend(batch)
        if len(batch) < limit:
            break
        offset += limit

    print(f"[fetch_stats] {len(events)} eventos obtenidos de Brevo")
    return events


def upgrade_status(current, new):
    """Only upgrade status, never downgrade (e.g. opened stays opened even if later delivered appears)."""
    ci = STATUS_PRIORITY.index(current) if current in STATUS_PRIORITY else 0
    ni = STATUS_PRIORITY.index(new)     if new     in STATUS_PRIORITY else 0
    return new if ni > ci else current


def main():
    crm = load_crm()
    if not crm:
        print("[fetch_stats] crm_data.json vacío — nada que actualizar")
        return

    # Build index: email -> crm entry index
    email_index = {entry["email"]: i for i, entry in enumerate(crm)}

    events = fetch_brevo_events(days=90)

    updated = 0
    for event in events:
        email      = event.get("email", "").lower()
        event_type = event.get("event", "")
        new_status = BREVO_EVENT_MAP.get(event_type)

        if not new_status or email not in email_index:
            continue

        idx     = email_index[email]
        current = crm[idx].get("status", "sent")
        upgraded = upgrade_status(current, new_status)

        if upgraded != current:
            crm[idx]["status"] = upgraded
            updated += 1
            print(f"  {email}: {current} → {upgraded}")

    save_crm(crm)
    print(f"[fetch_stats] {updated} registros actualizados")


if __name__ == "__main__":
    main()
