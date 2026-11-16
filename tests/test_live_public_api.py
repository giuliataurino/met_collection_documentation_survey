"""Live check against the real Met public API and Perseus. Skipped unless asked for:

    RUN_LIVE=1 pytest -q tests/test_live_public_api.py

It makes a handful of real requests and no model calls.
"""
import os

import pytest

from vasepipe import cli, link, met, perseus

pytestmark = pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="set RUN_LIVE=1 to call the real APIs")


def test_public_api_to_perseus_link(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rows = met.fetch_public_api(limit=3, query="kylix")
    objs = met.prepare(rows)
    assert objs, "the public API returned no Greek and Roman vases for 'kylix'"
    assert all("greek" in o["department"].lower() for o in objs)
    records = perseus.build(perseus.download())
    assert len(records) > 1500
    rec = cli.run_one(objs[0], link.Index(records), {}, "catalogue")
    assert rec["matches"] and 0 < rec["matches"][0]["score"] <= 1
    assert rec["catalogue"]["shape"] or rec["catalogue"]["fragment"]
