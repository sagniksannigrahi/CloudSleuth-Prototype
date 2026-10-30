from cloudsleuth_zeroth.core.anomaly import detect, detect_missing


def flat(n=60, v=100.0):
    return [v + (i % 3) for i in range(n)]


def test_single_spike_is_ignored():
    s = flat()
    s[40] = 5000                                    # one reading only
    assert detect(s, "latency_p95_ms", "x") is None


def test_sustained_shift_is_found():
    s = flat()
    for i in range(35, 60):
        s[i] = 900
    a = detect(s, "latency_p95_ms", "x")
    assert a is not None and a.onset == 35


def test_missing_points_do_not_break_a_run():
    s = flat()
    for i in range(35, 60):
        s[i] = 900
    s[36] = None
    assert detect(s, "latency_p95_ms", "x").onset == 35


def test_rps_drop_counts_as_bad_direction():
    s = flat(v=20.0)
    for i in range(30, 60):
        s[i] = 2.0
    assert detect(s, "rps", "x") is not None


def test_service_disappearing_is_found():
    s = [1.0] * 30 + [None, None, 1.0, 1.0] * 7 + [1.0, 1.0]
    assert detect_missing(s, "x") is not None


def test_crash_loop_found_from_restart_logs():
    from cloudsleuth_zeroth.core.anomaly import detect_restarts
    logs = [{"t": t, "service": "payments", "msg": "service starting"} for t in (5, 150, 170, 190)]
    a = detect_restarts(logs, "payments", n_points=48, interval_s=5)
    assert a is not None and a.peak_value == 3      # the start-up at t=5 is not counted
    assert detect_restarts(logs[:2], "payments", 48, 5) is None   # one restart is not a loop
