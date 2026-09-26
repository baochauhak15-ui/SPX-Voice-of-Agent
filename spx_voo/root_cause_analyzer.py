# -*- coding: utf-8 -*-
"""Turn cross-stakeholder facts into root-cause HYPOTHESES with named, inspectable evidence checks.

Wording guard: we only have correlational evidence, so the output never says "caused by".
  High   -> "strong signal ... likely driver"
  Medium -> "potential root cause"
  Low    -> "possible driver, needs validation"
"""
from .config import priority_cfg, sub_issue_index


def _pct(g):
    return "0%" if g is not None and abs(g) < 0.005 else f"{g:+.0%}"

WORDING = {
    "High": "Strong signal: {label} at {hub} is the likely common driver",
    "Medium": "Potential root cause: {label} at {hub}",
    "Low": "Possible driver (needs validation): {label} at {hub}",
}
CAVEAT = "Evidence is correlational (same place, same time, same parcels) — not proven causality. Validate with the owning team."


def evidence_checks(a, cfg=None):
    cfg = cfg or priority_cfg()
    sig = a["significant_stakeholders"]
    checks = []
    checks.append({"check": "Multi-stakeholder", "passed": len(sig) >= 2, "applicable": True,
                   "detail": f"{len(sig)} stakeholder(s) with significant growth: {', '.join(sig) or 'none'}"})
    hubs = a["stakeholder_top_hubs"]
    shared = {h for h in hubs.values() if list(hubs.values()).count(h) >= 2}
    checks.append({"check": "Location overlap", "passed": bool(shared), "applicable": len(sig) >= 2,
                   "detail": ("Same top hub for " + ", ".join(s for s, h in hubs.items() if h in shared) + f": {', '.join(shared)}")
                   if shared else "No shared top hub across stakeholders"})
    o = a.get("ops")
    if o and o.get("change") is not None:
        ctl = o.get("control_change")
        localized = ctl is None or ctl < cfg["ops_corroboration_min_change"] / 2
        ok = o["change"] >= cfg["ops_corroboration_min_change"] and localized
        checks.append({"check": "Operational corroboration", "passed": bool(ok), "applicable": True,
                       "detail": f"{o['label']} at {o['hub']}: {o['baseline']:.1f}{o['unit']} → {o['current']:.1f}{o['unit']} "
                                 f"({_pct(o['change'])}); other hubs {_pct(ctl)}" if ctl is not None else ""})
        checks.append({"check": "Temporal alignment", "passed": bool(o.get("aligned")), "applicable": True,
                       "detail": f"ops deterioration first seen {o.get('ops_first_date') or '—'}; "
                                 f"VOC spike first seen {o.get('voc_first_date') or '—'}"})
    else:
        checks.append({"check": "Operational corroboration", "passed": False, "applicable": False,
                       "detail": "no operational metric configured for this driver"})
        checks.append({"check": "Temporal alignment", "passed": False, "applicable": False, "detail": "n/a"})
    p = a.get("parcel_link")
    if p:
        checks.append({"check": "Parcel-level link", "passed": p["share"] >= cfg["parcel_link_min_share"], "applicable": True,
                       "detail": f"{p['above_p90']}/{p['linked']} ({p['share']:.0%}) complaint parcels exceeded the hub's normal "
                                 f"p90 processing time ({p['p90_reference']:.1f}h); baseline {p['baseline_share'] or 0:.0%}"})
    else:
        checks.append({"check": "Parcel-level link", "passed": False, "applicable": False, "detail": "no parcel-level field"})
    return checks


def confidence_from(checks):
    n = sum(c["passed"] for c in checks)
    return ("High" if n >= 4 else "Medium" if n >= 2 else "Low"), n


def score_priority(a, cfg=None):
    """Return (P1|P2|P3, score, reasons[]) — every point is explained."""
    cfg = cfg or priority_cfg()
    pts, reasons = 0, []
    P = cfg["points"]

    def band(value, table, label, fmt):
        nonlocal pts
        for thr, p in table:
            if value is not None and value >= thr:
                pts += p
                reasons.append(f"+{p} {label} {fmt(value)} (≥ {fmt(thr)})")
                return

    band(a["total_current"], P["volume"], "volume", lambda v: f"{v:.0f}")
    g = a["growth"]
    band(99 if g == float("inf") else g, P["growth"], "growth", lambda v: f"{v:+.0%}")
    n = len(a["significant_stakeholders"])
    if P["stakeholders"].get(n, 0):
        pts += P["stakeholders"][n]
        reasons.append(f"+{P['stakeholders'][n]} {n} stakeholders affected")
    idx = sub_issue_index()
    from .config import drivers
    subs = {s for v in drivers()[a["driver"]]["voc_signals"].values() for s in v}
    sev = max(idx[s].get("severity", 0) for s in subs)
    band(sev, P["severity"], "operational severity", lambda v: f"{v:.0f}")
    loc = a["location"]
    if loc["top_hub_share_current"] >= 0.5 and loc["top_hub_share_current"] >= 2 * max(loc["top_hub_share_baseline"], 0.01):
        pts += P["concentration"]
        reasons.append(f"+{P['concentration']} concentrated at {loc['top_hub']} ({loc['top_hub_share_current']:.0%} vs "
                       f"{loc['top_hub_share_baseline']:.0%} baseline)")
    o = a.get("ops")
    if o and o.get("change") is not None and o["change"] >= cfg["ops_corroboration_min_change"]:
        pts += P["ops_corroborated"]
        reasons.append(f"+{P['ops_corroborated']} operational metric worsened {o['change']:+.0%}")
    s = a["support"]
    band(s["repeat_contact_stakeholders"], P["repeat_contacts"], "repeat-contact stakeholders", lambda v: f"{v:.0f}")
    if s["tickets_current"] >= 5:
        band(s["sla_breach_current"], P["sla_breach"], "SLA breach", lambda v: f"{v:.0%}")
    t = cfg["thresholds"]
    pr = "P1" if pts >= t["P1"] else "P2" if pts >= t["P2"] else "P3"
    return pr, pts, reasons


def build_hypothesis(a, cfg=None):
    checks = evidence_checks(a, cfg)
    conf, n = confidence_from(checks)
    sig = a["significant_stakeholders"]
    overlap = next(c for c in checks if c["check"] == "Location overlap")["passed"]
    # cross-stakeholder = >= 2 stakeholders rising AND pointing at the same hub; otherwise it is a trend
    kind = ("cross_stakeholder" if len(sig) >= 2 and overlap else
            "emerging_trend" if len(sig) >= 1 else "monitor")
    hub = a["location"]["top_hub"] or "network"
    pr, score, reasons = score_priority(a, cfg)
    if pr == "P1" and conf == "Low":
        pr = "P2"
        reasons.append("capped at P2: evidence confidence Low (needs validation before escalation)")
    if kind == "monitor":
        pr = "P3"
        reasons.append("no stakeholder with significant growth → monitor")
    return {"driver": a["driver"], "label": a["label"], "kind": kind, "confidence": conf,
            "checks_passed": n, "checks": checks, "statement": WORDING[conf].format(label=a["label"], hub=hub),
            "caveat": CAVEAT, "priority": pr, "priority_score": score, "priority_reasons": reasons}
