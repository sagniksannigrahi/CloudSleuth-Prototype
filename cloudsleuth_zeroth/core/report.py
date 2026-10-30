"""Turn a diagnosis result into a short plain-text report."""


def as_text(r, top_n=6):
    lines = [f"=== CloudSleuth-Zeroth-Prototype diagnosis: case {r['case_id']} ({r['source']}) ===",
             f"method: {r['method']}   database evidence: {'ON' if r['use_db_evidence'] else 'OFF'}"]
    if not r["incident"]:
        lines.append("Result: " + r.get("summary", "no incident"))
        return "\n".join(lines)
    if r["method"] != "D":
        lines.append("Ranking: " + ", ".join(x["node"] for x in r["ranking"]))
        return "\n".join(lines)

    lines.append(f"Anomaly onset: t={r['onset_s']}s   persistent anomalies: {len(r['anomalies'])}")
    lines.append("")
    lines.append("Ranked likely causes:")
    for i, x in enumerate(r["ranking"][:top_n], 1):
        lines.append(f"  {i}. {x['node']:<10} raw score {x['raw_score']:>6.2f}")
    lines.append("")
    lines.append(f"Top cause:  {r['top_cause']}")
    lines.append(f"Fault type: {r['fault_type']}  (group: {r['fault_group']})")
    lines.append(f"Confidence: {r['raw_score']:.2f}  <- {r['confidence_note']}")
    lines.append("")
    rep = r["evidence_report"]
    lines.append(f"EVIDENCE REPORT for '{rep['cause']}'")
    lines.append("  Supporting:")
    for e in rep["support"] or [{"weight": 0, "text": "(none)"}]:
        lines.append(f"    + [{e['weight']:.1f}] {e['text']}")
    lines.append("  Contradicting:")
    for e in rep["contradict"] or [{"weight": 0, "text": "(none)"}]:
        lines.append(f"    - [{e['weight']:.1f}] {e['text']}")
    return "\n".join(lines)
