import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_run_local_demo(tmp_path, data_dir):
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, os.path.join(ROOT, "run_local.py"), "--mode", "demo", "--data", data_dir,
                        "--out", str(out)], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    assert "CROSS-STAKEHOLDER OPERATIONAL ISSUE DETECTED" in r.stdout
    files = set(os.listdir(out))
    for f in ("SPX_Voice_of_Operations_Dashboard.html", "SPX_Action_List.csv", "SPX_Action_List.xlsx",
              "voc_classified.csv", "insights.json"):
        assert f in files
    assert any(f.startswith("SPX_Daily_Operations_Intelligence_") for f in files)
    assert any(f.startswith("SPX_Weekly_VOC_Root_Cause_Report_") for f in files)
    assert any(f.startswith("SPX_Monthly_Operations_Intelligence_") for f in files)
    dash = (out / "SPX_Voice_of_Operations_Dashboard.html").read_text(encoding="utf-8")
    assert "SPX Voice of Operations" in dash and "/*__DATA__*/" not in dash
    ins = json.loads((out / "insights.json").read_text(encoding="utf-8"))
    top = ins["insights"][0]
    assert top["headline"] == "Cross-stakeholder operational issue detected"
    assert top["potential_root_cause"] == "Hub processing delay"
    assert set(top["affected_stakeholders"]) == {"Customer", "Seller", "Rider"}
    assert "Operations investigation" in top["recommended_actions"][0]["action"]


def test_run_with_mock_llm(tmp_path, data_dir, monkeypatch):
    out = tmp_path / "out2"
    env = dict(os.environ, LLM_CACHE=str(tmp_path / "cache.json"))
    r = subprocess.run([sys.executable, os.path.join(ROOT, "run_local.py"), "--mode", "weekly", "--data", data_dir,
                        "--out", str(out), "--llm", "mock"], capture_output=True, text=True, timeout=300, env=env)
    assert r.returncode == 0, r.stderr
    assert "provider=mock" in r.stdout
