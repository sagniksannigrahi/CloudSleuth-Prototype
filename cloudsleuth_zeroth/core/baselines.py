"""Two simple baselines to compare method D against.

loudest_alert: blame the service whose latency or error rate jumped the most
               (the "loudest alert" an on-call engineer would see first).
random_guess:  a random order of the candidates (fixed seed per case, so the
               result is repeatable).
"""

import random

from .anomaly import baseline_end, zscores


def loudest_alert(view):
    loudness = {}
    for s in view["services"]:
        best = 0.0
        for metric in ("latency_p95_ms", "error_rate"):
            series = view["metrics"].get(s, {}).get(metric)
            if not series:
                continue
            z, _ = zscores(series, metric)
            after = [v for v in (z or [])[baseline_end(len(series)):] if v is not None]
            best = max([best] + after)
        loudness[s] = round(best, 1)
    order = sorted(loudness, key=lambda s: (-loudness[s], s))
    return [{"node": s, "raw_score": loudness[s]} for s in order]


def random_guess(view):
    order = list(view["candidates"])
    random.Random(view["case_id"]).shuffle(order)
    return [{"node": s, "raw_score": None} for s in order]
