# -*- coding: utf-8 -*-
"""Main dashboard: one self-contained HTML file (inline CSS/JS/SVG, data embedded as JSON)."""
import json
import math
import os

import numpy as np
import pandas as pd

from .config import drivers, priority_cfg

TEMPLATE = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")


def jsonable(o):
    """Recursively convert numpy / pandas / inf / NaN into JSON-safe values (inf -> "inf")."""
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [jsonable(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        if math.isnan(f):
            return None
        if math.isinf(f):
            return "inf" if f > 0 else "-inf"
        return round(f, 4)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp,)):
        return str(o)
    return o


def build_payload(result, meta):
    ins = result["insights"]
    by_driver = {i.get("driver"): i for i in ins if i.get("driver")}
    rank = {"P1": 0, "P2": 1, "P3": 2}
    sub_to_ins = {}
    for key, d in drivers().items():
        i = by_driver.get(key)
        if not i:
            continue
        for subs in d["voc_signals"].values():
            for s in subs:
                cur = sub_to_ins.get(s)
                if cur is None or rank[i["priority"]] < rank[cur["priority"]]:
                    sub_to_ins[s] = i
    emerging = []
    for e in result["emerging"]:
        i = sub_to_ins.get(e["sub_issue"])
        emerging.append({**e, "priority": i["priority"] if i else "P3", "insight_id": i["id"] if i else None})
    return jsonable({
        "labels": priority_cfg()["labels"], "window": result["window"], "kpis": result["kpis"],
        "stakeholders": result["stakeholders"], "daily": result["daily"], "emerging": emerging,
        "insights": ins, "actions": result["actions"].to_dict("records"), "meta": meta,
    })


def render(payload, fragment=False):
    with open(TEMPLATE, encoding="utf-8") as f:
        tpl = f.read()
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    body = tpl.replace("/*__DATA__*/null", data)
    if fragment:                       # for hosts that add their own <html>/<head>/<body> skeleton
        return body
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            + body + "\n</html>\n")


def write(result, meta, out_dir, name="SPX_Voice_of_Operations_Dashboard.html", fragment=False):
    path = os.path.join(out_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(render(build_payload(result, meta), fragment=fragment))
    return path
