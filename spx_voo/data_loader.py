# -*- coding: utf-8 -*-
"""Read the six source CSVs and validate their schema (reference: Data Cleaner step 1)."""
import os

import pandas as pd

SCHEMAS = {
    "customer_voc": ["feedback_id", "stakeholder_type", "stakeholder_id", "timestamp", "rating", "comment",
                     "issue_type", "region", "hub", "tracking_id"],
    "seller_voc": ["feedback_id", "stakeholder_type", "seller_id", "timestamp", "rating", "comment",
                   "issue_type", "region", "hub", "tracking_id"],
    "rider_voc": ["feedback_id", "stakeholder_type", "rider_id", "timestamp", "rating", "comment",
                  "issue_type", "region", "hub"],
    "support_tickets": ["ticket_id", "stakeholder_type", "stakeholder_id", "created_time", "first_response_time",
                        "resolution_time", "issue_type", "description", "status", "owner_team", "hub",
                        "tracking_id"],
    "operational_events": ["event_id", "timestamp", "tracking_id", "event_type", "hub", "region",
                           "delivery_attempt", "processing_time", "status"],
    "help_center": ["article_id", "title", "issue_type", "content", "owner_team", "last_updated"],
}


class SchemaError(ValueError):
    pass


def load_all(data_dir):
    """Return {name: DataFrame}. Raises SchemaError listing every missing file/column."""
    frames, problems = {}, []
    for name, cols in SCHEMAS.items():
        path = os.path.join(data_dir, f"{name}.csv")
        if not os.path.exists(path):
            problems.append(f"missing file {name}.csv")
            continue
        df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
        missing = [c for c in cols if c not in df.columns]
        if missing:
            problems.append(f"{name}.csv missing columns {missing}")
        frames[name] = df
    if problems:
        raise SchemaError("; ".join(problems))
    return frames
