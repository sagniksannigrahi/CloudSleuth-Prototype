"""Step 1: anomaly detection with median / MAD.

For each metric series:
  * the first third of the window is the "normal" reference period
  * robust centre = median, robust spread = MAD (median absolute deviation)
  * score of a point  z = (value - median) / spread
  * a point is unusual if z goes past the threshold in the bad direction
  * the SERIES is anomalous only if it stays unusual for MIN_RUN readings in a
    row, so a single spike is ignored.
Missing points (None) are skipped: they neither break nor extend a run.
Two extra signals: a service that stops reporting all its metrics, and a
service that keeps restarting (from its logs).
"""

from dataclasses import dataclass
from statistics import median

Z_THRESHOLD = 4.0
MIN_RUN = 3               # readings in a row that must be unusual
BASELINE_FRACTION = 1 / 3

# Which direction is "bad" for each metric, and the smallest spread we allow
# (stops a perfectly flat baseline from turning tiny wiggles into alerts).
METRIC_RULES = {
    "latency_p95_ms":     ("up", 5.0),
    "error_rate":         ("up", 0.01),
    "rps":                ("down", 2.0),
    "cpu":                ("up", 0.05),
    "memory_mb":          ("up", 5.0),
    "lock_waits":         ("up", 1.0),
    "active_connections": ("up", 1.5),
    "mean_query_ms":      ("up", 1.0),
    "max_tx_duration_s":  ("up", 1.0),
    "db_cpu":             ("up", 0.05),
}


@dataclass
class Anomaly:
    node: str            # service name, or the database name
    metric: str
    onset: int           # index of the first point of the unusual run
    peak_z: float        # largest score after the onset
    fraction: float      # share of points after onset that are unusual
    baseline: float      # median in the reference period
    peak_value: float


def baseline_end(n_points):
    return max(5, int(n_points * BASELINE_FRACTION))


def robust_stats(values, min_spread):
    """Median and MAD-based spread (scaled to match a std-dev for normal data)."""
    vals = [v for v in values if v is not None]
    if len(vals) < 3:
        return None, None
    med = median(vals)
    mad = median(abs(v - med) for v in vals) * 1.4826
    return med, max(mad, min_spread, 0.05 * abs(med))


def zscores(series, metric):
    """Score of every point against the reference period (None stays None)."""
    direction, min_spread = METRIC_RULES.get(metric, ("up", 1.0))
    med, spread = robust_stats(series[: baseline_end(len(series))], min_spread)
    if med is None:
        return None, None
    sign = 1 if direction == "up" else -1
    return [None if v is None else sign * (v - med) / spread for v in series], med


def detect(series, metric, node):
    """Return an Anomaly if the series stays unusual for MIN_RUN readings."""
    z, med = zscores(series, metric)
    if z is None:
        return None
    start = baseline_end(len(series))
    run, onset = 0, None
    for i in range(start, len(z)):
        if z[i] is None:
            continue
        if z[i] > Z_THRESHOLD:
            run += 1
            if run == 1:
                first = i
            if run >= MIN_RUN:
                onset = first
                break
        else:
            run = 0
    if onset is None:
        return None
    after = [(v, s) for v, s in zip(z[onset:], series[onset:]) if v is not None]
    unusual = [v for v, _ in after if v > Z_THRESHOLD]
    peak_z, peak_value = max(after)
    return Anomaly(node, metric, onset, round(peak_z, 1), round(len(unusual) / len(after), 2),
                   round(med, 3), round(peak_value, 3))


def detect_missing(series, node):
    """Telemetry that keeps disappearing after being present (crash / down).

    Needs at least two missing readings in a row (one lost scrape is normal)
    and at least 15% of the readings after that point missing.
    """
    start = baseline_end(len(series))
    if sum(v is None for v in series[:start]) > start / 2:
        return None                                    # never really present
    for i in range(start, len(series) - 1):
        if series[i] is None and series[i + 1] is None:
            rest = series[i:]
            missing = sum(v is None for v in rest) / len(rest)
            if missing >= 0.15 and sum(v is None for v in rest) >= MIN_RUN:
                return Anomaly(node, "missing_data", i, 0.0, round(missing, 2), 0.0, 0.0)
    return None


def detect_restarts(logs, node, n_points, interval_s):
    """A service that restarts 2+ times after the reference period (from its logs).
    Fast crash loops can be too short to move any metric for 3 readings."""
    start_s = baseline_end(n_points) * interval_s
    restarts = lambda e: e["service"] == node and "service starting" in e["msg"]  # noqa: E731
    before = [e for e in logs if restarts(e) and e["t"] < start_s]
    after = [e for e in logs if restarts(e) and e["t"] >= start_s]
    if len(after) >= 2 and len(after) > len(before):
        return Anomaly(node, "restarts", int(after[0]["t"] // interval_s), 0.0, 1.0,
                       float(len(before)), float(len(after)))
    return None


def scan(snapshot):
    """Run detection on every metric of every node. Returns a list of Anomaly."""
    found = []
    for node, series_by_metric in snapshot["metrics"].items():
        for metric, series in series_by_metric.items():
            a = detect(series, metric, node)
            if a:
                found.append(a)
        # A service that stops reporting ALL its metrics at once (crash / down)
        # is also a signal. One metric missing is just a lost scrape.
        series = list(series_by_metric.values())
        if series:
            present = [None if all(s[i] is None for s in series) else 1.0 for i in range(len(series[0]))]
            m = detect_missing(present, node)
            if m:
                found.append(m)
        r = detect_restarts(snapshot["logs"], node, snapshot["steps"], snapshot["interval_s"])
        if r:
            found.append(r)
    return found
