import json

import pandas as pd
import pytest

from spx_voo.llm_classifier import apply_llm, parse_results, validate_item
from spx_voo.text_utils import normalize
from spx_voo.voc_classifier import RuleClassifier, classify_frame

clf = RuleClassifier()


def test_normalize_accents_teencode_and_stretch():
    assert normalize("Đơn giao TRỄ quáaaa!!!") == "don giao tre qua"
    assert normalize("ko nhận dc hàng") == "khong nhan duoc hang"
    assert normalize("Hub xử lý chậm 10h") == "kho xu ly cham 10 gio"


@pytest.mark.parametrize("stk,text,expected", [
    ("Customer", "Đơn giao trễ quá, chưa nhận được hàng", "Late delivery"),
    ("Customer", "don giao tre qua chua nhan dc hang", "Late delivery"),            # no accents + teen code
    ("Seller", "Đơn của shop kẹt ở kho không cập nhật trạng thái", "Tracking / status"),
    ("Rider", "Hub xử lý đơn quá chậm, 10h mới có hàng", "Hub processing delay"),
    ("Rider", "kho chia hang cham tai xe phai doi 3 tieng", "Hub processing delay"),
    ("Seller", "Tiền COD chưa được đối soát", "COD"),
    ("Rider", "App tài xế không đăng nhập được", "App issue"),
    ("Seller", "Đơn giao thất bại 2 lần rồi, giờ shop phải làm gì?", "Failed delivery"),
    ("Customer", "Hàng bị móp méo, vỡ đồ bên trong", "Lost / damaged parcel"),
])
def test_rule_labels(stk, text, expected):
    r = clf.classify(stk, text, rating=1)
    assert r["sub_issue"] == expected, r
    assert r["confidence"] == "High"
    assert r["matched_signal"]
    for k in ("stakeholder", "issue_group", "priority", "owner", "confidence", "matched_signal", "reason",
              "human_review_flag"):
        assert k in r


def test_typo_fuzzy_match():
    r = clf.classify("Customer", "shipper bao giao khong thanh cogn nhung toi o nha", rating=1)
    assert r["sub_issue"] == "Failed delivery"
    assert "~" in r["matched_signal"] and "fuzzy" in r["reason"]


def test_multi_issue_is_flagged_for_llm():
    r = clf.classify("Customer", "Giao chậm quá, còn phí ship cao quá so với chỗ khác", rating=1)
    assert r["sub_issue"] == "Late delivery"
    assert "Fee" in r["secondary_issues"]
    assert r["llm_candidate"] and "multi_issue" in r["llm_reason"]


def test_dropdown_conflict_and_fallback():
    r = clf.classify("Customer", "Đơn giao trễ quá", rating=1, dropdown="Fee")
    assert r["sub_issue"] == "Late delivery" and r["confidence"] == "Medium"
    assert "dropdown_text_conflict" in r["llm_reason"]
    r = clf.classify("Customer", "", rating=1, dropdown="Fee")
    assert r["sub_issue"] == "Fee" and "dropdown" in r["matched_signal"]


def test_unclear_and_positive():
    r = clf.classify("Customer", "tệ", rating=1)
    assert r["sub_issue"] == "Unclear" and not r["llm_candidate"]              # too short -> no LLM spend
    r = clf.classify("Customer", "Mình đợi mãi mà chẳng thấy đâu, lần sau chắc không dùng nữa", rating=1)
    assert r["confidence"] == "Low" and r["llm_candidate"]
    r = clf.classify("Customer", "Giao nhanh, shipper thân thiện", rating=5)
    assert r["sub_issue"] == "Non-actionable" and not r["is_negative"]


def test_stakeholder_context_preserved():
    idx_c = clf.classify("Customer", "Đơn giao trễ", rating=1)
    idx_s = clf.classify("Seller", "Đơn của shop bị giao trễ", rating=1)
    assert idx_c["sub_issue"] == idx_s["sub_issue"] == "Late delivery"
    assert idx_c["stakeholder"] == "Customer" and idx_s["stakeholder"] == "Seller"


