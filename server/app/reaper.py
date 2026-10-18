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
from typing import Any, Dict, List

from server.app.queries.coordination import reap_expired_leases, reap_expired_leases_detailed

log = logging.getLogger("reaper")


def run_reaper(graph_names: List[str]) -> int:
    """Reap expired leases across given graphs. Returns total reaped count."""
    detailed = run_reaper_detailed(graph_names)
    return sum(len(tasks) for tasks in detailed.values())


def run_reaper_detailed(graph_names: List[str]) -> Dict[str, List[Dict]]:
    """Reap expired leases across given graphs. Returns dict of graph_name -> list of reaped tasks."""
    res = {}
    for gn in graph_names:
        try:
            reaped = reap_expired_leases_detailed(gn)
            if reaped:
                log.info("reaped %d task(s) from %s: %s", len(reaped), gn, [t["task_id"] for t in reaped])
            res[gn] = reaped
        except Exception as exc:
            log.warning("reaper error on %s: %s", gn, exc)
            res[gn] = []
    return res


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
