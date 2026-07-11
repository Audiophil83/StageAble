#!/usr/bin/env python3
"""Compare sequential vs parallel OSC round-trip latency against ShowAble Bridge."""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.osc_client import AbletonOSCClient, _TRANSPORT  # noqa: E402


def median_ms(samples: list[float]) -> float:
    return statistics.median(samples) * 1000.0


def bench_sequential(osc: AbletonOSCClient, iterations: int) -> list[float]:
    timings: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        osc.query("/live/song/get/current_song_time")
        osc.query("/live/song/get/is_playing")
        timings.append(time.perf_counter() - start)
    return timings


def bench_parallel(osc: AbletonOSCClient, iterations: int) -> list[float]:
    timings: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        osc.query_many([
            ("/live/song/get/current_song_time", ()),
            ("/live/song/get/is_playing", ()),
        ])
        timings.append(time.perf_counter() - start)
    return timings


def bench_transport_query(osc: AbletonOSCClient, iterations: int) -> tuple[list[float], bool]:
    """Time raw /live/song/get/transport queries (no client-side cache)."""
    timings: list[float] = []
    supported = False
    for _ in range(iterations):
        start = time.perf_counter()
        reply = osc.query(_TRANSPORT, warn_timeout=False)
        timings.append(time.perf_counter() - start)
        if reply is not None and len(reply) >= 5:
            supported = True
    return timings, supported


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--iterations", type=int, default=20)
    args = parser.parse_args()

    osc = AbletonOSCClient(host=args.host)
    osc.start()
    try:
        if not osc.is_connected():
            print("Bridge not reachable on 11000/11001", file=sys.stderr)
            return 1

        # Transport first — get_transport() caches unsupported after one probe.
        transport, transport_ok = bench_transport_query(osc, args.iterations)
        sequential = bench_sequential(osc, args.iterations)
        parallel = bench_parallel(osc, args.iterations)

        print(f"Iterations: {args.iterations}")
        if transport_ok:
            print(f"Transport batch:        median {median_ms(transport):.1f} ms")
        else:
            print(
                "Transport batch:        not available "
                "(reinstall bridge: python scripts/install_bridge.py)"
            )
        print(f"Sequential (2 queries): median {median_ms(sequential):.1f} ms")
        print(f"Parallel (2 queries):   median {median_ms(parallel):.1f} ms")
        return 0
    finally:
        osc.stop()


if __name__ == "__main__":
    raise SystemExit(main())
