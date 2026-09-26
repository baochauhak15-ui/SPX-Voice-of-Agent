# -*- coding: utf-8 -*-
"""Vietnamese text normalisation + keyword matching robust to accents, typos and teen code.

Pattern reused from the reference `voc_rules_v2.strip_vi` / `_wb`, extended with:
  * abbreviation / teen-code expansion (config/normalization.yaml)
  * repeated-letter collapse ("lauuuu" -> "lau")
  * light fuzzy matching for long single tokens (typos such as "tre hen" vs "tre hne")
"""
import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache

from .config import load_yaml

_NORM = load_yaml("normalization.yaml")
_ABBR = {k: v for k, v in (_NORM.get("abbreviations") or {}).items()}
_PHRASES = list((_NORM.get("phrases") or {}).items())


def strip_accents(text):
    if text is None:
        return ""
    t = unicodedata.normalize("NFD", str(text))
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return t.replace("đ", "d").replace("Đ", "D")


@lru_cache(maxsize=50000)
def normalize(text):
    """Return canonical accent-free, lower-case, abbreviation-expanded text."""
    if text is None:
        return ""
    t = strip_accents(str(text)).lower()
    t = re.sub(r"(\d+)\s*h\b", r"\1 gio", t)                 # "10h" -> "10 gio"
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"([a-z])\1{2,}", r"\1", t)                     # lauuuu -> lau, quaaa -> qua
    toks = [_ABBR.get(tok, tok) for tok in t.split()]
    t = " " + " ".join(toks) + " "
    for a, b in _PHRASES:
        t = t.replace(f" {a} ", f" {b} ")
    return re.sub(r"\s+", " ", t).strip()


def _wb_find(text, kw):
    return re.search(r"(?:^|\s)" + re.escape(kw) + r"(?:$|\s)", text) is not None


def _fuzzy_phrase(text_tokens, kw_tokens, threshold=0.88):
    """Sliding-window fuzzy match of a multi-token keyword; only used for keywords >= 9 chars.
    The window must start with the same letter (cheap guard against false positives)."""
    n = len(kw_tokens)
    kw = " ".join(kw_tokens)
    for i in range(0, max(0, len(text_tokens) - n) + 1):
        if text_tokens[i][:1] != kw_tokens[0][:1]:
            continue
        window = " ".join(text_tokens[i:i + n])
        if abs(len(window) - len(kw)) <= 2 and SequenceMatcher(None, window, kw).ratio() >= threshold:
            return True
    return False


@lru_cache(maxsize=None)
def _regex(p):
    return re.compile(p)


def match_keywords(norm_text, keywords, fuzzy=True):
    """Return list of keywords found in already-normalised text."""
    hits = []
    if not norm_text:
        return hits
    toks = norm_text.split()
    for kw in keywords:
        if kw.startswith("re:"):
            if re.search(_regex(kw[3:]), norm_text):
                hits.append(kw)
            continue
        k = normalize(kw)
        if not k:
            continue
        if _wb_find(norm_text, k):
            hits.append(kw)
        elif fuzzy and len(k) >= 9 and _fuzzy_phrase(toks, k.split()):
            hits.append(kw + "~")                                 # "~" marks a fuzzy hit (explainability)
    return hits
