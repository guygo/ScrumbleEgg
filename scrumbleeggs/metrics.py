"""Real-time request metrics collector for the performance dashboard.

Maintains a 60-second rolling window of per-second buckets.
Thread-safe via a single lock. Zero external dependencies.
"""
import threading
from collections import defaultdict, deque
from math import floor
from time import time


class MetricsCollector:
    """Collects per-request metrics and exposes time-series data.

    Keeps a 60-second rolling window of per-second buckets, plus
    lifetime per-endpoint statistics (last 2000 samples each).

    Args:
        window: Rolling window size in seconds (default 60).
    """

    def __init__(self, window: int = 60) -> None:
        self._window = window
        self._lock = threading.Lock()
        self._buckets: deque = deque(maxlen=window)
        self._current_ts: int = int(time())
        self._current: dict = self._empty_bucket(self._current_ts)
        # endpoint -> {count, total_ms, samples[]}
        self._endpoints: dict = defaultdict(lambda: {"count": 0, "total_ms": 0.0, "samples": []})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(self, path: str, status: int, duration_ms: float) -> None:
        """Record a single completed request.

        Args:
            path: URL path (e.g. '/api/board').
            status: HTTP status code.
            duration_ms: Request duration in milliseconds.
        """
        with self._lock:
            self._advance(int(time()))
            b = self._current
            b["req_count"] += 1
            b["latencies"].append(duration_ms)
            if status < 400:
                b["status_2xx"] += 1
            elif status < 500:
                b["status_4xx"] += 1
                b["error_count"] += 1
            else:
                b["status_5xx"] += 1
                b["error_count"] += 1

            ep = self._endpoints[path]
            ep["count"] += 1
            ep["total_ms"] += duration_ms
            ep["samples"].append(duration_ms)
            if len(ep["samples"]) > 2000:
                ep["samples"] = ep["samples"][-2000:]

    def timeseries(self) -> dict:
        """Return the full time-series payload for the dashboard.

        Returns:
            dict with keys: buckets, endpoints, summary.
        """
        with self._lock:
            self._advance(int(time()))  # flush any idle gap

            # Seal a snapshot of the current (in-progress) bucket
            snap = dict(self._current)
            lats = sorted(snap.pop("latencies", []))
            snap["latency_p50"] = _pct(lats, 50)
            snap["latency_p95"] = _pct(lats, 95)
            snap["latency_p99"] = _pct(lats, 99)

            buckets = list(self._buckets) + [snap]

            endpoints = {}
            for path, data in sorted(self._endpoints.items()):
                samples = sorted(data["samples"])
                n = len(samples)
                endpoints[path] = {
                    "count": data["count"],
                    "avg_ms": round(data["total_ms"] / n, 2) if n else 0,
                    "p95_ms": round(_pct(samples, 95), 2),
                    "p99_ms": round(_pct(samples, 99), 2),
                }

            # Summary over the last 10 seconds
            recent = buckets[-10:] if len(buckets) >= 10 else buckets
            total_reqs = sum(b["req_count"] for b in recent)
            total_errs = sum(b["error_count"] for b in recent)
            p95_vals   = [b["latency_p95"] for b in recent if b["latency_p95"] > 0]

            lifetime_reqs = sum(b["req_count"] for b in buckets)

            return {
                "window_seconds": self._window,
                "buckets": buckets,
                "endpoints": endpoints,
                "summary": {
                    "rps":            round(total_reqs / max(len(recent), 1), 2),
                    "error_rate_pct": round(total_errs / max(total_reqs, 1) * 100, 2),
                    "p95_ms":         round(max(p95_vals) if p95_vals else 0, 2),
                    "total_requests": lifetime_reqs,
                },
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _empty_bucket(ts: int) -> dict:
        return {
            "ts": ts,
            "req_count": 0,
            "error_count": 0,
            "latencies": [],
            "latency_p50": 0.0,
            "latency_p95": 0.0,
            "latency_p99": 0.0,
            "status_2xx": 0,
            "status_4xx": 0,
            "status_5xx": 0,
        }

    def _seal(self, bucket: dict) -> dict:
        """Compute percentiles from raw latency list and remove it."""
        lats = sorted(bucket.pop("latencies", []))
        bucket["latency_p50"] = _pct(lats, 50)
        bucket["latency_p95"] = _pct(lats, 95)
        bucket["latency_p99"] = _pct(lats, 99)
        return bucket

    def _advance(self, now: int) -> None:
        """Advance the current bucket to `now`, filling gaps with empty buckets."""
        if now == self._current_ts:
            return
        # Seal the current bucket
        self._buckets.append(self._seal(self._current))
        # Fill any idle gap (server received no requests for several seconds)
        gap = min(now - self._current_ts - 1, self._window - 1)
        for i in range(1, gap + 1):
            self._buckets.append(self._empty_bucket(self._current_ts + i))
        self._current_ts = now
        self._current = self._empty_bucket(now)


def _pct(sorted_list: list, p: int) -> float:
    """Return the p-th percentile of a pre-sorted list."""
    if not sorted_list:
        return 0.0
    idx = min(floor(len(sorted_list) * p / 100), len(sorted_list) - 1)
    return round(sorted_list[idx], 2)
