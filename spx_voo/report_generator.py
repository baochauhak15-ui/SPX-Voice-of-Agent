# -*- coding: utf-8 -*-
"""Daily / Weekly / Monthly HTML reports + Action List (CSV / XLSX).

Report structure follows the reference project (Executive summary → KPI → period comparison →
root-cause → increasing issues → drill-down samples → action list → methodology & validation),
adapted to SPX and to cross-stakeholder root causes. Self-contained HTML, no CDN, light/dark aware.
"""
import html
import os

import pandas as pd

from .config import STAKEHOLDERS
from .insight_generator import pct

TITLES = {"daily": "SPX Daily Operations Intelligence",
          "weekly": "SPX Weekly VOC & Root Cause Report",
          "monthly": "SPX Monthly Operations Intelligence"}

CSS = """
:root{--bg:#f4f6f8;--surface:#fff;--s2:#eef1f4;--ink:#0f1720;--ink2:#465061;--muted:#727c8b;--line:#dfe3e8;
--p1:#d03b3b;--p1s:#fbe9e9;--p2:#c7652f;--p2s:#fcefe6;--p3:#6b7482;--p3s:#eceef1;--ok:#0a7d0a;--oks:#e5f4e5;
--fact:#2a5f9e;--inf:#7a4bb3;--rec:#0a7d0a;--cc:#2a78d6;--cs:#eb6834;--cr:#1baf7a}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#0d1015;--surface:#151a21;--s2:#1c222b;
--ink:#f1f3f6;--ink2:#b8c0cc;--muted:#8a93a1;--line:#29303a;--p1:#e66767;--p1s:#3a1d1f;--p2:#ec835a;--p2s:#3a2519;--p3:#9aa3b0;
--p3s:#242a33;--ok:#3fbf3f;--oks:#173019;--fact:#86b6ef;--inf:#b99af0;--rec:#5fd15f;--cc:#3987e5;--cs:#d95926;--cr:#199e70}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#0d1015;--surface:#151a21;--s2:#1c222b;--ink:#f1f3f6;--ink2:#b8c0cc;--muted:#8a93a1;
--line:#29303a;--p1:#e66767;--p1s:#3a1d1f;--p2:#ec835a;--p2s:#3a2519;--p3:#9aa3b0;--p3s:#242a33;--ok:#3fbf3f;--oks:#173019;
--fact:#86b6ef;--inf:#b99af0;--rec:#5fd15f;--cc:#3987e5;--cs:#d95926;--cr:#199e70}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 "IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1040px;margin:0 auto;padding-inline:20px;padding-block:28px 48px;display:grid;gap:16px}
h1{font:700 28px/1.15 "IBM Plex Sans Condensed","IBM Plex Sans",system-ui,sans-serif;margin:0}
h2{font:700 18px/1.2 "IBM Plex Sans Condensed","IBM Plex Sans",system-ui,sans-serif;margin:0 0 10px}
h3{font-size:15px;margin:0 0 6px}
section{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px 18px}
.sub{color:var(--ink2);margin:6px 0 0}.muted{color:var(--muted)}
.pills{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.pill{border:1px solid var(--line);border-radius:999px;padding:3px 10px;font-size:12px;color:var(--ink2);background:var(--surface)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.kpi{border:1px solid var(--line);border-radius:8px;padding:10px 12px}.kpi b{display:block;font-size:22px;font-variant-numeric:tabular-nums}
.kpi span{font-size:12px;color:var(--muted)}
.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}
th{text-align:left;font-size:12px;color:var(--muted);font-weight:600;border-bottom:1px solid var(--line);padding:7px 8px;white-space:nowrap}
td{border-bottom:1px solid var(--line);padding:7px 8px;vertical-align:top}td.r,th.r{text-align:right;font-variant-numeric:tabular-nums}
.chip{display:inline-block;border-radius:6px;padding:1px 7px;font-size:11.5px;font-weight:600;white-space:nowrap}
.P1{background:var(--p1s);color:var(--p1)}.P2{background:var(--p2s);color:var(--p2)}.P3{background:var(--p3s);color:var(--p3)}
.High{background:var(--oks);color:var(--ok)}.Medium{background:var(--p2s);color:var(--p2)}.Low{background:var(--p3s);color:var(--p3)}
.ins{border:1px solid var(--line);border-radius:8px;padding:14px;display:grid;gap:10px;margin-top:12px}
.ins.cross{border-left:4px solid var(--p1)}
.grid3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.grid3 div{background:var(--s2);border-radius:8px;padding:8px 10px}.k{font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);font-weight:600}
ul.st{list-style:none;margin:0;padding:0;display:grid;gap:5px}ul.st li{display:grid;grid-template-columns:118px 1fr;gap:10px}
.tag{font:600 10.5px/1.6 "IBM Plex Mono",ui-monospace,monospace;border-radius:4px;padding:0 6px;justify-self:start}
.FACT{color:var(--fact);border:1px solid currentColor}.INFERENCE{color:var(--inf);border:1px dashed currentColor}.RECOMMENDATION{color:var(--rec);border:1px solid currentColor}
.y{color:var(--ok);font-weight:700}.n{color:var(--muted);font-weight:700}
.bar{display:inline-block;height:8px;border-radius:0 3px 3px 0;vertical-align:middle}
.up{color:var(--p1)}.down{color:var(--ok)}
ol,ul.plain{margin:0;padding-left:20px;display:grid;gap:4px}
@media (max-width:700px){.grid3{grid-template-columns:1fr}ul.st li{grid-template-columns:1fr;gap:2px}main{padding-inline:16px}}
"""

