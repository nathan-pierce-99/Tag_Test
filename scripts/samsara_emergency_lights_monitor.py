#!/usr/bin/env python3
"""Keep a Samsara vehicle in an emergency-lights tag based on speed.

By default this monitors "Nates Rav4" and the "emergency lights" tag. It reads
the API token from SAMSARA_API_TOKEN and requires --apply before making changes.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any

import samsara_api


DEFAULT_VEHICLE_NAME = "Nates Rav4"
DEFAULT_TAG_NAME = "emergency lights"
DEFAULT_THRESHOLD_MPH = 45.0
DEFAULT_POLL_SECONDS = 5.0


class MonitorError(RuntimeError):
    """Raised when the monitor cannot safely complete an operation."""


def normalize_name(value: str) -> str:
    return "".join(character.lower() for character in value if character.isalnum())


def log(message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"{timestamp} {message}", flush=True)


def require_token() -> str:
    token = os.environ.get("SAMSARA_API_TOKEN", "").strip()
    if not token:
        raise MonitorError(
            "Missing SAMSARA_API_TOKEN. Export your Samsara API token before running."
        )
    return token


def request_json(
    *,
    token: str,
    method: str,
    base_url: str,
    endpoint: str,
    params: list[tuple[str, str]] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float,
) -> Any:
    url = samsara_api.build_url(base_url, endpoint, params or [])
    body_bytes = json.dumps(body).encode("utf-8") if body is not None else None
    return samsara_api.request_json(
        token=token,
        method=method,
        url=url,
        body=body_bytes,
        timeout=timeout,
    )


def request_paginated(
    *,
    token: str,
    base_url: str,
    endpoint: str,
    params: list[tuple[str, str]] | None = None,
    timeout: float,
) -> list[dict[str, Any]]:
    url = samsara_api.build_url(base_url, endpoint, params or [])
    response = samsara_api.request_paginated(token=token, url=url, timeout=timeout)
    data = response.get("data")
    if not isinstance(data, list):
        raise MonitorError(f"Expected list data from {endpoint}, got {type(data).__name__}")
    return [item for item in data if isinstance(item, dict)]


def find_one_by_name(
    *,
    items: list[dict[str, Any]],
    requested_name: str,
    item_type: str,
) -> dict[str, Any]:
    exact_matches = [
        item
        for item in items
        if str(item.get("name", "")).casefold() == requested_name.casefold()
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        ids = ", ".join(str(item.get("id")) for item in exact_matches)
        raise MonitorError(f"Multiple {item_type}s matched {requested_name!r}: {ids}")

    normalized_requested = normalize_name(requested_name)
    normalized_matches = [
        item
        for item in items
        if normalize_name(str(item.get("name", ""))) == normalized_requested
    ]
    if len(normalized_matches) == 1:
        return normalized_matches[0]
    if len(normalized_matches) > 1:
        ids = ", ".join(str(item.get("id")) for item in normalized_matches)
        raise MonitorError(
            f"Multiple {item_type}s matched normalized name {requested_name!r}: {ids}"
        )

    available = ", ".join(
        sorted(str(item.get("name")) for item in items if item.get("name"))[:20]
    )
    raise MonitorError(
        f"Could not find {item_type} named {requested_name!r}. "
        f"First available names: {available or '(none)'}"
    )


def resolve_vehicle(
    *,
    token: str,
    base_url: str,
    vehicle_id: str | None,
    vehicle_name: str,
    timeout: float,
) -> dict[str, str]:
    if vehicle_id:
        return {"id": vehicle_id, "name": vehicle_name}

    vehicles = request_paginated(
        token=token,
        base_url=base_url,
        endpoint="/fleet/vehicles",
        params=[("limit", "512")],
        timeout=timeout,
    )
    vehicle = find_one_by_name(
        items=vehicles,
        requested_name=vehicle_name,
        item_type="vehicle",
    )
    return {"id": str(vehicle["id"]), "name": str(vehicle.get("name", vehicle_name))}


def resolve_tag(
    *,
    token: str,
    base_url: str,
    tag_id: str | None,
    tag_name: str,
    timeout: float,
) -> dict[str, str]:
    if tag_id:
        return {"id": tag_id, "name": tag_name}

    tags = request_paginated(
        token=token,
        base_url=base_url,
        endpoint="/tags",
        params=[("limit", "512")],
        timeout=timeout,
    )
    tag = find_one_by_name(items=tags, requested_name=tag_name, item_type="tag")
    return {"id": str(tag["id"]), "name": str(tag.get("name", tag_name))}


def get_vehicle_speed_mph(
    *,
    token: str,
    base_url: str,
    vehicle_id: str,
    timeout: float,
) -> tuple[float | None, str | None]:
    response = request_json(
        token=token,
        method="GET",
        base_url=base_url,
        endpoint="/fleet/vehicles/stats",
        params=[("types", "gps"), ("vehicleIds", vehicle_id)],
        timeout=timeout,
    )
    if not isinstance(response, dict) or not isinstance(response.get("data"), list):
        raise MonitorError("Unexpected vehicle stats response from Samsara.")

    for item in response["data"]:
        if not isinstance(item, dict) or str(item.get("id")) != vehicle_id:
            continue
        gps = item.get("gps")
        if not isinstance(gps, dict):
            return None, None
        speed = gps.get("speedMilesPerHour")
        if speed is None:
            return None, str(gps.get("time")) if gps.get("time") else None
        try:
            return float(speed), str(gps.get("time")) if gps.get("time") else None
        except (TypeError, ValueError) as exc:
            raise MonitorError(f"Invalid speed value from Samsara: {speed!r}") from exc

    raise MonitorError(f"Vehicle {vehicle_id} was not present in vehicle stats response.")


def get_tag_vehicle_ids(
    *,
    token: str,
    base_url: str,
    tag_id: str,
    timeout: float,
) -> list[str]:
    response = request_json(
        token=token,
        method="GET",
        base_url=base_url,
        endpoint=f"/tags/{tag_id}",
        timeout=timeout,
    )
    if not isinstance(response, dict) or not isinstance(response.get("data"), dict):
        raise MonitorError("Unexpected tag response from Samsara.")

    vehicles = response["data"].get("vehicles", [])
    if vehicles is None:
        return []
    if not isinstance(vehicles, list):
        raise MonitorError("Unexpected tag vehicles response from Samsara.")

    vehicle_ids: list[str] = []
    for vehicle in vehicles:
        if isinstance(vehicle, dict) and vehicle.get("id") is not None:
            vehicle_ids.append(str(vehicle["id"]))
        elif isinstance(vehicle, str):
            vehicle_ids.append(vehicle)
    return vehicle_ids


def patch_tag_vehicle_ids(
    *,
    token: str,
    base_url: str,
    tag_id: str,
    vehicle_ids: list[str],
    timeout: float,
) -> None:
    request_json(
        token=token,
        method="PATCH",
        base_url=base_url,
        endpoint=f"/tags/{tag_id}",
        body={"vehicles": vehicle_ids},
        timeout=timeout,
    )


def reconcile_tag_membership(
    *,
    token: str,
    base_url: str,
    tag_id: str,
    tag_name: str,
    vehicle_id: str,
    vehicle_name: str,
    should_be_tagged: bool,
    apply_changes: bool,
    timeout: float,
) -> None:
    current_vehicle_ids = get_tag_vehicle_ids(
        token=token,
        base_url=base_url,
        tag_id=tag_id,
        timeout=timeout,
    )
    is_tagged = vehicle_id in current_vehicle_ids

    if should_be_tagged and is_tagged:
        log(f"{vehicle_name} is already in {tag_name!r}; no change needed.")
        return
    if not should_be_tagged and not is_tagged:
        log(f"{vehicle_name} is already outside {tag_name!r}; no change needed.")
        return

    if should_be_tagged:
        updated_vehicle_ids = current_vehicle_ids + [vehicle_id]
        action = "add"
        past_tense_action = "added"
    else:
        updated_vehicle_ids = [
            current_id for current_id in current_vehicle_ids if current_id != vehicle_id
        ]
        action = "remove"
        past_tense_action = "removed"

    if not apply_changes:
        log(
            f"DRY RUN: would {action} {vehicle_name} "
            f"({'id=' + vehicle_id}) {'to' if should_be_tagged else 'from'} {tag_name!r}."
        )
        return

    patch_tag_vehicle_ids(
        token=token,
        base_url=base_url,
        tag_id=tag_id,
        vehicle_ids=updated_vehicle_ids,
        timeout=timeout,
    )
    log(f"Updated {tag_name!r}: {past_tense_action} {vehicle_name} ({'id=' + vehicle_id}).")


def run_once(
    *,
    token: str,
    base_url: str,
    vehicle: dict[str, str],
    tag: dict[str, str],
    threshold_mph: float,
    apply_changes: bool,
    timeout: float,
) -> None:
    speed_mph, gps_time = get_vehicle_speed_mph(
        token=token,
        base_url=base_url,
        vehicle_id=vehicle["id"],
        timeout=timeout,
    )
    if speed_mph is None:
        log(f"No current GPS speed for {vehicle['name']}; leaving tag unchanged.")
        return

    should_be_tagged = speed_mph > threshold_mph
    comparator = "over" if should_be_tagged else "at or below"
    gps_detail = f" from GPS ping {gps_time}" if gps_time else ""
    log(
        f"{vehicle['name']} is traveling {speed_mph:.1f} MPH{gps_detail}, "
        f"{comparator} {threshold_mph:.1f} MPH."
    )
    reconcile_tag_membership(
        token=token,
        base_url=base_url,
        tag_id=tag["id"],
        tag_name=tag["name"],
        vehicle_id=vehicle["id"],
        vehicle_name=vehicle["name"],
        should_be_tagged=should_be_tagged,
        apply_changes=apply_changes,
        timeout=timeout,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Monitor a Samsara vehicle speed and add/remove it from an emergency "
            "lights tag when it crosses a MPH threshold."
        )
    )
    parser.add_argument(
        "--vehicle-name",
        default=DEFAULT_VEHICLE_NAME,
        help=f"Vehicle name to monitor. Defaults to {DEFAULT_VEHICLE_NAME!r}.",
    )
    parser.add_argument(
        "--vehicle-id",
        help="Samsara vehicle ID. If provided, skips vehicle name lookup.",
    )
    parser.add_argument(
        "--tag-name",
        default=DEFAULT_TAG_NAME,
        help=f"Tag name to manage. Defaults to {DEFAULT_TAG_NAME!r}.",
    )
    parser.add_argument(
        "--tag-id",
        help="Samsara tag ID. If provided, skips tag name lookup.",
    )
    parser.add_argument(
        "--threshold-mph",
        type=float,
        default=DEFAULT_THRESHOLD_MPH,
        help=f"Add to the tag above this speed; remove at or below it. Defaults to {DEFAULT_THRESHOLD_MPH}.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=DEFAULT_POLL_SECONDS,
        help=f"Polling interval for continuous mode. Defaults to {DEFAULT_POLL_SECONDS}.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one speed check and exit.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually patch Samsara tag membership. Without this, the script is dry-run only.",
    )
    parser.add_argument(
        "--base-url",
        default=samsara_api.DEFAULT_BASE_URL,
        help=f"Samsara API base URL. Defaults to {samsara_api.DEFAULT_BASE_URL}.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Request timeout in seconds. Defaults to 30.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.threshold_mph < 0:
        print("--threshold-mph cannot be negative.", file=sys.stderr)
        return 2
    if args.poll_seconds <= 0:
        print("--poll-seconds must be greater than zero.", file=sys.stderr)
        return 2

    try:
        token = require_token()
        vehicle = resolve_vehicle(
            token=token,
            base_url=args.base_url,
            vehicle_id=args.vehicle_id,
            vehicle_name=args.vehicle_name,
            timeout=args.timeout,
        )
        tag = resolve_tag(
            token=token,
            base_url=args.base_url,
            tag_id=args.tag_id,
            tag_name=args.tag_name,
            timeout=args.timeout,
        )
    except (MonitorError, samsara_api.ApiError) as exc:
        print(exc, file=sys.stderr)
        return 1

    mode = "APPLYING changes" if args.apply else "dry-run mode"
    log(
        f"Monitoring {vehicle['name']} (id={vehicle['id']}) against "
        f"{tag['name']!r} (id={tag['id']}) at {args.threshold_mph:.1f} MPH in {mode}."
    )

    stop_requested = False

    def handle_stop(signum: int, _frame: Any) -> None:
        nonlocal stop_requested
        stop_requested = True
        log(f"Received signal {signum}; stopping after current loop.")

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    while not stop_requested:
        try:
            run_once(
                token=token,
                base_url=args.base_url,
                vehicle=vehicle,
                tag=tag,
                threshold_mph=args.threshold_mph,
                apply_changes=args.apply,
                timeout=args.timeout,
            )
        except (MonitorError, samsara_api.ApiError) as exc:
            log(f"ERROR: {exc}")
            if args.once:
                return 1

        if args.once:
            break
        time.sleep(args.poll_seconds)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
