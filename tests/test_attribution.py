from cloudsleuth_zeroth.core.attribution import one_trace


def span(sid, parent, service, kind, start, dur, error=False, peer=None):
    return {"span_id": sid, "parent_id": parent, "service": service, "kind": kind,
            "start_ms": start, "duration_ms": dur, "error": error, "peer": peer}


def test_own_time_vs_waiting_time():
    # orders (100 ms) calls inventory via a client span (60 ms);
    # inventory works 20 ms itself and spends 30 ms in the database.
    spans = [
        span("a", None, "orders", "server", 0, 100),
        span("b", "a", "orders", "client", 10, 60, peer="inventory"),
        span("c", "b", "inventory", "server", 15, 50),
        span("d", "c", "inventory", "db", 20, 30, peer="postgres"),
    ]
    r = one_trace(spans, "postgres")
    assert r["orders"]["own_ms"] == 40          # 100 - 60 waiting on inventory
    assert r["orders"]["wait_ms"] == 60
    assert r["inventory"]["own_ms"] == 20       # 50 - 30 waiting on the DB
    assert r["postgres"]["own_ms"] == 30
    assert r["inventory"]["net_gap_ms"] == 10   # client 60 - server 50


def test_error_origin_and_unreachable():
    spans = [
        span("a", None, "gateway", "server", 0, 10, error=True),
        span("b", "a", "gateway", "client", 1, 5, error=True, peer="orders"),   # no answer
    ]
    r = one_trace(spans, "postgres")
    assert r["orders"]["unreachable"] == 1
    assert "errors_started" not in r["gateway"]  # gateway only passed the error on