E = lambda s: html.escape(str(s if s is not None else ""))
COLV = {"Customer": "var(--cc)", "Seller": "var(--cs)", "Rider": "var(--cr)"}


def chip(p, text=None):
    return f'<span class="chip {E(p)}">{E(text or p)}</span>'


def table(cols, rows):
    if not rows:
        return '<p class="muted">None.</p>'
    h = "".join(f'<th class="{c[2] if len(c) > 2 else ""}">{E(c[0])}</th>' for c in cols)
    body = ""
    for r in rows:
        body += "<tr>" + "".join(
            f'<td class="{c[2] if len(c) > 2 else ""}">{c[1](r) if callable(c[1]) else E(r.get(c[1], ""))}</td>' for c in cols) + "</tr>"
    return f'<div class="wrap"><table><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table></div>'


def insight_block(i, full=True):
    parts = [f'<div class="ins {"cross" if i["type"] == "cross_stakeholder" else ""}">',
             f'<div>{chip(i["priority"], i["priority"] + " · " + i["priority_label"])} {chip(i["confidence"], i["confidence"] + " confidence")} '
             f'<span class="muted">{E(i["headline"])} · owner {E(i["owner"])}</span></div>',
             f'<h3>{E(i["title"])}</h3>',
             '<div class="grid3">' + "".join(f'<div><div class="k">{k}</div>{E(v)}</div>' for k, v in (
                 ("What happened", i["what"]), ("Who · where", f'{i["who"]} · {i["where"]}'), ("Impact (measured)", i["impact"]))) + '</div>',
             '<ul class="st">' + "".join(f'<li><span class="tag {s["type"]}">{s["type"]}</span><span>{E(s["text"])}</span></li>'
                                         for s in i["statements"]) + "</ul>"]
    if full and i.get("drilldown", {}).get("checks"):
        parts.append("<div><b>Evidence checks</b>" + table(
            [["", lambda c: '<span class="y">✓</span>' if c["passed"] else '<span class="n">–</span>'],
             ["Check", "check"], ["Detail", "detail"]], i["drilldown"]["checks"]) + "</div>")
    if full:
        parts.append("<div><b>Evidence</b>" + table(
            [["Metric", "metric"], ["Baseline", "baseline", "r"], ["Current", "current", "r"], ["Change", "change"],
             ["Source", "source"], ["Traceable ids", lambda e: str(len(e.get("record_ids") or e.get("ticket_ids") or [])) or "", "r"]],
            i["evidence"]) + "</div>")
        ex = (i.get("drilldown") or {}).get("examples") or []
        if ex:
            parts.append("<div><b>Representative VOC</b>" + table(
                [["Id", "feedback_id"], ["Stakeholder", "stakeholder"], ["Hub", "hub"], ["★", "rating", "r"],
                 ["Comment", "comment"], ["Label", lambda v: f'{E(v["sub_issue"])} <span class="muted">({E(v["confidence"])})</span>']],
                ex[:6]) + "</div>")
    parts.append("</div>")
    return "".join(parts)


