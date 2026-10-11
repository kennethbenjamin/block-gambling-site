#!/usr/bin/env python3
"""Squid external_acl helper: live gambling verdicts from filter-gateway.

Protocol (concurrency=0): Squid sends "<dst> <src>\\n" per line on stdin.
The question asked is "is this gambling?": reply "OK" = yes/block,
"ERR" = no/allow. Same pod, so gateway is localhost:8080 by default
(override base URL with GATEWAY_API env, no trailing /check-dns).
Fail closed: any error blocks. Verdicts cached 300s.
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request

GATEWAY_API = os.environ.get("GATEWAY_API", "http://127.0.0.1:8080") + "/check-dns"
CACHE_TTL = 300

_cache = {}  # domain -> (is_gambling, timestamp)


def classify(domain, client_ip):
    now = time.time()
    hit = _cache.get(domain)
    if hit and now - hit[1] < CACHE_TTL:
        return hit[0]
    try:
        qs = urllib.parse.urlencode({"domain": domain, "client_ip": client_ip})
        req = urllib.request.Request(f"{GATEWAY_API}?{qs}", method="GET")
        with urllib.request.urlopen(req, timeout=3) as res:
            data = json.load(res)
        is_gambling = data.get("action") == "BLOCK"
    except Exception as ex:
        print(f"helper error for {domain}: {ex}", file=sys.stderr, flush=True)
        return True  # fail closed
    if len(_cache) > 10000:
        _cache.clear()
    _cache[domain] = (is_gambling, now)
    return is_gambling


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        domain = parts[0].split(":")[0].lower().rstrip(".")
        client_ip = parts[1] if len(parts) > 1 else "127.0.0.1"
        try:
            blocked = classify(domain, client_ip)
        except Exception:
            blocked = True
        sys.stdout.write("OK\n" if blocked else "ERR\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
