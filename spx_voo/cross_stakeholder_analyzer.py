# -*- coding: utf-8 -*-
"""Cross-stakeholder pattern detection — the key differentiator.

For each operational driver (config/drivers.yaml):
  1. group negative VOC by driver through each stakeholder's symptom sub-issues
  2. compare Customer / Seller / Rider: current window vs baseline window
  3. localise: region / hub concentration and lift vs baseline
  4. cross-check operations at the same hub (and a control group: all other hubs)
  5. parcel-level link: complaints whose own parcel passed the hub with abnormal processing time
  6. temporal alignment: did operations deteriorate before / when VOC spiked?
  7. support signals: related tickets, repeat contacts, SLA breach
Everything returned here is an OBSERVED FACT (numbers + record ids). Interpretation happens in
root_cause_analyzer.py.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import STAKEHOLDERS, drivers, priority_cfg


@dataclass
class Window:
    mode: str
    cur_start: pd.Timestamp
    cur_end: pd.Timestamp
    base_start: pd.Timestamp
    base_end: pd.Timestamp

    @property
    def scale(self):
        """Multiply baseline counts by this to compare with the current window (per-period average)."""
        return ((self.cur_end - self.cur_start).days + 1) / ((self.base_end - self.base_start).days + 1)

    @property
    def label(self):
        return {"daily": "vs prior 7-day daily avg", "weekly": "vs prior 4-week avg", "monthly": "vs prior 28 days"}[self.mode]

    def cur(self, s):
        return (s >= self.cur_start) & (s <= self.cur_end)

    def base(self, s):
        return (s >= self.base_start) & (s <= self.base_end)

    def as_dict(self):
        f = lambda t: str(t.date())
        return {"mode": self.mode, "current": [f(self.cur_start), f(self.cur_end)],
                "baseline": [f(self.base_start), f(self.base_end)], "comparison": self.label}


def make_window(end_date, mode="weekly"):
    end = pd.Timestamp(end_date).normalize()
    if mode == "daily":
        return Window(mode, end, end, end - pd.Timedelta(days=7), end - pd.Timedelta(days=1))
    # weekly: last 7 days vs the average week of the 4 prior weeks (more robust than plain WoW)
    n, nb = {"weekly": (7, 28), "monthly": (28, 28)}[mode]
    cs = end - pd.Timedelta(days=n - 1)
    return Window(mode, cs, end, cs - pd.Timedelta(days=nb), cs - pd.Timedelta(days=1))


def growth(cur, base):
    if base <= 0:
        return None if cur == 0 else float("inf")
    return cur / base - 1


def _sig(cur, base, cfg):
    s = cfg["significance"]
    g = growth(cur, base)
    return bool(cur >= s["min_current"] and (cur - base) >= s["min_delta"] and (g is None or g >= s["min_growth"]))


def driver_mask(voc, dcfg):
    m = pd.Series(False, index=voc.index)
    for stk, subs in (dcfg.get("voc_signals") or {}).items():
        m |= (voc["stakeholder_type"] == stk) & voc["sub_issue"].isin(subs)
    return m


def _ops_series(dcfg, ops, tickets, hub=None, exclude_hub=None):
    """Daily metric series for the driver's operational metric (optionally for one hub)."""
    om = dcfg.get("ops_metric")
    if not om:
        return None
    if om["source"] == "ops":
        d = ops[ops["event_type"] == om["event_type"]]
    else:
        d = tickets.rename(columns={"created_time": "timestamp"})
    if hub:
        d = d[d["hub"] == hub]
    if exclude_hub:
        d = d[d["hub"] != exclude_hub]
    if om["agg"] == "rate":
        return d.groupby("date")[om["field"]].apply(lambda s: (s == om["value"]).mean() * 100)
    return d.groupby("date")[om["field"]].mean()


def _window_mean(series, mask_fn):
    if series is None or series.empty:
        return None
    v = series[mask_fn(series.index.to_series())]
    return float(v.mean()) if len(v) else None


def _first_break(series, start, end, ref_start, ref_end, k=3.0, min_abs=0.0):
    """First date in [start, end] where series exceeds ref mean + k*std (and + min_abs)."""
    if series is None or series.empty:
        return None
    ref = series[(series.index >= ref_start) & (series.index <= ref_end)]
    if len(ref) < 5:
        return None
    thr = ref.mean() + max(k * ref.std(ddof=0), min_abs)
    hit = series[(series.index >= start) & (series.index <= end) & (series > thr)]
    return hit.index.min() if len(hit) else None