def _period_table(res):
    rows = []
    for s in STAKEHOLDERS:
        v = res["stakeholders"][s]
        rows.append({"s": s, **v})
    mx = max(max(r["negative"], r["negative_baseline"]) for r in rows) or 1
    return table([
        ["Stakeholder", lambda r: f'<span class="bar" style="width:10px;background:{COLV[r["s"]]}"></span> {E(r["s"])}'],
        ["VOC", "total", "r"], ["Negative (baseline avg)", lambda r: f'{r["negative_baseline"]:.0f}', "r"],
        ["Negative (now)", "negative", "r"],
        ["Change", lambda r: f'<span class="{"up" if (r["negative_growth"] or 0) > 0 else "down"}">{pct(r["negative_growth"])}</span>', "r"],
        ["", lambda r: f'<span class="bar" style="width:{120 * r["negative"] / mx:.0f}px;background:{COLV[r["s"]]}"></span>'],
        ["Neg. rate", lambda r: f'{r["negative_rate"]:.0%}', "r"], ["Avg ★", "avg_rating", "r"], ["Top issue", "top_issue"]], rows)


def _issues_table(em, n=10, reverse=False):
    rows = sorted(em, key=lambda e: e["delta"], reverse=not reverse)
    rows = [e for e in rows if (e["delta"] < 0 if reverse else e["delta"] > 0)][:n]
    return table([["Sub-issue", "sub_issue"], ["Group", "issue_group"], ["Baseline", lambda e: f'{e["baseline"]:.0f}', "r"],
                  ["Now", "current", "r"], ["Change", lambda e: pct(e["growth"]), "r"],
                  ["Customer / Seller / Rider", lambda e: " / ".join(str(e["stakeholders"][s]["current"]) for s in STAKEHOLDERS), "r"],
                  ["Top hub", lambda e: f'{E(e["top_hub"])} ({e["top_hub_share"]:.0%})']], rows)


def _hub_matrix(voc, win):
    cur = voc[win.cur(voc["date"]) & voc["is_negative"]]
    base = voc[win.base(voc["date"]) & voc["is_negative"]]
    c = cur.groupby(["hub", "stakeholder_type"]).size().unstack(fill_value=0).reindex(columns=STAKEHOLDERS, fill_value=0)
    b = base.groupby("hub").size() * win.scale
    rows = [{"hub": h, **{s: int(r[s]) for s in STAKEHOLDERS}, "total": int(r.sum()), "base": float(b.get(h, 0))}
            for h, r in c.iterrows()]
    rows.sort(key=lambda r: r["total"], reverse=True)
    return table([["Hub", "hub"], ["Customer", "Customer", "r"], ["Seller", "Seller", "r"], ["Rider", "Rider", "r"],
                  ["Total", "total", "r"], ["Baseline", lambda r: f'{r["base"]:.0f}', "r"],
                  ["Change", lambda r: pct((r["total"] / r["base"] - 1) if r["base"] else None), "r"]], rows)


