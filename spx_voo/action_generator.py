# -*- coding: utf-8 -*-
"""Action list: one row per recommended action, traceable to its insight and evidence."""
import pandas as pd

COLUMNS = ["insight", "root_cause", "stakeholder", "priority", "owner", "recommended_action", "evidence", "status",
           "confidence", "insight_id"]


def build(insights):
    rows = []
    for i in insights:
        ev = "; ".join(f"{e['metric']}: {e['baseline']} → {e['current']} ({e['change']})" for e in i["evidence"][:4])
        for a in i["recommended_actions"]:
            rows.append({"insight": i["title"], "root_cause": i["root_cause_statement"],
                         "stakeholder": " + ".join(i["affected_stakeholders"]), "priority": i["priority"],
                         "owner": a["owner"], "recommended_action": a["action"], "evidence": ev,
                         "status": "Monitor" if i["priority"] == "P3" else "Open",
                         "confidence": i["confidence"], "insight_id": i["id"]})
    return pd.DataFrame(rows, columns=COLUMNS)
