# -*- coding: utf-8 -*-
"""Unify Customer / Seller / Rider VOC into one frame and clean all sources.

Business rules (deterministic):
  * each feedback row = one VOC record (no dedupe by stakeholder — reference rule)
  * exact duplicate feedback_id rows are dropped and counted
  * rating outside 1..5 -> NaN, flagged in data-quality stats
  * stakeholder_type is normalised to Customer | Seller | Rider
"""
import pandas as pd

from .text_utils import normalize

STK_ALIASES = {"customer": "Customer", "buyer": "Customer", "khach hang": "Customer",
               "seller": "Seller", "shop": "Seller", "nguoi ban": "Seller",
               "rider": "Rider", "driver": "Rider", "tai xe": "Rider", "shipper": "Rider"}


def _stk(v, default):
    return STK_ALIASES.get(normalize(v), default)


def clean(frames):
    """Return (voc, tickets, ops, help_center, dq_stats)."""
    dq = {}
    parts = []
    for name, id_col, default in (("customer_voc", "stakeholder_id", "Customer"),
                                  ("seller_voc", "seller_id", "Seller"),
                                  ("rider_voc", "rider_id", "Rider")):
        df = frames[name].copy()
        df = df.rename(columns={id_col: "stakeholder_id"})
        if "tracking_id" not in df.columns:
            df["tracking_id"] = ""
        df["stakeholder_type"] = [_stk(v, default) for v in df["stakeholder_type"]]
        df["source_file"] = f"{name}.csv"
        parts.append(df[["feedback_id", "stakeholder_type", "stakeholder_id", "timestamp", "rating", "comment",
                         "issue_type", "region", "hub", "tracking_id", "source_file"]])
    voc = pd.concat(parts, ignore_index=True)
    n0 = len(voc)
    voc = voc.drop_duplicates(subset=["feedback_id"]).copy()
    dq["duplicate_feedback_dropped"] = n0 - len(voc)

    voc["timestamp"] = pd.to_datetime(voc["timestamp"], errors="coerce")
    dq["bad_timestamp_dropped"] = int(voc["timestamp"].isna().sum())
    voc = voc[voc["timestamp"].notna()].copy()
    voc["date"] = voc["timestamp"].dt.normalize()
    voc["rating"] = pd.to_numeric(voc["rating"], errors="coerce")
    voc.loc[~voc["rating"].between(1, 5), "rating"] = float("nan")
    dq["invalid_rating"] = int(voc["rating"].isna().sum())
    for c in ("comment", "issue_type", "region", "hub", "tracking_id", "stakeholder_id"):
        voc[c] = voc[c].fillna("").astype(str).str.strip()
    voc["comment_norm"] = [normalize(c) for c in voc["comment"]]
    dq["empty_comment"] = int((voc["comment_norm"] == "").sum())
    voc = voc.sort_values("timestamp").reset_index(drop=True)

    t = frames["support_tickets"].copy()
    for c in ("created_time", "first_response_time", "resolution_time"):
        t[c] = pd.to_datetime(t[c], errors="coerce")
    t["stakeholder_type"] = [_stk(v, "Customer") for v in t["stakeholder_type"]]
    t["first_response_hours"] = (t["first_response_time"] - t["created_time"]).dt.total_seconds() / 3600
    t["date"] = t["created_time"].dt.normalize()

    ops = frames["operational_events"].copy()
    ops["timestamp"] = pd.to_datetime(ops["timestamp"], errors="coerce")
    ops["date"] = ops["timestamp"].dt.normalize()
    ops["processing_time"] = pd.to_numeric(ops["processing_time"], errors="coerce")
    ops["delivery_attempt"] = pd.to_numeric(ops["delivery_attempt"], errors="coerce")

    hc = frames["help_center"].copy()
    hc["last_updated"] = pd.to_datetime(hc["last_updated"], errors="coerce")
    hc["content_norm"] = [normalize(f"{a} {b}") for a, b in zip(hc["title"], hc["content"])]

    dq.update({"voc_rows": len(voc), "tickets": len(t), "ops_events": len(ops), "help_articles": len(hc),
               "date_min": str(voc["date"].min().date()), "date_max": str(voc["date"].max().date())})
    return voc, t, ops, hc, dq
