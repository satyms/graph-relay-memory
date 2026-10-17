"""
Lease reaper: re-opens tasks whose lease has expired.

Run as a background worker (e.g. every 10s via cron or asyncio.sleep loop).
Usage: python -m server.app.reaper [--once]
       or import run_reaper() and call from an async loop.

shortcut: no per-graph discovery; caller must pass graph names, when multi-tenant reaper is needed.
"""
import argparse
import time
import logging
from typing import List

from server.app.queries.coordination import reap_expired_leases

log = logging.getLogger("reaper")


def run_reaper(graph_names: List[str]) -> int:
    """Reap expired leases across given graphs. Returns total reaped count."""
    total = 0
    for gn in graph_names:
        try:
            n = reap_expired_leases(gn)
            if n:
                log.info("reaped %d task(s) from %s", n, gn)
            total += n
        except Exception as exc:
            log.warning("reaper error on %s: %s", gn, exc)
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Relay lease reaper")
    parser.add_argument("--graphs", nargs="+", required=True, help="Graph names to reap")
    parser.add_argument("--interval", type=int, default=10, help="Seconds between sweeps")
    parser.add_argument("--once", action="store_true", help="Run one sweep then exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    log.info("reaper started, watching: %s", args.graphs)

    while True:
        run_reaper(args.graphs)
        if args.once:
            break
        time.sleep(args.interval)
