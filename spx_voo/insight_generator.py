# -*- coding: utf-8 -*-
"""Build explainable insight objects: What / Who / Where / Why / Impact / Action / Owner / Priority / Evidence.

Every sentence is tagged:
  FACT            measured directly from the data (with record / ticket ids)
  INFERENCE       the agent's interpretation (correlation-based, with a caveat)
  RECOMMENDATION  what to do next
No monetary or business impact is invented: impact only cites counted quantities.
"""
import pandas as pd

from .config import STAKEHOLDERS, drivers, priority_cfg, sub_issue_index
from .knowledge_checker import article_coverage
from .root_cause_analyzer import build_hypothesis


def pct(g):
    if g is None:
        return "n/a"
    if g == float("inf"):
        return "new"
    if abs(g) < 0.005:
        return "0%"
    return f"{g:+.0%}"


def _examples(voc, ids, per_stk=3):
    d = voc[voc["feedback_id"].isin(set(ids))].sort_values("timestamp", ascending=False)
    out = []
    for s in STAKEHOLDERS:
        for _, r in d[d["stakeholder_type"] == s].head(per_stk).iterrows():
            out.append({"feedback_id": r["feedback_id"], "stakeholder": s, "date": str(r["date"].date()),
                        "hub": r["hub"], "rating": None if pd.isna(r["rating"]) else int(r["rating"]),
                        "comment": r["comment"], "sub_issue": r["sub_issue"], "confidence": r["confidence"],
                        "matched_signal": r["matched_signal"], "classified_by": r["classified_by"],
                        "tracking_id": r["tracking_id"],
                        "hub_processing_hours": None if pd.isna(r.get("hub_processing_hours")) else round(float(r["hub_processing_hours"]), 1)})
    return out


def _tickets(tickets, ids, n=8):
    d = tickets[tickets["ticket_id"].isin(set(ids))].sort_values("created_time", ascending=False).head(n)
    return [{"ticket_id": r["ticket_id"], "stakeholder": r["stakeholder_type"], "created": str(r["created_time"])[:16],
             "first_response_h": None if pd.isna(r["first_response_hours"]) else round(float(r["first_response_hours"]), 1),
             "status": r["status"], "owner_team": r["owner_team"], "issue_type": r["issue_type"],
             "description": r["description"]} for _, r in d.iterrows()]


def _ops_events(ops, voc, record_ids, n=8):
    tids = voc[voc["feedback_id"].isin(set(record_ids))]["tracking_id"].tolist()
    d = ops[ops["tracking_id"].isin(set(tids)) & (ops["event_type"] == "sort_complete")]
    d = d.sort_values("processing_time", ascending=False).head(n)
    return [{"event_id": r["event_id"], "tracking_id": r["tracking_id"], "event_type": r["event_type"],
             "hub": r["hub"], "timestamp": str(r["timestamp"])[:16],
             "processing_time": None if pd.isna(r["processing_time"]) else round(float(r["processing_time"]), 1),
             "status": r["status"]} for _, r in d.iterrows()]


def _owner_line(dcfg):
    owners = []
    for a in dcfg.get("actions", []):
        if a["owner"] not in owners:
            owners.append(a["owner"])
    return owners