def analyze_driver(key, voc_neg, voc_all, tickets, ops, win, cfg=None):
    cfg = cfg or priority_cfg()
    d = drivers()[key]
    m = driver_mask(voc_neg, d)
    dv = voc_neg[m]
    cur = dv[win.cur(dv["date"])]
    base = dv[win.base(dv["date"])]
    sc = win.scale

    # ---- 1-2. per stakeholder
    stk = {}
    for s in STAKEHOLDERS:
        if s not in (d.get("voc_signals") or {}):
            continue
        c, b = int((cur["stakeholder_type"] == s).sum()), (base["stakeholder_type"] == s).sum() * sc
        cs = cur[cur["stakeholder_type"] == s]
        top = cs.groupby("hub").size().sort_values(ascending=False)
        stk[s] = {"current": c, "baseline": round(float(b), 1), "growth": growth(c, b), "delta": round(c - b, 1),
                  "significant": _sig(c, b, cfg), "top_hub": top.index[0] if len(top) else None,
                  "sub_issues": cs["sub_issue"].value_counts().to_dict()}

    # ---- 3. location
    hc = cur.groupby(["region", "hub"]).size().rename("current")
    hb = (base.groupby(["region", "hub"]).size() * sc).rename("baseline")
    loc = pd.concat([hc, hb], axis=1).fillna(0).reset_index()
    loc["delta"] = loc["current"] - loc["baseline"]
    loc["share_current"] = loc["current"] / max(len(cur), 1)
    loc["share_baseline"] = loc["baseline"] / max(len(base) * sc, 1e-9)
    loc = loc.sort_values("delta", ascending=False)
    top_hub = loc.iloc[0]["hub"] if len(loc) and loc.iloc[0]["delta"] > 0 else (
        loc.sort_values("current", ascending=False).iloc[0]["hub"] if len(loc) else None)
    top_region = loc[loc["hub"] == top_hub]["region"].iloc[0] if top_hub else None
    reg = cur.groupby("region").size().sort_values(ascending=False)

    # ---- 4. operations at the hub + control group
    ops_block = None
    om = d.get("ops_metric")
    if om and top_hub:
        s_hub = _ops_series(d, ops, tickets, hub=top_hub)
        s_ctl = _ops_series(d, ops, tickets, exclude_hub=top_hub)
        hb_, hc_ = _window_mean(s_hub, win.base), _window_mean(s_hub, win.cur)
        cb_, cc_ = _window_mean(s_ctl, win.base), _window_mean(s_ctl, win.cur)
        ops_block = {"label": om["label"], "unit": om.get("unit", ""), "hub": top_hub,
                     "baseline": hb_, "current": hc_, "change": growth(hc_, hb_) if hb_ else None,
                     "control_baseline": cb_, "control_current": cc_,
                     "control_change": growth(cc_, cb_) if cb_ else None,
                     "daily_hub": {str(k.date()): round(float(v), 2) for k, v in s_hub.items()} if s_hub is not None else {},
                     "daily_control": {str(k.date()): round(float(v), 2) for k, v in s_ctl.items()} if s_ctl is not None else {}}
        # ---- 6. temporal alignment (reference period = 4 weeks before the baseline window ends - 3d)
        ref_end = win.cur_start - pd.Timedelta(days=4)
        ref_start = ref_end - pd.Timedelta(days=27)
        scan_start = win.cur_start - pd.Timedelta(days=3)
        ops_first = _first_break(s_hub, scan_start, win.cur_end, ref_start, ref_end, k=3.0)
        vd = dv[dv["hub"] == top_hub].groupby("date").size()
        vd = vd.reindex(pd.date_range(ref_start, win.cur_end), fill_value=0)
        voc_first = _first_break(vd, scan_start, win.cur_end, ref_start, ref_end, k=3.0, min_abs=3)
        ops_block["ops_first_date"] = str(ops_first.date()) if ops_first is not None else None
        ops_block["voc_first_date"] = str(voc_first.date()) if voc_first is not None else None
        ops_block["aligned"] = bool(ops_first is not None and voc_first is not None and ops_first <= voc_first)

    # ---- 5. parcel-level link
    parcel = None
    pf = d.get("parcel_field")
    if pf and top_hub and pf in voc_all.columns:
        ref_mask = (voc_all["hub"] == top_hub) & voc_all[pf].notna()
        # normal range of the hub = all parcels in the reference period, via ops events
        s = ops[(ops["event_type"] == (om or {}).get("event_type", "sort_complete")) & (ops["hub"] == top_hub)]
        ref = s[s["date"] < win.base_start][om["field"]] if om else pd.Series(dtype=float)
        p90 = float(ref.quantile(0.9)) if len(ref) else None
        linked = cur[(cur["hub"] == top_hub) & cur[pf].notna()]
        if p90 is not None and len(linked):
            above = linked[linked[pf] > p90]
            base_linked = base[(base["hub"] == top_hub) & base[pf].notna()]
            parcel = {"hub": top_hub, "p90_reference": round(p90, 2), "linked": int(len(linked)),
                      "above_p90": int(len(above)), "share": len(above) / len(linked),
                      "baseline_share": (float((base_linked[pf] > p90).mean()) if len(base_linked) else None),
                      "record_ids": above["feedback_id"].tolist()[:200]}

    # ---- 7. support signals at the hub
    subs_all = sorted({x for v in d["voc_signals"].values() for x in v})
    tk = tickets[tickets["issue_type"].isin(subs_all)]
    if top_hub:
        tk = tk[tk["hub"] == top_hub]
    tcur, tbase = tk[win.cur(tk["date"])], tk[win.base(tk["date"])]
    sla = cfg["sla_first_response_hours"]
    rep = tcur.groupby("stakeholder_id").size()
    support = {"hub": top_hub, "tickets_current": int(len(tcur)), "tickets_baseline": round(len(tbase) * sc, 1),
               "sla_breach_current": float((tcur["first_response_hours"] > sla).mean()) if len(tcur) else 0.0,
               "sla_breach_baseline": float((tbase["first_response_hours"] > sla).mean()) if len(tbase) else 0.0,
               "repeat_contact_stakeholders": int((rep >= 2).sum()),
               "open_or_pending": int(tcur["status"].isin(["Open", "Pending"]).sum()),
               "ticket_ids": tcur["ticket_id"].tolist()[:200]}

    # ---- daily series per stakeholder for the whole available range (trend chart)
    daily = (dv.groupby(["date", "stakeholder_type"]).size().unstack(fill_value=0)
             .reindex(columns=[s for s in STAKEHOLDERS], fill_value=0))
    daily_hub = (dv[dv["hub"] == top_hub].groupby(["date", "stakeholder_type"]).size().unstack(fill_value=0)
                 .reindex(columns=[s for s in STAKEHOLDERS], fill_value=0)) if top_hub else daily.iloc[0:0]

    tot_c, tot_b = len(cur), len(base) * sc
    return {
        "driver": key, "label": d["label"], "owner": d["owner"],
        "total_current": int(tot_c), "total_baseline": round(float(tot_b), 1), "growth": growth(tot_c, tot_b),
        "stakeholders": stk,
        "significant_stakeholders": [s for s, v in stk.items() if v["significant"]],
        "location": {"top_hub": top_hub, "top_region": top_region,
                     "top_hub_share_current": float(loc[loc["hub"] == top_hub]["share_current"].iloc[0]) if top_hub else 0,
                     "top_hub_share_baseline": float(loc[loc["hub"] == top_hub]["share_baseline"].iloc[0]) if top_hub else 0,
                     "hubs": loc.round(3).to_dict("records"), "regions": reg.to_dict()},
        "stakeholder_top_hubs": {s: v["top_hub"] for s, v in stk.items() if v["significant"]},
        "ops": ops_block, "parcel_link": parcel, "support": support,
        "current_record_ids": cur["feedback_id"].tolist(),
        "daily": {str(k.date()): {s: int(r[s]) for s in STAKEHOLDERS} for k, r in daily.iterrows()},
        "daily_top_hub": {str(k.date()): {s: int(r[s]) for s in STAKEHOLDERS} for k, r in daily_hub.iterrows()},
        "max_severity": None,
    }


