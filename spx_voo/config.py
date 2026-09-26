# -*- coding: utf-8 -*-
"""Configuration loading. All business vocabulary lives in /config/*.yaml, not in code."""
import os
from functools import lru_cache

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.environ.get("SPX_VOO_CONFIG_DIR", os.path.join(ROOT, "config"))
DEFAULT_DATA_DIR = os.path.join(ROOT, "data", "synthetic")
DEFAULT_OUT_DIR = os.path.join(ROOT, "outputs")

STAKEHOLDERS = ["Customer", "Seller", "Rider"]


@lru_cache(maxsize=None)
def load_yaml(name):
    with open(os.path.join(CONFIG_DIR, name), encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def taxonomy():
    return load_yaml("taxonomy.yaml")


def drivers():
    return load_yaml("drivers.yaml")


def priority_cfg():
    return load_yaml("priority.yaml")


def sub_issue_index():
    """{sub_issue: {group, owner, severity, ...}} flattened from taxonomy.yaml."""
    idx = {}
    for group, g in taxonomy()["groups"].items():
        for sub, s in (g.get("sub_issues") or {}).items():
            idx[sub] = {"group": group, **(s or {})}
    return idx
