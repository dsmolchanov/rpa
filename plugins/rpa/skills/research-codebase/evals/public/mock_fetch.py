#!/usr/bin/env python3
"""Mock live-source fetcher for the synthetic preflight.

Stands in for the registered `drift_fetch_cmd` (curl/wget in a real
deployment): reads a curl-compatible `url = "..."` line from stdin, resolves
the URL path after `/live/` under the directory named by MOCK_LIVE_ROOT, and
copies that file to the argv destination, exiting
nonzero when the "live" source does not exist. This lets the preflight
prove the harness fetches sealed source URLs itself — with drift injected
by pointing MOCK_LIVE_ROOT at changed content — without any network.

Usage: printf 'url = "https://..."\n' | mock_fetch.py <dest>
"""

import json
import os
import re
import sys
from pathlib import Path


def parse_curl_config(text):
    match = re.fullmatch(r'url = "((?:[^"\\]|\\["\\])*)"\n?', text)
    if not match:
        raise ValueError("expected one quoted curl-config URL")
    escaped = match.group(1)
    return re.sub(r'\\(["\\])', r'\1', escaped)


def main():
    if len(sys.argv) != 2:
        print("mock_fetch: expected destination argv", file=sys.stderr)
        sys.exit(2)
    fetch_input = sys.stdin.read()
    try:
        url = parse_curl_config(fetch_input)
    except ValueError:
        print("mock_fetch: invalid stdin config", file=sys.stderr)
        sys.exit(2)
    dest = sys.argv[1]
    root = os.environ.get("MOCK_LIVE_ROOT")
    if not root:
        print("mock_fetch: MOCK_LIVE_ROOT not set", file=sys.stderr)
        sys.exit(2)
    marker = "/live/"
    if marker not in url:
        print("mock_fetch: unexpected URL shape", file=sys.stderr)
        sys.exit(2)
    log = os.environ.get("MOCK_FETCH_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(url + "\n")
    transport_log = os.environ.get("MOCK_FETCH_TRANSPORT_LOG")
    if transport_log:
        with open(transport_log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "argv": sys.argv[1:],
                "stdin": fetch_input,
            }, sort_keys=True) + "\n")
    source = Path(root) / url.split(marker, 1)[1]
    if not source.is_file():
        print("mock_fetch: live source unavailable", file=sys.stderr)
        sys.exit(2)
    Path(dest).write_bytes(source.read_bytes())


if __name__ == "__main__":
    main()
