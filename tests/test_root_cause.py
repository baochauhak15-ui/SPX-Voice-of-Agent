import pytest

from spx_voo import action_generator, insight_generator, knowledge_checker
from spx_voo.cross_stakeholder_analyzer import analyze_all, emerging_issues, growth, make_window
from spx_voo.root_cause_analyzer import build_hypothesis
from spx_voo.voc_classifier import classify_frame


@pytest.fixture(scope="module")
def world(cleaned):
    voc, t, ops, hc, dq = cleaned
    voc = classify_frame(voc)
    win = make_window(voc["date"].max(), "weekly")
    an = analyze_all(voc, t, ops, win)
    gaps = knowledge_checker.check(voc, hc, win.cur_end)
    ins = insight_generator.generate(an, voc, t, ops, hc, win, gaps)
    return voc, t, ops, hc, win, an, gaps, ins


def test_windows():
    w = make_window("2026-09-20", "weekly")
    assert str(w.cur_start.date()) == "2026-09-14" and w.scale == 0.25
    d = make_window("2026-09-20", "daily")
    assert d.cur_start == d.cur_end and abs(d.scale - 1 / 7) < 1e-9
    assert growth(0, 0) is None and growth(5, 0) == float("inf") and growth(15, 10) == 0.5


def test_main_story_detected(world):
    *_, an, gaps, ins = world
    a = an["hub_processing_delay"]
    assert set(a["significant_stakeholders"]) == {"Customer", "Seller", "Rider"}
    assert a["location"]["top_hub"] == "HCM-ThuDuc-SOC"
    assert a["ops"]["change"] > 0.4 and abs(a["ops"]["control_change"]) < 0.1
    assert a["ops"]["aligned"] and a["ops"]["ops_first_date"] <= a["ops"]["voc_first_date"]
    assert a["parcel_link"]["share"] > 0.8
    top = ins[0]
    assert top["type"] == "cross_stakeholder" and top["priority"] == "P1" and top["confidence"] == "High"
    assert top["potential_root_cause"] == "Hub processing delay"
    assert top["headline"] == "Cross-stakeholder operational issue detected"
    assert "Operations" in top["owner"]


def test_no_causal_overclaim(world):
    ins = world[-1]
    for i in ins:
        for s in i["statements"]:
            t = s["text"].lower()
            assert "caused by" not in t and "the root cause is" not in t
        assert {s["type"] for s in i["statements"]} <= {"FACT", "INFERENCE", "RECOMMENDATION"}
    hub = ins[0]
    assert any(s["type"] == "INFERENCE" and "likely" in s["text"] for s in hub["statements"])


def test_other_stories_not_overescalated(world):
    ins = world[-1]
    p1 = [i for i in ins if i["priority"] == "P1"]
    assert len(p1) == 1, [i["title"] for i in p1]
    app = next(i for i in ins if i["driver"] == "app_stability" if "driver" in i)
    assert app["type"] != "cross_stakeholder" and "Rider" in app["affected_stakeholders"] and app["owner"] == "Product"


def test_low_confidence_never_p1(world):
    for i in world[-1]:
        if i["confidence"] == "Low":
            assert i["priority"] != "P1"


def test_knowledge_gap(world):
    gaps, ins = world[-2], world[-1]
    g = next(g for g in gaps if g["sub_issue"] == "Failed delivery" and g["stakeholder"] == "Seller")
    assert g["status"] == "Does not explain" and g["article"]["article_id"] == "HC-004"
    assert 0.2 <= g["question_share"] <= 0.7
    kg = next(i for i in ins if i["type"] == "knowledge_gap" and "Failed delivery" in i["title"])
    assert "Update Help Center" in kg["recommended_actions"][0]["action"]


def test_evidence_traceable(world):
    voc, t, *_ , ins = world
    ids = set(voc["feedback_id"])
    tids = set(t["ticket_id"])
    for e in ins[0]["evidence"]:
        assert set(e.get("record_ids", [])) <= ids
        assert set(e.get("ticket_ids", [])) <= tids
    assert ins[0]["drilldown"]["examples"] and ins[0]["drilldown"]["tickets"] and ins[0]["drilldown"]["ops_events"]


def test_action_list(world):
    df = action_generator.build(world[-1])
    assert list(df.columns[:8]) == ["insight", "root_cause", "stakeholder", "priority", "owner",
                                    "recommended_action", "evidence", "status"]
    assert (df["priority"] == "P1").any()


def test_emerging_issues(world):
    voc, t, ops, hc, win, *_ = world
    rows = emerging_issues(voc, win)
    assert rows[0]["sub_issue"] in {"Late delivery", "Tracking / status"}
    assert rows[0]["top_hub"] == "HCM-ThuDuc-SOC"
