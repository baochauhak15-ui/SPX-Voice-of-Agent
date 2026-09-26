# -*- coding: utf-8 -*-
"""Layer 1 — rule-based VOC classification (runs on 100 % of records).

Lessons kept from the reference `voc_rules_v2`:
  * free text first; the survey dropdown (`issue_type`) is only a FALLBACK when text is empty/unclear,
    and a CONFLICT signal when it disagrees with the text
  * multi-dimensional output instead of a single label
  * every decision carries `matched_signal` + `reason` so it can be audited

Output columns per record:
  stakeholder, issue_group, sub_issue, secondary_issues, priority, owner, confidence, matched_signal,
  reason, human_review_flag, is_negative, llm_candidate, llm_reason, classified_by
"""
from .config import sub_issue_index, taxonomy
from .text_utils import match_keywords, normalize

UNCLEAR_MIN_LEN = 15          # reference rule: free text >= 15 chars without a match -> LLM review, else noise
_STK_KEY = {"Customer": "customer", "Seller": "seller", "Rider": "rider"}


class RuleClassifier:
    def __init__(self):
        self.tax = taxonomy()
        self.idx = sub_issue_index()
        self._kw = {}
        for sub, meta in self.idx.items():
            kws = meta.get("keywords") or {}
            for stk in ("customer", "seller", "rider"):
                self._kw[(sub, stk)] = list(kws.get("any") or []) + list(kws.get(stk) or [])
        sent = self.tax.get("sentiment") or {}
        self._pos, self._neg = sent.get("positive") or [], sent.get("negative") or []
        # dropdown label -> sub-issue (accent/case-insensitive)
        self._dropdown = {normalize(s): s for s in self.idx}

    # ------------------------------------------------------------------ core
    def _match(self, norm, stk, fuzzy):
        found = {}
        for sub in self.idx:
            hits = match_keywords(norm, self._kw[(sub, stk)], fuzzy=fuzzy)
            if hits:
                found[sub] = hits
        return found

    def classify(self, stakeholder, comment, rating=None, dropdown="", comment_norm=None):
        stk = _STK_KEY.get(stakeholder, "customer")
        norm = comment_norm if comment_norm is not None else normalize(comment)
        found = self._match(norm, stk, fuzzy=False)
        rating = None if rating is None or rating != rating else float(rating)
        if not found and len(norm) >= UNCLEAR_MIN_LEN and (rating is None or rating <= 3):
            found = self._match(norm, stk, fuzzy=True)          # typo tolerance, only when exact failed

        drop_sub = self._dropdown.get(normalize(dropdown)) if dropdown else None
        long_text = len(norm) >= UNCLEAR_MIN_LEN

        res = {"stakeholder": stakeholder, "secondary_issues": "", "matched_signal": "", "llm_reason": ""}
        if found:
            # primary = most keyword hits, then longest matched evidence, then severity
            # (multi-issue comments usually lead with the main complaint -> earliest position breaks ties)
            ranked = sorted(found.items(), key=lambda kv: (-len(kv[1]), self._first_pos(norm, kv[1]),
                                                           -self.idx[kv[0]].get("severity", 0)))
            sub = ranked[0][0]
            groups = {self.idx[s]["group"] for s in found}
            res.update(sub_issue=sub, secondary_issues="; ".join(s for s, _ in ranked[1:]),
                       matched_signal="; ".join(f"{s}: {', '.join(h)}" for s, h in ranked))
            conflict = bool(drop_sub) and drop_sub not in found and drop_sub in self.idx \
                and self.idx[drop_sub]["group"] != "Other"
            if len(groups) == 1 and not conflict:
                conf, why = "High", f"text keywords -> {sub}"
            else:
                conf = "Medium"
                why = f"text keywords -> {sub}"
                if len(groups) > 1:
                    why += f"; multi-issue ({len(groups)} groups)"
                if conflict:
                    why += f"; dropdown says '{drop_sub}' (conflict)"
            if any(h.endswith("~") for _, hs in ranked for h in hs):
                why += "; fuzzy match (typo)"
            is_neg = rating is None or rating <= 3
            if is_neg and rating is not None and rating >= 3 and match_keywords(norm, self._pos, fuzzy=False) \
                    and not match_keywords(norm, self._neg, fuzzy=False):
                is_neg = False
                why += "; positive wording, rating 3 -> not a complaint"
            res.update(confidence=conf, reason=why, conflict=conflict, multi_issue=len(groups) > 1)
        elif drop_sub and drop_sub in self.idx and (rating is None or rating <= 3):
            res.update(sub_issue=drop_sub, matched_signal=f"dropdown: {dropdown}",
                       confidence="Medium" if not long_text else "Low",
                       reason="no text signal; fell back to survey dropdown", conflict=False, multi_issue=False)
            is_neg = True
        else:
            if rating is not None and rating >= 4:
                sub, why, is_neg = "Non-actionable", "positive rating, no complaint signal", False
            elif rating is not None and rating == 3:
                sub, why, is_neg = "Non-actionable", "neutral rating, no complaint signal", False
            else:
                sub, is_neg = "Unclear", True
                why = "negative but no business signal" + ("" if long_text else " (too short)")
            res.update(sub_issue=sub, confidence="Low" if (is_neg and long_text) else "High",
                       reason=why, conflict=False, multi_issue=False)

        meta = self.idx[res["sub_issue"]]
        res["issue_group"] = meta["group"]
        res["owner"] = meta.get("owner", "CS")
        if stakeholder == "Seller" and res["owner"] == "CS":
            res["owner"] = "SS"                       # Seller Success owns seller-facing support
        res["is_negative"] = bool(is_neg) and res["sub_issue"] != "Non-actionable"
        res["priority"] = self._record_priority(res, rating, meta)

        # ---- LLM gate (Layer 2 only where it adds value)
        reasons = []
        if res["is_negative"]:
            if res["confidence"] == "Low" and long_text:
                reasons.append("low_confidence")
            if res.get("conflict"):
                reasons.append("dropdown_text_conflict")
            if res.get("multi_issue"):
                reasons.append("multi_issue")
        res["llm_candidate"] = bool(reasons)
        res["llm_reason"] = ",".join(reasons)
        res["human_review_flag"] = bool(res["is_negative"] and (res["confidence"] == "Low" or res.get("conflict")
                                                               or res["priority"] == "P1"))
        res["classified_by"] = "rule"
        res.pop("conflict", None)
        res.pop("multi_issue", None)
        return res

    @staticmethod
    def _first_pos(norm, hits):
        import re
        best = len(norm)
        for h in hits:
            h = h.rstrip("~")
            m = re.search(h[3:], norm) if h.startswith("re:") else re.search(re.escape(normalize(h)), norm)
            if m:
                best = min(best, m.start())
        return best

    @staticmethod
    def _record_priority(res, rating, meta):
        """Record-level priority (review queue). Insight-level priority is computed later."""
        if not res["is_negative"] or res["issue_group"] == "Other":
            return "P3"
        sev = meta.get("severity", 1)
        if sev >= 5 or (sev >= 4 and rating is not None and rating <= 1):
            return "P1"
        if sev >= 3 or (rating is not None and rating <= 1):
            return "P2"
        return "P3"


def classify_frame(voc):
    """Apply rules to a cleaned VOC frame; returns a new frame with classification columns."""
    clf = RuleClassifier()
    out = [clf.classify(s, c, r, d, n) for s, c, r, d, n in
           zip(voc["stakeholder_type"], voc["comment"], voc["rating"], voc["issue_type"], voc["comment_norm"])]
    import pandas as pd
    cls = pd.DataFrame(out, index=voc.index).drop(columns=["stakeholder"])
    return pd.concat([voc, cls], axis=1)
