import argparse
import os
import time
from datetime import datetime, timezone

import requests
import yaml
from dotenv import load_dotenv

load_dotenv()

ACTIVITIES_FILE = "activities.yaml"
TOKEN_URL = "https://www.strava.com/oauth/token"
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"

RATE_LIMIT_15MIN = 100
RATE_LIMIT_DAILY = 1000
RATE_LIMIT_SAFETY_THRESHOLD = 0.90  # pause at 90% usage


def get_access_token():
    client_id = os.environ["STRAVA_CLIENT_ID"]
    client_secret = os.environ["STRAVA_CLIENT_SECRET"]
    refresh_token = os.environ["STRAVA_REFRESH_TOKEN"]

    resp = requests.post(TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


def load_existing_activities():
    if not os.path.exists(ACTIVITIES_FILE):
        return {}
    with open(ACTIVITIES_FILE, "r") as f:
        data = yaml.safe_load(f) or {}
    return data


def get_latest_timestamp(activities: dict) -> int | None:
    """Return the UNIX timestamp of the most recent activity in the archive."""
    latest = None
    for date_str, entries in activities.items():
        for entry in entries:
            dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            ts = int(dt.timestamp())
            if latest is None or ts > latest:
                latest = ts
    return latest


def check_rate_limits(headers: dict):
    usage = headers.get("X-RateLimit-Usage", "")
    limit = headers.get("X-RateLimit-Limit", "")
    if not usage or not limit:
        return

    usage_parts = usage.split(",")
    limit_parts = limit.split(",")

    short_usage = int(usage_parts[0])
    short_limit = int(limit_parts[0])
    daily_usage = int(usage_parts[1])
    daily_limit = int(limit_parts[1])

    if short_usage / short_limit >= RATE_LIMIT_SAFETY_THRESHOLD:
        print(f"15-min rate limit at {short_usage}/{short_limit}. Sleeping 15 minutes...")
        time.sleep(900)

    if daily_usage / daily_limit >= RATE_LIMIT_SAFETY_THRESHOLD:
        print(f"Daily rate limit at {daily_usage}/{daily_limit}. Exiting to avoid ban.")
        raise SystemExit(1)


def fetch_activities(token: str, after: int = None, before: int = None) -> list:
    headers = {"Authorization": f"Bearer {token}"}
    all_activities = []
    page = 1

    while True:
        params = {"per_page": 100, "page": page}
        if after:
            params["after"] = after
        if before:
            params["before"] = before

        resp = requests.get(ACTIVITIES_URL, headers=headers, params=params)
        resp.raise_for_status()
        check_rate_limits(resp.headers)

        batch = resp.json()
        if not batch:
            break

        all_activities.extend(batch)
        print(f"  Fetched page {page} ({len(batch)} activities)")
        page += 1

    return all_activities


def transform_activity(raw: dict) -> dict:
    return {
        "id": raw["id"],
        "name": raw["name"],
        "sport_type": raw.get("sport_type", raw.get("type", "Unknown")),
        "distance_km": round(raw.get("distance", 0) / 1000, 2),
        "moving_time_sec": raw.get("moving_time", 0),
        "elevation_gain_m": round(raw.get("total_elevation_gain", 0), 1),
    }


def group_by_date(raw_activities: list) -> dict:
    grouped = {}
    for raw in raw_activities:
        date_str = raw["start_date_local"][:10]  # YYYY-MM-DD
        activity = transform_activity(raw)
        grouped.setdefault(date_str, []).append(activity)
    return grouped


def merge_activities(existing: dict, new_grouped: dict) -> dict:
    merged = {k: list(v) for k, v in existing.items()}

    for date_str, new_entries in new_grouped.items():
        existing_ids = {a["id"] for a in merged.get(date_str, [])}
        for entry in new_entries:
            if entry["id"] not in existing_ids:
                merged.setdefault(date_str, []).append(entry)
                existing_ids.add(entry["id"])

    # Sort by date descending
    return dict(sorted(merged.items(), reverse=True))


def save_activities(activities: dict):
    with open(ACTIVITIES_FILE, "w") as f:
        yaml.dump(activities, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def to_unix(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def main():
    parser = argparse.ArgumentParser(description="Sync Strava activities to YAML")
    parser.add_argument("--start", default="", help="Start date YYYY-MM-DD (optional)")
    parser.add_argument("--end", default="", help="End date YYYY-MM-DD (optional)")
    args = parser.parse_args()

    start = args.start.strip()
    end = args.end.strip()

    print("Refreshing access token...")
    token = get_access_token()

    existing = load_existing_activities()

    after = None
    before = None

    if start or end:
        print(f"Custom range mode: start={start or 'none'}, end={end or 'none'}")
        if start:
            after = to_unix(start)
        if end:
            before = to_unix(end)
    else:
        latest = get_latest_timestamp(existing)
        if latest:
            print(f"Incremental mode: fetching activities after {datetime.fromtimestamp(latest, tz=timezone.utc).date()}")
            after = latest
        else:
            print("No existing data found. Fetching full history...")

    print("Fetching activities from Strava...")
    raw = fetch_activities(token, after=after, before=before)
    print(f"Total fetched: {len(raw)} activities")

    if not raw:
        print("No new activities to sync.")
        return

    new_grouped = group_by_date(raw)
    merged = merge_activities(existing, new_grouped)
    save_activities(merged)

    total = sum(len(v) for v in merged.values())
    print(f"Saved {total} total activities to {ACTIVITIES_FILE}")


if __name__ == "__main__":
    main()
