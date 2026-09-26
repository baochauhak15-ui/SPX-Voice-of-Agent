import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory):
    from generate_synthetic_data import generate
    d = tmp_path_factory.mktemp("synthetic")
    generate(str(d), seed=42)
    return str(d)


@pytest.fixture(scope="session")
def cleaned(data_dir):
    from spx_voo.data_loader import load_all
    from spx_voo.data_cleaner import clean
    from spx_voo.linker import link
    voc, t, ops, hc, dq = clean(load_all(data_dir))
    return link(voc, t, ops), t, ops, hc, dq
