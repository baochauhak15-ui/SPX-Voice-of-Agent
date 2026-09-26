import pandas as pd
import pytest

from spx_voo.data_loader import SCHEMAS, SchemaError, load_all


def test_schemas_present(data_dir):
    frames = load_all(data_dir)
    for name, cols in SCHEMAS.items():
        assert set(cols) <= set(frames[name].columns), name


def test_missing_file_raises(tmp_path):
    with pytest.raises(SchemaError):
        load_all(str(tmp_path))


def test_no_pii_like_fields(data_dir):
    frames = load_all(data_dir)
    for df in frames.values():
        for c in df.columns:
            assert not any(k in c.lower() for k in ("phone", "email", "address", "name"))


def test_clean_unifies_three_stakeholders(cleaned):
    voc, t, ops, hc, dq = cleaned
    assert set(voc["stakeholder_type"]) == {"Customer", "Seller", "Rider"}
    assert voc["feedback_id"].is_unique
    assert dq["duplicate_feedback_dropped"] == 0
    assert voc["rating"].between(1, 5).all()


def test_incident_is_visible_in_ops(cleaned):
    voc, t, ops, hc, dq = cleaned
    s = ops[ops["event_type"] == "sort_complete"]
    hub = s[s["hub"] == "HCM-ThuDuc-SOC"]
    base = hub[hub["date"] < "2026-09-13"]["processing_time"].mean()
    inc = hub[hub["date"] >= "2026-09-14"]["processing_time"].mean()
    other = s[(s["hub"] != "HCM-ThuDuc-SOC") & (s["date"] >= "2026-09-14")]["processing_time"].mean()
    assert inc > base * 1.4
    assert abs(other - base) < 1.0


def test_linking(cleaned):
    voc, *_ = cleaned
    cs = voc[voc["stakeholder_type"] != "Rider"]
    assert cs["hub_processing_hours"].notna().mean() > 0.99   # every C/S VOC has a parcel journey
    assert voc["has_ticket"].sum() > 100
    assert voc[voc["stakeholder_type"] == "Rider"]["hub_processing_hours"].isna().all()