def render(mode, res, meta, voc, context=None):
    w, k = res["window"], res["kpis"]
    ins = res["insights"]
    active = [i for i in ins if i["type"] != "monitor"]
    summary = [f'{chip(i["priority"])} <b>{E(i["headline"])}</b> — {E(i["root_cause_statement"])}. {E(i["what"])}.'
               for i in active[:5]]
    if context:
        summary = [f'{chip(i["priority"])} <b>Still active:</b> {E(i["root_cause_statement"])}. {E(i["what"])} (7-day view).'
                   for i in context["insights"] if i["priority"] == "P1"] + summary
    out = [f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           f'<title>{E(TITLES[mode])}</title><style>{CSS}</style></head><body><main>',
           f'<header><h1>{E(TITLES[mode])}</h1><p class="sub">Customer · Seller · Rider voice of operations, linked to tickets, '
           f'parcel scans and Help Center.</p><div class="pills"><span class="pill">Current {E(w["current"][0])} → {E(w["current"][1])}</span>'
           f'<span class="pill">Baseline {E(w["baseline"][0])} → {E(w["baseline"][1])} ({E(w["comparison"])})</span>'
           f'<span class="pill">Generated {E(meta["generated_at"])}</span><span class="pill">Synthetic demo data</span></div></header>']
    out.append('<section><h2>Executive summary</h2><ol>' + "".join(f"<li>{s}</li>" for s in summary) + '</ol></section>')
    if context:
        still = [i for i in context["insights"] if i["priority"] == "P1"]
        if still:
            out.append('<section><h2>Still active (7-day view)</h2><p class="muted">Issues from the weekly analysis that remain '
                       'P1 — a single day compared with the prior 7 days can hide a problem that started earlier.</p>'
                       + "".join(insight_block(i, full=False) for i in still) + '</section>')
    out.append('<section><h2>KPIs</h2><div class="kpis">' + "".join(
        f'<div class="kpi"><span>{E(a)}</span><b>{E(b)}</b><span>{E(c)}</span></div>' for a, b, c in (
            ("Total VOC", f'{k["total_voc"]:,}', "current window"),
            ("Negative VOC", f'{k["negative_voc"]:,}', f'{pct(k["negative_growth"])} vs {k["negative_baseline"]:.0f}'),
            ("Top issue", k["top_issue"], f'{k["top_issue_count"]} records'),
            ("Issues increasing", k["issues_increasing"], "significant growth"),
            ("Cross-stakeholder", k["cross_stakeholder_issues"], "issues"),
            ("High priority", k["high_priority"], f'P1 · {k["p2"]} at P2'))) + '</div></section>')
    out.append('<section><h2>Who is affected — period comparison</h2>' + _period_table(res) + '</section>')
    out.append('<section><h2>Root-cause insights</h2><p class="muted">FACT = measured from data · INFERENCE = agent '
               'interpretation (correlational) · RECOMMENDATION = next step.</p>'
               + "".join(insight_block(i, full=(mode != "daily" or i["priority"] == "P1")) for i in active) + '</section>')
    out.append('<section><h2>Top increasing issues</h2>' + _issues_table(res["emerging"]) + '</section>')
    if mode != "daily":
        out.append('<section><h2>Top decreasing issues</h2>' + _issues_table(res["emerging"], n=5, reverse=True) + '</section>')
    if mode == "monthly":
        out.append('<section><h2>Negative VOC by hub and stakeholder</h2>' + _hub_matrix(voc, res["win"]) + '</section>')
    gaps = res["knowledge_gaps"]
    out.append('<section><h2>Knowledge gaps (Help Center)</h2>' + table(
        [["Topic", "sub_issue"], ["Stakeholder", "stakeholder"], ["Complaints (28d)", "volume", "r"], ["Status", "status"],
         ["Article", lambda g: E(g["article"]["article_id"] + " " + g["article"]["title"]) if g["article"] else "—"],
         ["Missing guidance", lambda g: E("; ".join(g["article"]["missing"])) if g["article"] else "article missing"],
         ["Question share", lambda g: f'{g["question_share"]:.0%}' if g["question_share"] is not None else "—", "r"]],
        gaps) + '</section>')
    out.append('<section><h2>Action list</h2>' + table(
        [["Pri.", lambda a: chip(a["priority"])], ["Action", "recommended_action"], ["Owner", "owner"],
         ["Stakeholder", "stakeholder"], ["Root cause", "root_cause"], ["Status", "status"]],
        res["actions"].to_dict("records")) + '</section>')
    c = meta["classification"]
    dq = meta["data_quality"]
    out.append('<section><h2>Methodology &amp; caveats</h2><ul class="plain">'
               f'<li>Rule-based classification on 100% of {c["records"]:,} records (controlled taxonomy in <code>config/taxonomy.yaml</code>); '
               f'{c["llm"]["candidates"]} low-confidence / conflicting / multi-issue records flagged for the LLM layer '
               f'(provider: {E(c["llm"]["provider"])}, applied: {c["llm"]["applied"]}).</li>'
               + (f'<li>Label accuracy vs synthetic ground truth: {c["eval"]["sub_issue_accuracy"]:.0%} on {c["eval"]["labelled_negative"]:,} negative records.</li>' if c.get("eval") else "")
               + f'<li>Negative VOC = rating ≤ 2, or rating 3 with a complaint signal. Comparison: {E(w["comparison"])}.</li>'
               '<li>Root-cause confidence = number of passed checks (multi-stakeholder, location overlap, operational corroboration '
               'with a control group, temporal alignment, parcel-level link). High ≥ 4, Medium 2–3, Low ≤ 1. Low confidence is never P1.</li>'
               '<li>All root-cause statements are correlational and worded as “likely / potential”. Validate with the owning team before acting on causality.</li>'
               '<li>Impact statements only cite counted quantities (complaints, tickets, repeat contacts, SLA breach); no monetary impact is estimated.</li>'
               '</ul></section>')
    out.append('<section><h2>Data validation</h2>' + table([["Check", "k"], ["Value", "v", "r"]], [
        {"k": "VOC records", "v": f'{dq["voc_rows"]:,}'}, {"k": "Date range", "v": f'{dq["date_min"]} → {dq["date_max"]}'},
        {"k": "Duplicate feedback dropped", "v": dq["duplicate_feedback_dropped"]}, {"k": "Invalid ratings", "v": dq["invalid_rating"]},
        {"k": "Empty comments", "v": dq["empty_comment"]}, {"k": "Support tickets", "v": f'{dq["tickets"]:,}'},
        {"k": "Operational events", "v": f'{dq["ops_events"]:,}'}, {"k": "Help Center articles", "v": dq["help_articles"]},
        {"k": "Records needing human review", "v": c["human_review"]}]) + '</section>')
    out.append("</main></body></html>")
    return "".join(out)