def driver_insight(a, voc, tickets, ops, hc, win, gaps):
    d = drivers()[a["driver"]]
    h = build_hypothesis(a)
    hub = a["location"]["top_hub"] or "network"
    region = a["location"]["top_region"] or ""
    stk = a["stakeholders"]
    sig = a["significant_stakeholders"]
    affected = sig if sig else [s for s, v in stk.items() if v["current"] > 0]
    o, p, s = a.get("ops"), a.get("parcel_link"), a["support"]
    comp = win.label
    stmts, evidence = [], []

    # ---------------- WHAT (fact)
    what = (f"{a['label']}-related negative VOC {'increased' if (a['growth'] or 0) > 0 else 'changed'} "
            f"{pct(a['growth'])} {comp} ({a['total_baseline']:.0f} → {a['total_current']})")
    stmts.append({"type": "FACT", "text": what + "."})
    evidence.append({"metric": f"Negative VOC linked to {a['label']}", "baseline": a["total_baseline"],
                     "current": a["total_current"], "change": pct(a["growth"]), "source": "customer/seller/rider_voc.csv",
                     "record_ids": a["current_record_ids"][:300]})
    for sname in STAKEHOLDERS:
        if sname not in stk:
            continue
        v = stk[sname]
        if v["current"] == 0 and v["baseline"] < 1:
            continue
        top_sub = ", ".join(list(v["sub_issues"])[:2]) or "—"
        stmts.append({"type": "FACT", "text": f"{sname}: {v['baseline']:.0f} → {v['current']} ({pct(v['growth'])}); "
                                              f"main signals: {top_sub}."})
        evidence.append({"metric": f"{sname} VOC ({top_sub})", "baseline": v["baseline"], "current": v["current"],
                         "change": pct(v["growth"]), "source": f"{sname.lower()}_voc.csv", "significant": v["significant"]})

    # ---------------- WHO / WHERE
    who = " + ".join(affected) if affected else "No stakeholder with significant change"
    loc = a["location"]
    where = (f"Concentrated at {hub} ({region}): {loc['top_hub_share_current']:.0%} of current VOC "
             f"vs {loc['top_hub_share_baseline']:.0%} in baseline")
    stmts.append({"type": "FACT", "text": where + "."})

    # ---------------- WHY (facts that support, then the inference)
    why_parts = []
    if o and o.get("change") is not None:
        t = (f"{o['label']} at {o['hub']}: {o['baseline']:.1f}{o['unit']} → {o['current']:.1f}{o['unit']} ({pct(o['change'])})"
             + (f"; other hubs {pct(o['control_change'])}" if o.get("control_change") is not None else ""))
        stmts.append({"type": "FACT", "text": t + "."})
        evidence.append({"metric": o["label"] + f" @ {o['hub']}", "baseline": round(o["baseline"], 2),
                         "current": round(o["current"], 2), "change": pct(o["change"]), "source": "operational_events.csv"
                         if d["ops_metric"]["source"] == "ops" else "support_tickets.csv"})
        if o.get("control_change") is not None:
            evidence.append({"metric": o["label"] + " @ all other hubs (control)", "baseline": round(o["control_baseline"], 2),
                             "current": round(o["control_current"], 2), "change": pct(o["control_change"]),
                             "source": "operational_events.csv"})
        if o.get("ops_first_date"):
            stmts.append({"type": "FACT", "text": f"Operational deterioration first detected on {o['ops_first_date']}; "
                                                  f"VOC spike first detected on {o.get('voc_first_date') or '—'}."})
        why_parts.append(f"{o['label']} at {o['hub']} {pct(o['change'])}")
    if p:
        stmts.append({"type": "FACT", "text": f"{p['above_p90']} of {p['linked']} linked complaint parcels ({p['share']:.0%}) "
                                              f"exceeded {p['hub']}'s normal p90 processing time of {p['p90_reference']:.1f}h "
                                              f"(baseline: {p['baseline_share'] or 0:.0%})."})
        evidence.append({"metric": "Complaint parcels above hub p90 processing time", "baseline": f"{p['baseline_share'] or 0:.0%}",
                         "current": f"{p['share']:.0%}", "change": f"{p['above_p90']}/{p['linked']} parcels",
                         "source": "operational_events.csv × VOC tracking_id", "record_ids": p["record_ids"]})
        why_parts.append(f"{p['share']:.0%} of complaint parcels delayed at hub")
    stmts.append({"type": "INFERENCE", "text": h["statement"] + f" (confidence {h['confidence']}, "
                                                               f"{h['checks_passed']}/5 evidence checks passed)."})
    why = (h["statement"] + (" — " + "; ".join(why_parts) if why_parts else "")) if h["kind"] != "monitor" else \
        "No significant change — monitor"

    # ---------------- IMPACT (counted, not invented)
    imp = []
    for sname, v in stk.items():
        if v["current"]:
            imp.append(f"{v['current']} {sname.lower()} complaints")
    if s["tickets_current"]:
        imp.append(f"{s['tickets_current']} related tickets at {hub} (baseline {s['tickets_baseline']:.0f})")
    if s["repeat_contact_stakeholders"]:
        imp.append(f"{s['repeat_contact_stakeholders']} stakeholders contacted support ≥2 times")
    if s["tickets_current"] >= 5:
        imp.append(f"{s['sla_breach_current']:.0%} of related tickets breached the "
                   f"{priority_cfg()['sla_first_response_hours']}h first-response SLA (baseline {s['sla_breach_baseline']:.0%})")
    impact = "; ".join(imp)
    if s["tickets_current"]:
        evidence.append({"metric": f"Related tickets @ {hub}", "baseline": s["tickets_baseline"], "current": s["tickets_current"],
                         "change": f"SLA breach {s['sla_breach_baseline']:.0%} → {s['sla_breach_current']:.0%}; "
                                   f"repeat contacts {s['repeat_contact_stakeholders']}",
                         "source": "support_tickets.csv", "ticket_ids": s["ticket_ids"]})

    # ---------------- ACTIONS
    fmt = {"hub": hub, "ops_first_date": (o or {}).get("ops_first_date") or win.cur_start.date()}
    actions = [{"owner": x["owner"], "action": x["action"].format(**fmt)} for x in d.get("actions", [])]
    if h["kind"] == "monitor":
        actions = [{"owner": d["owner"], "action": f"Monitor {a['label']} volume; no action unless it rises"}]
    elif h["kind"] == "emerging_trend":
        actions = actions[:1]
    for x in actions:
        stmts.append({"type": "RECOMMENDATION", "text": f"[{x['owner']}] {x['action']}"})

    # ---------------- Help Center context
    subs = sorted({x for v in d["voc_signals"].values() for x in v})
    articles = []
    for sub in subs:
        for art in article_coverage(hc, sub, win.cur_end):
            articles.append({**art, "sub_issue": sub})
    rel_gaps = [g for g in gaps if g["sub_issue"] in subs]
    if any(a2["stale"] for a2 in articles if a2["sub_issue"] in [x for v in d["voc_signals"].values() for x in v]):
        stale = [a2 for a2 in articles if a2["stale"]]
        stmts.append({"type": "FACT", "text": "Related Help Center guidance is outdated: " + "; ".join(
            f"{a2['article_id']} last updated {a2['last_updated']} ({a2['age_days']} days)" for a2 in stale) + "."})

    order = {"FACT": 0, "INFERENCE": 1, "RECOMMENDATION": 2}
    stmts = sorted(stmts, key=lambda x: order[x["type"]])

    # ---------------- drilldown
    cur_ids = a["current_record_ids"]
    dist = voc[voc["feedback_id"].isin(set(cur_ids))].groupby(["stakeholder_type", "sub_issue"]).size()
    drill = {
        "examples": _examples(voc, cur_ids),
        "issue_distribution": [{"stakeholder": k[0], "sub_issue": k[1], "count": int(v)} for k, v in dist.items()],
        "hubs": a["location"]["hubs"][:8], "regions": a["location"]["regions"],
        "tickets": _tickets(tickets, s["ticket_ids"]),
        "ops_events": _ops_events(ops, voc, (p or {}).get("record_ids", cur_ids)) if o else [],
        "ops_daily_hub": (o or {}).get("daily_hub", {}), "ops_daily_control": (o or {}).get("daily_control", {}),
        "help_articles": articles, "knowledge_gaps": rel_gaps,
        "checks": h["checks"], "priority_reasons": h["priority_reasons"], "caveat": h["caveat"],
        "daily": a["daily"], "daily_top_hub": a["daily_top_hub"],
        "stakeholder_meaning": {sname: sub_issue_index()[subs_[0]].get("stakeholder_meaning", {}).get(sname.lower(), "")
                                for sname, subs_ in d["voc_signals"].items()},
    }
    headline = {"cross_stakeholder": "Cross-stakeholder operational issue detected",
                "emerging_trend": f"{' + '.join(affected)} issue increasing",
                "monitor": "Stable — monitor"}[h["kind"]]
    return {
        "id": f"INS-{a['driver']}", "type": h["kind"], "headline": headline, "title": f"{a['label']} — {hub}",
        "driver": a["driver"], "potential_root_cause": a["label"], "root_cause_statement": h["statement"],
        "confidence": h["confidence"], "checks_passed": h["checks_passed"],
        "priority": h["priority"], "priority_label": priority_cfg()["labels"][h["priority"]],
        "priority_score": h["priority_score"], "priority_reasons": h["priority_reasons"],
        "owner": " · ".join(_owner_line(d)) if h["kind"] == "cross_stakeholder" else d["owner"],
        "affected_stakeholders": affected, "hub": hub, "region": region,
        "stakeholder_counts": {k: {"current": v["current"], "baseline": v["baseline"], "growth": pct(v["growth"]),
                                   "significant": v["significant"]} for k, v in stk.items()},
        "what": what, "who": who, "where": where, "why": why, "impact": impact,
        "recommended_actions": actions, "statements": stmts, "evidence": evidence, "drilldown": drill,
        "total_current": a["total_current"], "total_baseline": a["total_baseline"], "growth": pct(a["growth"]),
    }