def test_seller_support_owner_is_ss():
    assert clf.classify("Seller", "gửi yêu cầu mà không ai trả lời", rating=1)["owner"] == "SS"
    assert clf.classify("Customer", "gửi yêu cầu mà không ai trả lời", rating=1)["owner"] == "CS"


def test_accuracy_against_synthetic_ground_truth(cleaned, data_dir):
    voc = cleaned[0]
    c = classify_frame(voc)
    gt = pd.read_csv(f"{data_dir}/_ground_truth.csv")
    m = c.merge(gt, on="feedback_id")
    neg = m[m["true_sub_issue"] != "Positive"]
    acc = (neg["sub_issue"] == neg["true_sub_issue"]).mean()
    assert acc >= 0.90, acc
    assert c["llm_candidate"].mean() < 0.10          # LLM only on a small subset


# ------------------------------------------------------------------ Layer 2
def _frame():
    rows = [("Customer", "Mình đợi mãi mà chẳng thấy đâu, lần sau chắc không dùng nữa", 1, ""),
            ("Customer", "Giao chậm quá, còn phí ship cao quá so với chỗ khác", 1, ""),
            ("Customer", "Giao nhanh", 5, "")]
    voc = pd.DataFrame(rows, columns=["stakeholder_type", "comment", "rating", "issue_type"])
    voc["comment_norm"] = [normalize(c) for c in voc["comment"]]
    return classify_frame(voc)


def test_llm_none_keeps_rules():
    df, st = apply_llm(_frame(), provider="none", verbose=False)
    assert st["candidates"] == 2 and st["applied"] == 0
    assert set(df.loc[df["llm_candidate"], "llm_status"]) == {"not_run"}


def test_llm_mock_applies_valid_labels(tmp_path, monkeypatch):
    monkeypatch.setattr("spx_voo.llm_classifier.CACHE_PATH", str(tmp_path / "c.json"))
    df, st = apply_llm(_frame(), provider="mock", verbose=False)
    assert st["applied"] == 2
    assert df.iloc[0]["sub_issue"] == "Late delivery" and df.iloc[0]["classified_by"] == "rule+llm"
    assert df.iloc[2]["classified_by"] == "rule"                   # non-candidates never sent


def test_llm_invalid_output_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr("spx_voo.llm_classifier.CACHE_PATH", str(tmp_path / "c.json"))
    bad = lambda recs: json.dumps({"results": [{"id": r["id"], "issue_group": "Delivery",
                                                "sub_issue": "Alien abduction", "confidence": "High"} for r in recs]})
    monkeypatch.setitem(__import__("spx_voo.llm_classifier", fromlist=["x"]).PROVIDERS, "mock", bad)
    before = _frame()
    df, st = apply_llm(before, provider="mock", verbose=False)
    assert st["rejected_invalid"] == 2 and st["applied"] == 0
    assert list(df["sub_issue"]) == list(before["sub_issue"])


def test_llm_network_error_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr("spx_voo.llm_classifier.CACHE_PATH", str(tmp_path / "c.json"))
    def boom(recs):
        raise TimeoutError("simulated")
    monkeypatch.setitem(__import__("spx_voo.llm_classifier", fromlist=["x"]).PROVIDERS, "mock", boom)
    before = _frame()
    df, st = apply_llm(before, provider="mock", verbose=False)
    assert st["errors"] == 2 and list(df["sub_issue"]) == list(before["sub_issue"])


def test_parse_and_validate():
    assert parse_results('```json\n{"results":[{"id":"1"}]}\n```') == [{"id": "1"}]
    assert parse_results("garbage") == []
    assert validate_item({"issue_group": "Delivery", "sub_issue": "Late delivery", "confidence": "High",
                          "secondary_issues": []})
    assert not validate_item({"issue_group": "Payment / Money", "sub_issue": "Late delivery", "confidence": "High"})