def file_name(mode, res):
    end = pd.Timestamp(res["window"]["current"][1])
    suffix = {"daily": end.strftime("%Y%m%d"), "weekly": f"{end.isocalendar().year}W{end.isocalendar().week:02d}",
              "monthly": end.strftime("%Y%m")}[mode]
    return {"daily": "SPX_Daily_Operations_Intelligence_", "weekly": "SPX_Weekly_VOC_Root_Cause_Report_",
            "monthly": "SPX_Monthly_Operations_Intelligence_"}[mode] + suffix + ".html"


def write_report(mode, res, meta, voc, out_dir, context=None):
    path = os.path.join(out_dir, file_name(mode, res))
    with open(path, "w", encoding="utf-8") as f:
        f.write(render(mode, res, meta, voc, context))
    return path


def write_action_list(actions, out_dir):
    csv_path = os.path.join(out_dir, "SPX_Action_List.csv")
    actions.to_csv(csv_path, index=False, encoding="utf-8-sig")
    paths = [csv_path]
    try:
        xlsx = os.path.join(out_dir, "SPX_Action_List.xlsx")
        with pd.ExcelWriter(xlsx, engine="openpyxl") as xw:
            actions.to_excel(xw, index=False, sheet_name="Action List")
            ws = xw.sheets["Action List"]
            for col, width in zip("ABCDEFGHIJ", (38, 50, 22, 9, 14, 70, 70, 10, 12, 30)):
                ws.column_dimensions[col].width = width
            ws.freeze_panes = "A2"
        paths.append(xlsx)
    except Exception:
        pass
    return paths
