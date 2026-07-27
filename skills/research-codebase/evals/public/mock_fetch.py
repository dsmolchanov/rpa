#!/usr/bin/env python3
"""Mock live-source fetcher for the synthetic preflight.

Stands in for the registered `drift_fetch_cmd` (curl/wget in a real
deployment): resolves the URL path after `/live/` under the directory
named by MOCK_LIVE_ROOT and copies that file to the destination, exiting
nonzero when the "live" source does not exist. This lets the preflight
prove the harness fetches sealed source URLs itself — with drift injected
by pointing MOCK_LIVE_ROOT at changed content — without any network.

Usage: mock_fetch.py <url> <dest>
"""

import os
import sys
from pathlib import Path


def main():
    url, dest = sys.argv[1], sys.argv[2]
    root = os.environ.get("MOCK_LIVE_ROOT")
    if not root:
        print("mock_fetch: MOCK_LIVE_ROOT not set", file=sys.stderr)
        sys.exit(2)
    marker = "/live/"
    if marker not in url:
        print(f"mock_fetch: unexpected url {url}", file=sys.stderr)
        sys.exit(2)
    log = os.environ.get("MOCK_FETCH_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(url + "\n")
    source = Path(root) / url.split(marker, 1)[1]
    if not source.is_file():
        print(f"mock_fetch: no live source at {source}", file=sys.stderr)
        sys.exit(2)
    Path(dest).write_bytes(source.read_bytes())


if __name__ == "__main__":
    main()
