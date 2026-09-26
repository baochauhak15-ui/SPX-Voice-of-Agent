# -*- coding: utf-8 -*-
"""Journey / Ticket mapper adapted to SPX (reference: Journey Mapper + Ticket Mapper).

  * VOC  -> operational parcel journey  by tracking_id (hub dwell time, attempts, failed attempts)
  * VOC  -> support tickets             by stakeholder_id within ±2 days (nearest), or same tracking_id
Linking is *directional evidence*, not a complete universe (same caveat as the reference project).
"""
import pandas as pd


def parcel_journeys(ops):
    """One row per tracking_id with the hub processing time and delivery outcome."""
    sort = ops[ops["event_type"] == "sort_complete"][["tracking_id", "hub", "processing_time", "date"]]
    sort = sort.rename(columns={"hub": "ops_hub", "processing_time": "hub_processing_hours", "date": "sort_date"})
    att = ops[ops["event_type"] == "delivery_attempt"]
    agg = att.groupby("tracking_id").agg(delivery_attempts=("delivery_attempt", "max"),
                                         failed_attempts=("status", lambda s: int((s == "failed").sum())))
    pk = ops[ops["event_type"] == "pickup"][["tracking_id", "processing_time"]].rename(
        columns={"processing_time": "pickup_lead_hours"})
    j = sort.merge(agg, on="tracking_id", how="left").merge(pk, on="tracking_id", how="left")
    return j.drop_duplicates("tracking_id")


def link(voc, tickets, ops, window_days=2):
    j = parcel_journeys(ops)
    voc = voc.merge(j, on="tracking_id", how="left")

    # ticket link: same stakeholder_id, nearest created_time within the window
    tk = tickets[["ticket_id", "stakeholder_id", "created_time", "status", "first_response_hours"]].dropna(
        subset=["created_time"])
    tk_by_sid = {sid: g.sort_values("created_time") for sid, g in tk.groupby("stakeholder_id")}
    ids, n_contacts = [], []
    win = pd.Timedelta(days=window_days)
    for sid, ts in zip(voc["stakeholder_id"], voc["timestamp"]):
        g = tk_by_sid.get(sid)
        if g is None:
            ids.append("")
            n_contacts.append(0)
            continue
        near = g[(g["created_time"] - ts).abs() <= win]
        if near.empty:
            ids.append("")
            n_contacts.append(0)
        else:
            k = (near["created_time"] - ts).abs().idxmin()
            ids.append(near.loc[k, "ticket_id"])
            n_contacts.append(len(near))
    voc["ticket_id"] = ids
    voc["contacts_in_window"] = n_contacts
    voc["has_ticket"] = voc["ticket_id"] != ""
    return voc
