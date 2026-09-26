# -*- coding: utf-8 -*-
"""Layer 2 — LLM relabelling, ONLY for records the rule layer flagged (`llm_candidate`).

Reference pattern kept: gate -> batch -> JSON parse -> validate against the controlled taxonomy ->
fallback to the rule result on any error. The allowed label set is built from config/taxonomy.yaml,
so the LLM can never introduce a label the business did not define.

Providers (env LLM_PROVIDER):
  none   (default)  no call; candidates stay flagged for human review
  openai            any OpenAI-compatible /chat/completions endpoint (LLM_BASE_URL, LLM_MODEL, LLM_API_KEY)
  mock              deterministic offline stub used by tests and the offline demo
"""
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request

from .config import ROOT, sub_issue_index

PROMPT_VERSION = "spx-voo-llm-v1"
VALID_CONF = {"High", "Medium", "Low"}
BATCH = int(os.environ.get("LLM_BATCH", "20"))
CACHE_PATH = os.environ.get("LLM_CACHE", os.path.join(ROOT, "outputs", ".llm_cache.json"))


def _taxonomy_block():
    idx = sub_issue_index()
    lines = []
    for sub, m in idx.items():
        meaning = m.get("stakeholder_meaning") or {}
        lines.append(f"- {m['group']} > {sub}: " + "; ".join(f"{k}: {v}" for k, v in meaning.items()))
    return "\n".join(lines)


SYSTEM_PROMPT = f"""You classify SPX Express (Vietnam logistics) Voice-of-Operations feedback.
Each record comes from a CUSTOMER (buyer), a SELLER (shop) or a RIDER (driver). Keep the stakeholder's
perspective: the same words mean different things for each (e.g. "chờ lâu" from a rider usually means
waiting at the hub; from a customer it means late delivery).
Text is Vietnamese, often without accents, with typos and teen code (ko=không, dc=được, ship=giao).
Pick labels ONLY from this controlled taxonomy (group > sub_issue):
{_taxonomy_block()}
Rules: choose the MAIN complaint as sub_issue, list other complaints in secondary_issues (sub_issue names).
If there is no business signal use Other > Unclear. Never invent labels.
Return JSON: {{"results": [{{"id": str, "issue_group": str, "sub_issue": str, "secondary_issues": [str],
"confidence": "High"|"Medium"|"Low", "reason": str (short, English)}}]}}. JSON only."""


# ---------------------------------------------------------------------------- providers
def _call_openai(records):
    base = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    if not key:
        raise RuntimeError("LLM_API_KEY / OPENAI_API_KEY not set")
    payload = {
        "model": model, "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": json.dumps(records, ensure_ascii=False)}],
    }
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=float(os.environ.get("LLM_TIMEOUT", "60"))) as r:
                body = json.loads(r.read().decode())
            return body["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:           # 429 backoff (reference behaviour)
            if e.code == 429 and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise


def _call_mock(records):
    """Deterministic stand-in: re-reads the rule hints and resolves the obvious cases the way a model
    would (e.g. keeps the earliest-mentioned issue). It exists to exercise the Layer-2 plumbing
    (gating, validation, fallback, audit columns) offline — NOT to claim model accuracy."""
    out = []
    for r in records:
        subs = [s.strip() for s in (r.get("rule_sub_issue", ""), *r.get("rule_secondary", [])) if s.strip()]
        text = r["comment"].lower()
        if "doi mai" in text or "đợi mãi" in text or "chua toi" in text or "chưa tới" in text:
            pick, conf, why = "Late delivery", "Medium", "waiting with no delivery -> late delivery"
        elif "đứng chờ" in text or "dung cho" in text:
            pick, conf, why = "Hub processing delay", "Medium", "rider waiting before route -> hub delay"
        elif subs:
            pick, conf, why = subs[0], "Medium", "kept main complaint, others secondary"
        else:
            pick, conf, why = "Unclear", "Low", "no business signal"
        out.append({"id": r["id"], "issue_group": sub_issue_index()[pick]["group"], "sub_issue": pick,
                    "secondary_issues": [s for s in subs if s != pick], "confidence": conf, "reason": why})
    return json.dumps({"results": out})


PROVIDERS = {"openai": _call_openai, "mock": _call_mock}


# ---------------------------------------------------------------------------- parsing / validation
def parse_results(text):
    text = str(text).strip()
    text = re.sub(r"^```[a-zA-Z]*|```$", "", text).strip()
    try:
        obj = json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}|\[.*\]", text, re.S)
        if not m:
            return []
        try:
            obj = json.loads(m.group(0))
        except Exception:
            return []
    if isinstance(obj, dict):
        obj = obj.get("results", [obj])
    return obj if isinstance(obj, list) else []


