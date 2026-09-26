# -*- coding: utf-8 -*-
"""Help Center as a knowledge source: does guidance exist, does it explain the issue, is it current?

For every sub-issue × stakeholder with enough negative VOC:
  * find articles for that issue_type
  * check the taxonomy's `must_explain` concepts against the article text
  * measure how many complaints raise the configured `question_patterns`
  * flag: Missing article | Does not explain | Outdated | Covered
"""
import re

import pandas as pd

from .config import STAKEHOLDERS, priority_cfg, sub_issue_index

MIN_VOLUME = 8


def _has(pattern, text):
    return re.search(rf"(?:^|\s)(?:{pattern})(?:$|\s)", text) is not None


def article_coverage(hc, sub, as_of, cfg=None):
    cfg = cfg or priority_cfg()
    meta = sub_issue_index()[sub]
    concepts = meta.get("must_explain") or []
    arts = hc[hc["issue_type"] == sub]
    out = []
    for _, a in arts.iterrows():
        covered = [c["label"] for c in concepts if _has(c["pattern"], a["content_norm"])]
        missing = [c["label"] for c in concepts if c["label"] not in covered]
        age = (as_of - a["last_updated"]).days if pd.notna(a["last_updated"]) else None
        status = ("Does not explain" if missing else
                  "Outdated" if age is not None and age > cfg["help_center_stale_days"] else "Covered")
        out.append({"article_id": a["article_id"], "title": a["title"], "owner_team": a["owner_team"],
                    "last_updated": str(a["last_updated"].date()) if pd.notna(a["last_updated"]) else "",
                    "age_days": age, "covered": covered, "missing": missing, "status": status,
                    "stale": bool(age is not None and age > cfg["help_center_stale_days"])})
    return sorted(out, key=lambda r: (len(r["missing"]), r["age_days"] or 0))


def check(voc, hc, as_of, days=28):
    as_of = pd.Timestamp(as_of)
    win = voc[(voc["date"] > as_of - pd.Timedelta(days=days)) & (voc["date"] <= as_of) & voc["is_negative"]]
    idx = sub_issue_index()
    gaps = []
    for sub, meta in idx.items():
        if meta["group"] == "Other":
            continue
        qps = meta.get("question_patterns") or []
        for stk in STAKEHOLDERS:
            rows = win[(win["stakeholder_type"] == stk) &
                       ((win["sub_issue"] == sub) | win["secondary_issues"].str.contains(sub, regex=False))]
            if len(rows) < MIN_VOLUME:
                continue
            arts = article_coverage(hc, sub, as_of)
            q_share, q_label, q_ids = None, None, []
            if qps:
                hit = rows["comment_norm"].apply(lambda t: any(re.search(q["pattern"], t) for q in qps))
                q_share, q_label = float(hit.mean()), qps[0]["label"]
                q_ids = rows[hit]["feedback_id"].tolist()
            best = arts[0] if arts else None
            status = best["status"] if best else "Missing article"
            if status == "Covered" and not (best and best["stale"]):
                continue
            if not meta.get("must_explain") and best is not None and not best["stale"]:
                continue
            gaps.append({"sub_issue": sub, "stakeholder": stk, "volume": int(len(rows)), "status": status,
                         "article": best, "question_label": q_label, "question_share": q_share,
                         "question_count": len(q_ids), "record_ids": q_ids[:100] or rows["feedback_id"].tolist()[:100],
                         "owner": best["owner_team"] if best else meta.get("owner", "CS"),
                         "window_days": days})
    return sorted(gaps, key=lambda g: ((g["question_share"] or 0) * g["volume"], g["volume"]), reverse=True)