def knowledge_insight(g, voc):
    art = g["article"]
    q = ""
    if g["question_share"]:
        q = (f"{g['question_share']:.0%} of {g['stakeholder'].lower()} {g['sub_issue'].lower()} complaints "
             f"({g['question_count']}/{g['volume']}, last {g['window_days']} days) ask \"{g['question_label']}\"")
    if art is None:
        gap = f"no Help Center article exists for {g['sub_issue']}"
    elif art["status"] == "Does not explain":
        gap = f"{art['article_id']} \"{art['title']}\" does not explain: {'; '.join(art['missing'])}"
    else:
        gap = f"{art['article_id']} \"{art['title']}\" was last updated {art['last_updated']} ({art['age_days']} days ago)"
    what = (q + ", but " + gap) if q else f"{g['volume']} {g['stakeholder'].lower()} complaints on {g['sub_issue']}, but {gap}"
    pr = "P2" if (g["question_share"] or 0) >= 0.25 or art is None else "P3"
    action = ("Update Help Center: add the next-step rule (" + "; ".join(art["missing"]) + ")"
              if art and art["missing"] else "Update Help Center: refresh and re-validate the article"
              if art else f"Create a Help Center article for {g['sub_issue']}")
    return {
        "id": f"KG-{g['stakeholder']}-{g['sub_issue']}".replace(" ", "_").replace("/", ""),
        "type": "knowledge_gap", "headline": "Knowledge Gap", "title": f"Help Center gap — {g['sub_issue']} ({g['stakeholder']})",
        "potential_root_cause": "Knowledge gap: " + (art["status"] if art else "Missing article"),
        "root_cause_statement": "Guidance gap likely drives repeat questions (inference from question share)",
        "confidence": "Medium" if q else "Low", "priority": pr, "priority_label": priority_cfg()["labels"][pr],
        "priority_reasons": [f"question share {g['question_share']:.0%}" if g["question_share"] else "article issue"],
        "owner": g["owner"], "affected_stakeholders": [g["stakeholder"]], "hub": "network", "region": "",
        "what": what[0].upper() + what[1:] + ".", "who": g["stakeholder"], "where": "Network-wide (Help Center)",
        "why": gap, "impact": f"{g['volume']} {g['stakeholder'].lower()} complaints in {g['window_days']} days on this topic",
        "recommended_actions": [{"owner": g["owner"], "action": action}],
        "statements": ([{"type": "FACT", "text": q + "."}] if q else []) + [
            {"type": "FACT", "text": gap[0].upper() + gap[1:] + "."},
            {"type": "INFERENCE", "text": f"Missing / unclear guidance is a potential driver of repeat {g['stakeholder'].lower()} questions and contacts."},
            {"type": "RECOMMENDATION", "text": f"[{g['owner']}] {action}."}],
        "evidence": [{"metric": f"{g['stakeholder']} complaints raising the question", "baseline": "",
                      "current": g["question_count"], "change": f"{(g['question_share'] or 0):.0%} of {g['volume']}",
                      "source": f"{g['stakeholder'].lower()}_voc.csv × help_center.csv", "record_ids": g["record_ids"]}],
        "drilldown": {"examples": _examples(voc, g["record_ids"], per_stk=6), "help_articles": [art] if art else [],
                      "checks": [], "knowledge_gaps": [g]},
        "total_current": g["volume"], "growth": "",
    }


