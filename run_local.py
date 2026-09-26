# -*- coding: utf-8 -*-
"""SPX Voice of Operations Agent — local runner.

    python run_local.py --mode demo                 # generate synthetic data (if missing) + everything
    python run_local.py --mode weekly               # one report
    python run_local.py --mode all --llm mock       # exercise the LLM layer offline
    LLM_PROVIDER=openai LLM_API_KEY=... python run_local.py --mode demo
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "scripts"))

from spx_voo import dashboard, pipeline, report_generator  # noqa: E402
from spx_voo.config import DEFAULT_DATA_DIR, DEFAULT_OUT_DIR  # noqa: E402
from spx_voo.dashboard import jsonable  # noqa: E402

MODES = {"demo": ("daily", "weekly", "monthly"), "all": ("daily", "weekly", "monthly"),
         "daily": ("daily", "weekly"), "weekly": ("weekly",), "monthly": ("monthly",)}


def banner(ins):
    top = next((i for i in ins if i["type"] == "cross_stakeholder"), None)
    if not top:
        print("\nNo cross-stakeholder issue detected in this window.")
        return
    sc = top["stakeholder_counts"]
    ops = next((e for e in top["evidence"] if "@" in e["metric"] and "control" not in e["metric"]), None)
    print("\n" + "=" * 78)
    print("  ⚠  CROSS-STAKEHOLDER OPERATIONAL ISSUE DETECTED")
    print("=" * 78)
    print(f"  Potential root cause : {top['potential_root_cause']} ({top['hub']})")
    print(f"  Confidence / priority: {top['confidence']} ({top['checks_passed']}/5 checks) · {top['priority']} {top['priority_label']}")
    print("  Affected             : " + " · ".join(f"{s} {v['growth']}" for s, v in sc.items() if v["significant"]))
    if ops:
        print(f"  Ops signal           : {ops['metric']}: {ops['baseline']} → {ops['current']} ({ops['change']})")
    for a in top["recommended_actions"]:
        print(f"  Action [{a['owner']:<10}] : {a['action'][:110]}")
    print("  Note                 : correlational evidence — 'likely driver', not proven causality")
    print("=" * 78)


def main():
    ap = argparse.ArgumentParser(description="SPX Voice of Operations Agent")
    ap.add_argument("--mode", default="demo", choices=list(MODES))
    ap.add_argument("--data", default=DEFAULT_DATA_DIR)
    ap.add_argument("--out", default=DEFAULT_OUT_DIR)
    ap.add_argument("--llm", default=None, choices=["none", "openai", "mock"],
                    help="LLM provider for Layer 2 (default: env LLM_PROVIDER or none)")
    ap.add_argument("--regenerate", action="store_true", help="re-create synthetic data")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    t0 = time.time()
    if a.regenerate or not os.path.exists(os.path.join(a.data, "customer_voc.csv")):
        from generate_synthetic_data import generate
        print(f"[1/5] Generating synthetic SPX data → {os.path.relpath(a.data)}")
        for k, v in generate(a.data, a.seed).items():
            print(f"      {k:<20} {v:>7,}")
    else:
        print(f"[1/5] Using data in {os.path.relpath(a.data)}")

    modes = MODES[a.mode]
    print("[2/5] Clean → link → classify (rules on 100%, LLM on flagged records only)")
    voc, tickets, ops, hc, results, meta = pipeline.run(a.data, a.out, modes, llm_provider=a.llm)
    c = meta["classification"]
    print(f"      {c['records']:,} records · confidence {c['by_confidence']} · LLM candidates {c['llm']['candidates']} "
          f"(provider={c['llm']['provider']}, applied={c['llm']['applied']})"
          + (f" · label accuracy vs synthetic truth {c['eval']['sub_issue_accuracy']:.1%}" if c.get("eval") else ""))

    print("[3/5] Cross-stakeholder analysis → root-cause hypotheses → insights")
    for m in modes:
        r = results[m]
        print(f"      {m:<8} {r['window']['current'][0]}→{r['window']['current'][1]}: "
              + ", ".join(f"{i['priority']} {i['title']}" for i in r["insights"][:4]))

    print("[4/5] Writing outputs")
    os.makedirs(a.out, exist_ok=True)
    written = []
    main_res = results.get("weekly") or results[modes[0]]
    if a.mode in ("demo", "all", "weekly"):
        written.append(dashboard.write(main_res, meta, a.out))
    for m in modes:
        if a.mode == "daily" and m == "weekly":
            continue
        written.append(report_generator.write_report(m, results[m], meta, voc, a.out,
                                                     context=results.get("weekly") if m == "daily" else None))
    written += report_generator.write_action_list(main_res["actions"], a.out)
    cols = ["feedback_id", "stakeholder_type", "stakeholder_id", "timestamp", "rating", "comment", "issue_type", "region",
            "hub", "tracking_id", "issue_group", "sub_issue", "secondary_issues", "priority", "owner", "confidence",
            "matched_signal", "reason", "human_review_flag", "is_negative", "llm_candidate", "llm_reason", "llm_status",
            "classified_by", "ticket_id", "hub_processing_hours"]
    p = os.path.join(a.out, "voc_classified.csv")
    voc[cols].to_csv(p, index=False, encoding="utf-8-sig")
    written.append(p)
    p = os.path.join(a.out, "insights.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(jsonable({"window": main_res["window"], "kpis": main_res["kpis"], "insights": main_res["insights"],
                            "knowledge_gaps": main_res["knowledge_gaps"], "meta": meta}), f, ensure_ascii=False, indent=1)
    written.append(p)
    for w in written:
        print(f"      ✓ {os.path.relpath(w)}")

    print(f"[5/5] Done in {time.time() - t0:.1f}s")
    banner(main_res["insights"])
    if a.mode in ("demo", "all", "weekly"):
        print(f"\nOpen the dashboard: {os.path.relpath(written[0])}   (or: python app.py)")


if __name__ == "__main__":
    main()