def validate_item(it, idx=None):
    """True only if the item uses the controlled taxonomy."""
    idx = idx or sub_issue_index()
    if not isinstance(it, dict):
        return False
    sub = it.get("sub_issue")
    if sub not in idx or idx[sub]["group"] != it.get("issue_group"):
        return False
    if it.get("confidence") not in VALID_CONF:
        return False
    sec = it.get("secondary_issues") or []
    if not isinstance(sec, list) or any(s not in idx for s in sec):
        return False
    return True


# ---------------------------------------------------------------------------- cache
def _key(r):
    return hashlib.sha1(f"{PROMPT_VERSION}|{r['stakeholder']}|{r['comment']}".encode()).hexdigest()


def _load_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(c):
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False)
    except Exception:
        pass


# ---------------------------------------------------------------------------- main entry
def apply_llm(df, provider=None, verbose=True):
    """Relabel `llm_candidate` rows in place-safe copy. Adds llm_status / llm_label columns."""
    provider = (provider or os.environ.get("LLM_PROVIDER", "none")).lower()
    df = df.copy()
    df["llm_status"] = ""
    df.loc[df["llm_candidate"], "llm_status"] = "not_run" if provider == "none" else "pending"
    df["llm_label"] = ""
    stats = {"provider": provider, "candidates": int(df["llm_candidate"].sum()), "applied": 0,
             "rejected_invalid": 0, "errors": 0, "cached": 0}
    if provider == "none" or stats["candidates"] == 0:
        return df, stats
    call = PROVIDERS.get(provider)
    if call is None:
        raise ValueError(f"unknown LLM_PROVIDER {provider!r}")

    idx = sub_issue_index()
    cache = _load_cache()
    cand = df[df["llm_candidate"]]
    todo, results = [], {}
    for i, row in cand.iterrows():
        rec = {"id": str(i), "stakeholder": row["stakeholder_type"], "comment": row["comment"],
               "rating": None if row["rating"] != row["rating"] else int(row["rating"]),
               "survey_dropdown": row["issue_type"], "rule_sub_issue": row["sub_issue"],
               "rule_secondary": [s for s in str(row["secondary_issues"]).split("; ") if s]}
        k = _key(rec)
        if k in cache:
            results[i] = cache[k]
            stats["cached"] += 1
        else:
            todo.append((i, k, rec))
    for b in range(0, len(todo), BATCH):
        chunk = todo[b:b + BATCH]
        try:
            items = parse_results(call([c[2] for c in chunk]))
        except Exception as e:                                   # network / auth / timeout -> keep rules
            stats["errors"] += len(chunk)
            if verbose:
                print(f"  [llm] batch failed ({type(e).__name__}: {e}); keeping rule labels")
            for i, _, _ in chunk:
                df.at[i, "llm_status"] = "error_kept_rule"
            continue
        by_id = {str(it.get("id")): it for it in items if isinstance(it, dict)}
        for i, k, _ in chunk:
            it = by_id.get(str(i))
            results[i] = it
            if it is not None:
                cache[k] = it
    _save_cache(cache)

    for i, it in results.items():
        if it is None or not validate_item(it, idx):
            stats["rejected_invalid"] += 1
            df.at[i, "llm_status"] = "invalid_kept_rule"
            continue
        df.at[i, "llm_label"] = it["sub_issue"]
        df.at[i, "llm_status"] = "applied"
        stats["applied"] += 1
        if it["sub_issue"] != df.at[i, "sub_issue"]:
            df.at[i, "reason"] = f"LLM: {it.get('reason', '')} (rule said {df.at[i, 'sub_issue']})"
        m = idx[it["sub_issue"]]
        df.at[i, "sub_issue"] = it["sub_issue"]
        df.at[i, "issue_group"] = m["group"]
        owner = m.get("owner", "CS")
        df.at[i, "owner"] = "SS" if (owner == "CS" and df.at[i, "stakeholder_type"] == "Seller") else owner
        df.at[i, "secondary_issues"] = "; ".join(it.get("secondary_issues") or [])
        df.at[i, "confidence"] = it["confidence"]
        df.at[i, "classified_by"] = "rule+llm"
        df.at[i, "human_review_flag"] = it["confidence"] == "Low"
    return df, stats
