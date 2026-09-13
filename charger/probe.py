#!/usr/bin/env python3
"""
Diagnostic utility to probe BF Tech (Hexapower) Charger HTTP endpoints on 192.168.4.1.
Discovers available API routes, scrapes HTML/JavaScript variables, and logs responses.
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_URL = "http://192.168.4.1"
CANDIDATE_PATHS = [
    "/",
    "/status",
    "/status.json",
    "/data",
    "/data.json",
    "/api",
    "/api/status",
    "/api/data",
    "/api/state",
    "/state",
    "/state.json",
    "/info",
    "/get",
    "/metrics",
    "/values",
    "/config",
]


def fetch_url(url: str, timeout: float = 3.0) -> tuple[int | None, str | None, dict]:
    """Fetch HTTP URL, returning (status_code, content, headers)."""
    req = Request(
        url,
        headers={"User-Agent": "Paeraki-Probe/1.0", "Accept": "*/*"},
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            status = resp.status
            content = resp.read().decode("utf-8", errors="replace")
            headers = dict(resp.headers)
            return status, content, headers
    except HTTPError as e:
        content = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return e.code, content, dict(e.headers)
    except (URLError, TimeoutError, OSError) as e:
        return None, str(e), {}


def extract_potential_endpoints(html: str) -> list[str]:
    """Scan HTML/JS for URLs or fetch/ajax endpoints."""
    endpoints = set()
    # Match patterns like fetch('/api/...'), $.get('/...'), href="/..."
    for match in re.finditer(r"""(?:fetch|get|post|\$|url|href|src)\s*[\(:=]\s*['"]([/a-zA-Z0-9_\-\.\?&=]+)['"]""", html, re.I):
        path = match.group(1)
        if path.startswith("/") and not path.endswith((".css", ".js", ".png", ".jpg", ".ico")):
            endpoints.add(path)
    return sorted(endpoints)


def extract_js_variables(html: str) -> dict[str, str]:
    """Extract key/value variables often declared in embedded JS (e.g. var volt = 79.4)."""
    metrics = {}
    keywords = ["volt", "curr", "amp", "pwr", "power", "temp", "status", "state", "soc", "error", "fault"]
    for line in html.splitlines():
        line = line.strip()
        for kw in keywords:
            if re.search(rf"\b{kw}\b", line, re.I):
                match = re.search(r"(?:var|let|const)?\s*([a-zA-Z0-9_]+)\s*[:=]\s*([^;,\n]+)", line)
                if match:
                    var_name = match.group(1)
                    val = match.group(2).strip().strip("'\"")
                    metrics[var_name] = val
    return metrics


def main():
    parser = argparse.ArgumentParser(description="Probe BF Tech (Hexapower) Charger HTTP Interface")
    parser.add_argument("--url", default=DEFAULT_URL, help="Charger base URL (default: http://192.168.4.1)")
    parser.add_argument("--out", default="/home/jh/paeraki/data/charger_probe_results.json", help="Path to save probe results")
    parser.add_argument("--timeout", type=float, default=3.0, help="HTTP timeout in seconds (default: 3.0)")
    args = parser.parse_args()

    base = args.url.rstrip("/")
    print("=" * 65)
    print(f" Paeraki • Probing BF Tech Charger at {base}")
    print("=" * 65)

    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "base_url": base,
        "reachable": False,
        "endpoints": {},
        "discovered_paths": [],
        "inferred_metrics": {},
    }

    # 1. Test base URL
    print(f"[*] Testing connectivity to {base}/ ...")
    status, content, headers = fetch_url(f"{base}/", timeout=args.timeout)

    if status is None:
        print(f"[-] Connection failed: {content}")
        print("[!] Ensure sing is connected to the charger Wi-Fi AP (wlan1).")
        sys.exit(1)

    results["reachable"] = True
    results["endpoints"]["/"] = {
        "status": status,
        "content_length": len(content or ""),
        "content_type": headers.get("Content-Type", ""),
    }
    print(f"[+] Connected! Root responded with HTTP {status} ({len(content or '')} bytes)")

    # Scan root content for JavaScript variables & endpoints
    if content:
        found_paths = extract_potential_endpoints(content)
        if found_paths:
            print(f"[+] Discovered embedded routes in HTML: {found_paths}")
            results["discovered_paths"] = found_paths

        metrics = extract_js_variables(content)
        if metrics:
            print(f"[+] Discovered embedded variables in page: {metrics}")
            results["inferred_metrics"] = metrics

    # 2. Test candidate endpoints + any discovered paths
    paths_to_test = list(dict.fromkeys(CANDIDATE_PATHS + results["discovered_paths"]))
    print("\n[*] Probing candidate API endpoints...")

    for path in paths_to_test:
        if path == "/":
            continue
        test_url = f"{base}{path}"
        st, body, hdrs = fetch_url(test_url, timeout=args.timeout)
        if st is not None and st < 400:
            is_json = False
            parsed_data = None
            try:
                parsed_data = json.loads(body)
                is_json = True
            except Exception:
                pass

            print(f"  [+] {path:<16} -> HTTP {st} ({len(body or '')} bytes, JSON={is_json})")
            results["endpoints"][path] = {
                "status": st,
                "is_json": is_json,
                "content_type": hdrs.get("Content-Type", ""),
                "data": parsed_data if is_json else (body[:200] if body else None),
            }
            if is_json and parsed_data:
                print(f"      Payload: {json.dumps(parsed_data, indent=6)}")
        elif st is not None:
            print(f"  [-] {path:<16} -> HTTP {st}")
        else:
            print(f"  [x] {path:<16} -> Failed ({body})")

    # 3. Save report
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\n" + "=" * 65)
    print(f"[✓] Probe complete. Full results saved to: {out_path}")
    print("=" * 65)


if __name__ == "__main__":
    main()
