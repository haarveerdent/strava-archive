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
ACTIVITY_DETAIL_URL = "https://www.strava.com/api/v3/activities/{id}"

RATE_LIMIT_SAFETY_THRESHOLD = 0.90


def get_access_token():
    resp = requests.post(TOKEN_URL, data={
        "client_id": os.environ["STRAVA_CLIENT_ID"],
        "client_secret": os.environ["STRAVA_CLIENT_SECRET"],
        "refresh_token": os.environ["STRAVA_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


def load_existing_activities():
    if not os.path.exists(ACTIVITIES_FILE):
        return {}
    with open(ACTIVITIES_FILE, "r") as f:
        return yaml.safe_load(f) or {}


def get_latest_timestamp(activities: dict) -> int | None:
    latest = None
    for date_str in activities:
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

    su, du = map(int, usage.split(","))
    sl, dl = map(int, limit.split(","))

    if su / sl >= RATE_LIMIT_SAFETY_THRESHOLD:
        print(f"15-min rate limit at {su}/{sl}. Sleeping 15 minutes...")
        time.sleep(900)

    if du / dl >= RATE_LIMIT_SAFETY_THRESHOLD:
        print(f"Daily rate limit at {du}/{dl}. Exiting to avoid ban.")
        raise SystemExit(1)


def fetch_activity_list(token: str, after: int = None, before: int = None) -> list:
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


def fetch_activity_detail(token: str, activity_id: int) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(
        ACTIVITY_DETAIL_URL.format(id=activity_id),
        headers=headers,
        params={"include_all_efforts": True},
    )
    resp.raise_for_status()
    check_rate_limits(resp.headers)
    return resp.json()


def _opt(raw, key, default=None):
    val = raw.get(key)
    return val if val is not None else default


def _round(val, places=2):
    return round(val, places) if val is not None else None


def transform_summary(raw: dict) -> dict:
    """Fields available on the list endpoint (SummaryActivity)."""
    return {
        # Identity
        "id": raw["id"],
        "upload_id": _opt(raw, "upload_id"),
        "external_id": _opt(raw, "external_id"),
        # Basic info
        "name": raw["name"],
        "description": _opt(raw, "description"),
        "sport_type": raw.get("sport_type", raw.get("type", "Unknown")),
        "start_date": raw.get("start_date"),
        "start_date_local": raw.get("start_date_local"),
        "timezone": _opt(raw, "timezone"),
        # Distance & time
        "distance_km": _round(raw.get("distance", 0) / 1000, 2),
        "moving_time_sec": _opt(raw, "moving_time", 0),
        "elapsed_time_sec": _opt(raw, "elapsed_time", 0),
        # Elevation
        "elevation_gain_m": _round(_opt(raw, "total_elevation_gain", 0), 1),
        "elev_high_m": _round(_opt(raw, "elev_high"), 1),
        "elev_low_m": _round(_opt(raw, "elev_low"), 1),
        # Speed
        "average_speed_ms": _round(_opt(raw, "average_speed"), 3),
        "max_speed_ms": _round(_opt(raw, "max_speed"), 3),
        # Heart rate
        "has_heartrate": _opt(raw, "has_heartrate", False),
        "average_heartrate": _round(_opt(raw, "average_heartrate"), 1),
        "max_heartrate": _opt(raw, "max_heartrate"),
        # Cadence & power
        "average_cadence": _round(_opt(raw, "average_cadence"), 1),
        "average_watts": _round(_opt(raw, "average_watts"), 1),
        "weighted_average_watts": _opt(raw, "weighted_average_watts"),
        "max_watts": _opt(raw, "max_watts"),
        "kilojoules": _round(_opt(raw, "kilojoules"), 1),
        "device_watts": _opt(raw, "device_watts"),
        # Environmental
        "average_temp_c": _opt(raw, "average_temp"),
        # Effort & achievements
        "suffer_score": _opt(raw, "suffer_score"),
        "achievement_count": _opt(raw, "achievement_count", 0),
        "kudos_count": _opt(raw, "kudos_count", 0),
        "comment_count": _opt(raw, "comment_count", 0),
        "pr_count": _opt(raw, "pr_count", 0),
        "photo_count": _opt(raw, "total_photo_count", 0),
        # Location
        "start_latlng": _opt(raw, "start_latlng"),
        "end_latlng": _opt(raw, "end_latlng"),
        "location_city": _opt(raw, "location_city"),
        "location_state": _opt(raw, "location_state"),
        "location_country": _opt(raw, "location_country"),
        # Flags
        "commute": _opt(raw, "commute", False),
        "trainer": _opt(raw, "trainer", False),
        "manual": _opt(raw, "manual", False),
        "private": _opt(raw, "private", False),
        "gear_id": _opt(raw, "gear_id"),
        "device_name": _opt(raw, "device_name"),
    }


def enrich_with_detail(activity: dict, detail: dict) -> dict:
    """Merge in fields only available from the detailed activity endpoint."""

    # Gear
    gear = detail.get("gear")
    if gear:
        activity["gear"] = {
            "id": gear.get("id"),
            "name": gear.get("name"),
            "brand_name": gear.get("brand_name"),
            "model_name": gear.get("model_name"),
            "distance_km": _round((gear.get("distance") or 0) / 1000, 1),
        }

    # Map polyline
    map_data = detail.get("map")
    if map_data:
        activity["map"] = {
            "id": map_data.get("id"),
            "summary_polyline": map_data.get("summary_polyline"),
            "polyline": map_data.get("polyline"),
        }

    # Splits (metric)
    splits = detail.get("splits_metric")
    if splits:
        activity["splits_metric"] = [
            {
                "split": s.get("split"),
                "distance_m": _round(s.get("distance"), 1),
                "elapsed_time_sec": s.get("elapsed_time"),
                "moving_time_sec": s.get("moving_time"),
                "elevation_difference_m": _round(s.get("elevation_difference"), 1),
                "average_speed_ms": _round(s.get("average_speed"), 3),
                "average_heartrate": _round(s.get("average_heartrate"), 1),
                "average_grade_adjusted_speed_ms": _round(s.get("average_grade_adjusted_speed"), 3),
                "pace_zone": s.get("pace_zone"),
            }
            for s in splits
        ]

    # Laps
    laps = detail.get("laps")
    if laps:
        activity["laps"] = [
            {
                "lap_index": l.get("lap_index"),
                "name": l.get("name"),
                "distance_km": _round((l.get("distance") or 0) / 1000, 2),
                "moving_time_sec": l.get("moving_time"),
                "elapsed_time_sec": l.get("elapsed_time"),
                "elevation_gain_m": _round(l.get("total_elevation_gain"), 1),
                "average_speed_ms": _round(l.get("average_speed"), 3),
                "max_speed_ms": _round(l.get("max_speed"), 3),
                "average_heartrate": _round(l.get("average_heartrate"), 1),
                "max_heartrate": l.get("max_heartrate"),
                "average_cadence": _round(l.get("average_cadence"), 1),
                "average_watts": _round(l.get("average_watts"), 1),
                "pace_zone": l.get("pace_zone"),
            }
            for l in laps
        ]

    # Best efforts (PRs)
    best_efforts = detail.get("best_efforts")
    if best_efforts:
        activity["best_efforts"] = [
            {
                "name": e.get("name"),
                "distance_m": e.get("distance"),
                "moving_time_sec": e.get("moving_time"),
                "elapsed_time_sec": e.get("elapsed_time"),
                "pr_rank": e.get("pr_rank"),
                "achievements": e.get("achievements", []),
            }
            for e in best_efforts
        ]

    # Segment efforts (top 10 by elapsed time to keep YAML manageable)
    segment_efforts = detail.get("segment_efforts")
    if segment_efforts:
        activity["segment_efforts"] = [
            {
                "name": s.get("name"),
                "segment_id": s.get("segment", {}).get("id"),
                "distance_m": _round(s.get("distance"), 1),
                "moving_time_sec": s.get("moving_time"),
                "elapsed_time_sec": s.get("elapsed_time"),
                "average_heartrate": _round(s.get("average_heartrate"), 1),
                "average_watts": _round(s.get("average_watts"), 1),
                "pr_rank": s.get("pr_rank"),
                "kom_rank": s.get("kom_rank"),
            }
            for s in segment_efforts[:10]
        ]

    return activity


def group_by_date(raw_activities: list, token: str, existing_ids: set) -> dict:
    grouped = {}
    total = len(raw_activities)

    for i, raw in enumerate(raw_activities):
        activity_id = raw["id"]
        date_str = raw["start_date_local"][:10]

        activity = transform_summary(raw)

        if activity_id not in existing_ids:
            print(f"  [{i+1}/{total}] Fetching detail for activity {activity_id}...")
            try:
                detail = fetch_activity_detail(token, activity_id)
                activity = enrich_with_detail(activity, detail)
            except Exception as e:
                print(f"  Warning: could not fetch detail for {activity_id}: {e}")

        grouped.setdefault(date_str, []).append(activity)

    return grouped


def merge_activities(existing: dict, new_grouped: dict) -> dict:
    merged = {k: list(v) for k, v in existing.items()}

    for date_str, new_entries in new_grouped.items():
        existing_ids = {a["id"] for a in merged.get(date_str, [])}
        for entry in new_entries:
            if entry["id"] not in existing_ids:
                merged.setdefault(date_str, []).append(entry)

    return dict(sorted(merged.items(), reverse=True))


def get_all_existing_ids(activities: dict) -> set:
    ids = set()
    for entries in activities.values():
        for a in entries:
            ids.add(a["id"])
    return ids


def save_activities(activities: dict):
    with open(ACTIVITIES_FILE, "w") as f:
        yaml.dump(activities, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def to_unix(date_str: str) -> int:
    return int(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


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
    existing_ids = get_all_existing_ids(existing)

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

    print("Fetching activity list from Strava...")
    raw_list = fetch_activity_list(token, after=after, before=before)
    print(f"Total fetched: {len(raw_list)} activities")

    if not raw_list:
        print("No new activities to sync.")
        return

    print("Fetching detailed data for each activity...")
    new_grouped = group_by_date(raw_list, token, existing_ids)
    merged = merge_activities(existing, new_grouped)
    save_activities(merged)

    total = sum(len(v) for v in merged.values())
    print(f"Saved {total} total activities to {ACTIVITIES_FILE}")


if __name__ == "__main__":
    main()