def coverage_insight(gaps):
    """One consolidated P3 item for Help Center topics that are missing / outdated without question evidence."""
    missing = [g for g in gaps if g["article"] is None and g["volume"] >= 15]
    stale = [g for g in gaps if g["article"] is not None and g["article"]["status"] != "Covered"]
    if not missing and not stale:
        return None
    topics = sorted({f"{g['sub_issue']} ({g['stakeholder']})" for g in missing})
    arts = sorted({f"{g['article']['article_id']} {g['article']['status'].lower()}" for g in stale})
    what = []
    if topics:
        what.append(f"{len(topics)} complaint topics with ≥15 complaints in 28 days have no Help Center article: " + ", ".join(topics))
    if arts:
        what.append("Articles needing review: " + ", ".join(arts))
    stmts = [{"type": "FACT", "text": w + "."} for w in what] + [
        {"type": "RECOMMENDATION", "text": "[CS / SS] Review Help Center coverage in the next content sprint."}]
    return {"id": "KG-coverage", "type": "knowledge_gap", "headline": "Knowledge coverage", "title": "Help Center coverage review",
            "potential_root_cause": "Knowledge coverage gaps", "root_cause_statement": "Coverage gaps (no question-level evidence yet)",
            "confidence": "Low", "priority": "P3", "priority_label": priority_cfg()["labels"]["P3"],
            "priority_reasons": ["no question-level evidence → monitor"], "owner": "CS / SS",
            "affected_stakeholders": sorted({g["stakeholder"] for g in missing + stale}), "hub": "network", "region": "",
            "what": ". ".join(what) + ".", "who": ", ".join(sorted({g["stakeholder"] for g in missing + stale})),
            "where": "Help Center", "why": "Guidance missing or outdated", "impact": f"{sum(g['volume'] for g in missing + stale)} complaints on these topics (28 days)",
            "recommended_actions": [{"owner": "CS / SS", "action": "Review Help Center coverage for: " + ", ".join(topics + arts)}],
            "statements": stmts, "evidence": [{"metric": f"{g['sub_issue']} ({g['stakeholder']})", "baseline": "",
                                               "current": g["volume"], "change": g["status"], "source": "help_center.csv"}
                                              for g in (missing + stale)[:12]],
            "drilldown": {"examples": [], "help_articles": [g["article"] for g in stale], "checks": [], "knowledge_gaps": missing + stale},
            "total_current": sum(g["volume"] for g in missing + stale), "growth": "", "priority_score": 0}


def generate(analyses, voc, tickets, ops, hc, win, gaps):
    ins = [driver_insight(a, voc, tickets, ops, hc, win, gaps) for a in analyses.values()]
    ins = [i for i in ins if i["type"] != "monitor" or i["total_current"] >= 15]
    ins += [knowledge_insight(g, voc) for g in gaps if (g["question_share"] or 0) >= 0.2]
    cov = coverage_insight([g for g in gaps if (g["question_share"] or 0) < 0.2])
    if cov:
        ins.append(cov)
    rank = {"P1": 0, "P2": 1, "P3": 2}
    kind = {"cross_stakeholder": 0, "emerging_trend": 1, "knowledge_gap": 2, "monitor": 3}
    return sorted(ins, key=lambda i: (rank[i["priority"]], kind[i["type"]], -i.get("priority_score", 0)))
