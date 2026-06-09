#!/usr/bin/env python3
"""Small CLI for calling the Samsara REST API.

The script intentionally reads the API token from SAMSARA_API_TOKEN so secrets
do not need to be placed in source code or shell history.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://api.samsara.com"
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class ApiError(RuntimeError):
    """Raised when the Samsara API returns an error response."""


def parse_key_value(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError(
            f"expected KEY=VALUE format for query parameter, got {value!r}"
        )
    key, parsed_value = value.split("=", 1)
    if not key:
        raise argparse.ArgumentTypeError("query parameter key cannot be empty")
    return key, parsed_value


def build_url(base_url: str, endpoint: str, params: list[tuple[str, str]]) -> str:
    """Build an API URL from a full URL or an endpoint path."""
    if endpoint.startswith(("http://", "https://")):
        url = endpoint
    else:
        url = urljoin(base_url.rstrip("/") + "/", endpoint.lstrip("/"))

    parsed = urlparse(url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.extend(params)
    return urlunparse(parsed._replace(query=urlencode(query)))


def load_json_body(body_json: str | None, body_file: str | None) -> bytes | None:
    if body_json and body_file:
        raise SystemExit("Use either --body-json or --body-file, not both.")
    if not body_json and not body_file:
        return None

    raw_body = body_json
    if body_file:
        with open(body_file, "r", encoding="utf-8") as handle:
            raw_body = handle.read()

    try:
        parsed = json.loads(raw_body or "")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Request body is not valid JSON: {exc}") from exc

    return json.dumps(parsed).encode("utf-8")


def request_json(
    *,
    token: str,
    method: str,
    url: str,
    body: bytes | None,
    timeout: float,
) -> Any:
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"

    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            response_body = response.read()
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise ApiError(
            f"Samsara API returned HTTP {exc.code} for {method} {url}:\n{error_body}"
        ) from exc
    except URLError as exc:
        raise ApiError(f"Could not reach Samsara API: {exc.reason}") from exc

    if not response_body:
        return None

    try:
        return json.loads(response_body)
    except json.JSONDecodeError:
        return response_body.decode("utf-8", errors="replace")


def add_or_replace_after(url: str, cursor: str) -> str:
    parsed = urlparse(url)
    query = [(key, value) for key, value in parse_qsl(parsed.query) if key != "after"]
    query.append(("after", cursor))
    return urlunparse(parsed._replace(query=urlencode(query)))


def request_paginated(
    *,
    token: str,
    url: str,
    timeout: float,
) -> dict[str, Any]:
    all_items: list[Any] = []
    page_count = 0
    next_url = url
    last_response: dict[str, Any] | None = None

    while True:
        page_count += 1
        response = request_json(
            token=token,
            method="GET",
            url=next_url,
            body=None,
            timeout=timeout,
        )
        if not isinstance(response, dict):
            return {"data": [response], "pageCount": page_count}

        last_response = response
        data = response.get("data")
        if isinstance(data, list):
            all_items.extend(data)
        elif data is not None:
            all_items.append(data)

        pagination = response.get("pagination")
        if not isinstance(pagination, dict) or not pagination.get("hasNextPage"):
            break

        end_cursor = pagination.get("endCursor")
        if not end_cursor:
            break
        next_url = add_or_replace_after(url, str(end_cursor))

    result: dict[str, Any] = {
        "data": all_items,
        "pageCount": page_count,
        "pagination": {
            "hasNextPage": False,
            "endCursor": "",
        },
    }

    if last_response:
        for key, value in last_response.items():
            if key not in result and key not in {"data", "pagination"}:
                result[key] = value

    return result


def write_output(payload: Any, output_path: str | None) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if output_path:
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write(rendered)
        return
    print(rendered, end="")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Call the Samsara REST API with SAMSARA_API_TOKEN.",
        epilog=(
            "Examples:\n"
            "  python scripts/samsara_api.py /fleet/vehicles --paginate\n"
            "  python scripts/samsara_api.py /fleet/drivers --param limit=100\n"
            "  python scripts/samsara_api.py /addresses --method POST "
            "--body-json '{\"name\":\"Yard\"}' --yes"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("endpoint", help="API path, such as /fleet/vehicles, or a full URL")
    parser.add_argument(
        "--method",
        default="GET",
        help="HTTP method to use. Defaults to GET.",
    )
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        type=parse_key_value,
        metavar="KEY=VALUE",
        help="Query parameter to add. Can be provided multiple times.",
    )
    parser.add_argument(
        "--body-json",
        help="JSON request body for POST, PUT, or PATCH.",
    )
    parser.add_argument(
        "--body-file",
        help="Path to a file containing a JSON request body.",
    )
    parser.add_argument(
        "--paginate",
        action="store_true",
        help="Follow Samsara pagination and combine all data items.",
    )
    parser.add_argument(
        "--output",
        help="Write JSON output to this file instead of stdout.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Samsara API base URL. Defaults to {DEFAULT_BASE_URL}.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Request timeout in seconds. Defaults to 30.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required for write methods to confirm the dashboard may be changed.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    method = args.method.upper()

    token = os.environ.get("SAMSARA_API_TOKEN", "").strip()
    if not token:
        print(
            "Missing SAMSARA_API_TOKEN. Export your Samsara API token before running.",
            file=sys.stderr,
        )
        return 2

    if method in WRITE_METHODS and not args.yes:
        print(
            f"{method} can modify Samsara dashboard data. Re-run with --yes to continue.",
            file=sys.stderr,
        )
        return 2

    if args.paginate and method != "GET":
        print("--paginate is only supported for GET requests.", file=sys.stderr)
        return 2

    body = load_json_body(args.body_json, args.body_file)
    if method == "GET" and body is not None:
        print("GET requests cannot include a JSON body.", file=sys.stderr)
        return 2

    url = build_url(args.base_url, args.endpoint, args.param)
    try:
        if args.paginate:
            payload = request_paginated(token=token, url=url, timeout=args.timeout)
        else:
            payload = request_json(
                token=token,
                method=method,
                url=url,
                body=body,
                timeout=args.timeout,
            )
    except ApiError as exc:
        print(exc, file=sys.stderr)
        return 1

    write_output(payload, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
