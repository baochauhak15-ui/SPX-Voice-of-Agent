# -*- coding: utf-8 -*-
"""End-to-end orchestration:

Data Loader → Data Cleaner → Journey/Ticket Linker → Rule Classifier → (LLM on candidates)
→ Cross-stakeholder Analyzer → Root-cause Analyzer → Knowledge Checker → Insight Generator → Actions
"""
import os
import time
from datetime import datetime

import pandas as pd

from . import action_generator, insight_generator, knowledge_checker
from .config import STAKEHOLDERS
from .cross_stakeholder_analyzer import analyze_all, emerging_issues, growth, make_window
from .data_cleaner import clean
from .data_loader import load_all
from .linker import link
from .llm_classifier import apply_llm
from .voc_classifier import classify_frame


def classify_data(data_dir, llm_provider=None, verbose=True):
    t0 = time.time()
    voc, tickets, ops, hc, dq = clean(load_all(data_dir))
    voc = link(voc, tickets, ops)
    voc = classify_frame(voc)
    voc, llm_stats = apply_llm(voc, provider=llm_provider, verbose=verbose)
    stats = {"seconds": round(time.time() - t0, 2), "records": len(voc),
             "by_confidence": voc["confidence"].value_counts().to_dict(),
             "by_classified_by": voc["classified_by"].value_counts().to_dict(),
             "human_review": int(voc["human_review_flag"].sum()),
             "llm": llm_stats, "llm_reasons": voc.loc[voc["llm_candidate"], "llm_reason"].str.split(",").explode()
             .value_counts().to_dict()}
    gt_path = os.path.join(data_dir, "_ground_truth.csv")
    if os.path.exists(gt_path):                      # synthetic data ships labels -> measure the rule layer honestly
        gt = pd.read_csv(gt_path)
        m = voc.merge(gt, on="feedback_id")
        neg = m[m["true_sub_issue"] != "Positive"]
        stats["eval"] = {"labelled_negative": int(len(neg)),
                         "sub_issue_accuracy": round(float((neg["sub_issue"] == neg["true_sub_issue"]).mean()), 3),
                         "note": "accuracy of the final label vs synthetic ground truth (primary sub-issue)"}
    return voc, tickets, ops, hc, dq, stats


def _stakeholder_block(voc, win):
    out = {}
    for s in STAKEHOLDERS:
        v = voc[voc["stakeholder_type"] == s]
        c, b = v[win.cur(v["date"])], v[win.base(v["date"])]
        cn, bn = c[c["is_negative"]], b[b["is_negative"]]
        top = cn[cn["issue_group"] != "Other"]["sub_issue"].value_counts()
        out[s] = {"total": int(len(c)), "negative": int(len(cn)), "negative_baseline": round(len(bn) * win.scale, 1),
                  "negative_growth": growth(len(cn), len(bn) * win.scale),
                  "negative_rate": round(len(cn) / max(len(c), 1), 3),
                  "avg_rating": round(float(c["rating"].mean()), 2) if len(c) else None,
                  "top_issue": top.index[0] if len(top) else "—",
                  "top_issues": top.head(5).to_dict()}
    return out


def _daily(voc):
    neg = voc[voc["is_negative"]]
    d = neg.groupby(["date", "stakeholder_type"]).size().unstack(fill_value=0).reindex(columns=STAKEHOLDERS, fill_value=0)
    tot = voc.groupby("date").size()
    return [{"date": str(k.date()), **{s: int(r[s]) for s in STAKEHOLDERS}, "total": int(tot.get(k, 0))}
            for k, r in d.iterrows()]


def analyze(voc, tickets, ops, hc, mode="weekly", end_date=None):
    end_date = end_date or voc["date"].max()
    win = make_window(end_date, mode)
    an = analyze_all(voc, tickets, ops, win)
    gaps = knowledge_checker.check(voc, hc, win.cur_end)
    insights = insight_generator.generate(an, voc, tickets, ops, hc, win, gaps)
    actions = action_generator.build(insights)
    em = emerging_issues(voc, win)
    cur = voc[win.cur(voc["date"])]
    neg = cur[cur["is_negative"]]
    base_neg = voc[win.base(voc["date"]) & voc["is_negative"]]
    top_issue = neg[neg["issue_group"] != "Other"]["sub_issue"].value_counts()
    increasing = [e for e in em if any(v["significant"] for v in e["stakeholders"].values())]
    kpis = {
        "total_voc": int(len(cur)), "negative_voc": int(len(neg)),
        "negative_rate": round(len(neg) / max(len(cur), 1), 3),
        "negative_baseline": round(len(base_neg) * win.scale, 1),
        "negative_growth": growth(len(neg), len(base_neg) * win.scale),
        "top_issue": top_issue.index[0] if len(top_issue) else "—",
        "top_issue_count": int(top_issue.iloc[0]) if len(top_issue) else 0,
        "issues_increasing": len(increasing),
        "cross_stakeholder_issues": sum(1 for i in insights if i["type"] == "cross_stakeholder"),
        "high_priority": sum(1 for i in insights if i["priority"] == "P1"),
        "p2": sum(1 for i in insights if i["priority"] == "P2"),
    }
    return {"window": win.as_dict(), "win": win, "kpis": kpis, "stakeholders": _stakeholder_block(voc, win),
            "emerging": em, "insights": insights, "knowledge_gaps": gaps, "actions": actions, "analyses": an,
            "daily": _daily(voc)}


def run(data_dir, out_dir, modes=("weekly",), llm_provider=None, verbose=True):
    voc, tickets, ops, hc, dq, stats = classify_data(data_dir, llm_provider, verbose)
    os.makedirs(out_dir, exist_ok=True)
    results = {m: analyze(voc, tickets, ops, hc, m) for m in modes}
    meta = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "data_dir": os.path.relpath(data_dir),
            "data_quality": dq, "classification": stats}
    return voc, tickets, ops, hc, results, meta