def analyze_all(voc, tickets, ops, win):
    neg = voc[voc["is_negative"]]
    return {k: analyze_driver(k, neg, voc, tickets, ops, win) for k in drivers()}


def emerging_issues(voc, win, cfg=None):
    """Per sub-issue: current vs baseline, per stakeholder (the 'Top emerging issues' table)."""
    cfg = cfg or priority_cfg()
    neg = voc[voc["is_negative"] & (voc["issue_group"] != "Other")]
    cur, base = neg[win.cur(neg["date"])], neg[win.base(neg["date"])]
    rows = []
    for sub in sorted(set(cur["sub_issue"]) | set(base["sub_issue"])):
        c, b = cur[cur["sub_issue"] == sub], base[base["sub_issue"] == sub]
        per = {}
        for s in STAKEHOLDERS:
            cc, bb = int((c["stakeholder_type"] == s).sum()), float((b["stakeholder_type"] == s).sum() * win.scale)
            per[s] = {"current": cc, "baseline": round(bb, 1), "growth": growth(cc, bb), "significant": _sig(cc, bb, cfg)}
        tc, tb = len(c), len(b) * win.scale
        top = c.groupby("hub").size().sort_values(ascending=False)
        rows.append({"sub_issue": sub, "issue_group": c["issue_group"].iloc[0] if len(c) else b["issue_group"].iloc[0],
                     "current": int(tc), "baseline": round(float(tb), 1), "growth": growth(tc, tb),
                     "delta": round(tc - tb, 1), "stakeholders": per,
                     "affected": [s for s in STAKEHOLDERS if per[s]["current"] > 0],
                     "top_hub": top.index[0] if len(top) else None,
                     "top_hub_share": float(top.iloc[0] / tc) if len(top) and tc else 0.0})
    return sorted(rows, key=lambda r: (r["delta"], r["current"]), reverse=True)


def safe_float(x):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return None
    return float(x)
