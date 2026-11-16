"""Offline tests for stages 3 to 6. Images are synthetic; records are invented."""
import json

import pytest
from PIL import Image, ImageDraw

from vasepipe import cli, contentdm, fragments, link, met, sources, visual


def picture(color, shape):
    im = Image.new("RGB", (200, 200), (30, 30, 30))
    draw = ImageDraw.Draw(im)
    if shape == "circle":
        draw.ellipse((40, 40, 160, 160), fill=color)
    else:
        draw.rectangle((20, 80, 180, 120), fill=color)
    return im


def obj(i, acc, title, name, begin=-500, end=-480, artist="", tags=(), image=""):
    return met.normalise({"objectID": i, "accessionNumber": acc, "title": title, "objectName": name, "culture": "Greek, Attic",
                          "objectBeginDate": begin, "objectEndDate": end, "medium": "Terracotta; red-figure",
                          "classification": "Vases", "department": "Greek and Roman Art", "tags": list(tags),
                          "artistDisplayName": artist, "primaryImageSmall": image})


# ---------------------------------------------------------------- stage 3

def test_visual_measures_separate_like_from_unlike():
    a = visual.features(picture((200, 90, 40), "circle"), use_clip=False)
    b = visual.features(picture((205, 95, 45), "circle"), use_clip=False)
    c = visual.features(picture((40, 90, 200), "bar"), use_clip=False)
    near, far = visual.pair_measures(a, b), visual.pair_measures(a, c)
    assert set(near) == {"hist", "edge", "dhash"}
    assert all(0 <= v <= 1 for v in list(near.values()) + list(far.values()))
    assert visual.combine(near) > 0.9 > 0.6 > visual.combine(far)


def test_store_round_trip_and_best_view(tmp_path):
    store = visual.Store(tmp_path / "f.npz")
    store.add("x", "view1", visual.features(picture((40, 90, 200), "bar"), use_clip=False))
    store.add("x", "view2", visual.features(picture((200, 90, 40), "circle"), use_clip=False))
    store.add("y", "view1", visual.features(picture((205, 95, 45), "circle"), use_clip=False))
    store.flush()
    again = visual.Store(tmp_path / "f.npz")
    assert len(again) == 3 and again.has("x", "view2") and not again.has("x", "view9")
    scores = visual.object_scores(again, "y", again)
    assert scores["x"]["view"] == "view2" and scores["x"]["combined"] > 0.9      # matched through the right view
    assert set(scores["x"]) >= {"combined", "hist", "edge", "dhash", "view"}


def test_build_skips_bad_images_and_resumes(tmp_path):
    good = tmp_path / "a.png"
    picture((200, 90, 40), "circle").save(good)
    store = visual.Store(tmp_path / "f.npz")
    assert visual.build(store, [("1", str(good)), ("2", str(tmp_path / "missing.png"))], use_clip=False) == (1, 1)
    assert visual.build(store, [("1", str(good))], use_clip=False) == (0, 0)       # already indexed


def test_visual_changes_the_perseus_ranking():
    recs = [{"id": i, "name": i, "url": "", "summary": "", "decoration": "", "shape_raw": "Kylix", "shape": "kylix",
             "ware": "", "technique": "red-figure", "fabric": "attic", "painter": "", "period": "", "year": -490,
             "image": ""} for i in ("p1", "p2")]
    top = link.Index(recs).match({"shape": "kylix"}, weights={"visual": 30},
                                 visual_scores={"p1": {"combined": 0.2, "edge": 0.2}, "p2": {"combined": 0.9, "edge": 0.9}})
    assert [m["id"] for m in top] == ["p2", "p1"] and top[0]["visual"]["edge"] == 0.9
    assert top[0]["components"]["visual"] == 1.0 and top[1]["components"]["visual"] == 0.0


# ---------------------------------------------------------------- stage 4

FRAGS = [obj(1, "1985.228.8a", "Terracotta rim fragment of a kylix (drinking cup)", "Kylix fragment",
             artist="Attributed to the Brygos Painter", tags=["Satyrs", "Maenads"]),
         obj(2, "1985.228.8b", "Terracotta foot fragment of a kylix (drinking cup)", "Kylix fragment",
             artist="Attributed to the Brygos Painter", tags=["Satyrs"]),
         obj(3, "11.212.5", "Terracotta fragment of a kylix (drinking cup)", "Kylix fragment", tags=["Youths"]),
         obj(4, "06.1021.99", "Terracotta foot fragment of a kylix (drinking cup)", "Kylix fragment", begin=-380, end=-350),
         obj(5, "X.1", "Terracotta fragment of a hydria (water jar)", "Hydria fragment", tags=["Satyrs"])]


def test_fragment_records_read_parts_and_painter():
    f = fragments.from_met(FRAGS[0])
    assert f["parts"] == ["rim"] and f["attribution"] == "brygos painter" and f["shape"] == "kylix" and f["is_fragment"]


def test_same_accession_and_painter_is_strong_generic_agreement_is_not():
    pool = [fragments.from_met(o) for o in FRAGS]
    by = {r["name"]: r for r in fragments.propose(pool, min_confidence=0)}
    best = by["1985.228.8a"]["candidates"][0]
    assert best["name"] == "1985.228.8b" and best["tier"] == "strong" and best["evidence"]["accession"] == 1.0
    other = next(c for c in by["1985.228.8a"]["candidates"] if c["name"] == "11.212.5")
    assert other["tier"] == "weak" and other["confidence"] < 0.4          # same shape, technique, date: not enough
    names = lambda n: {c["name"] for c in by[n]["candidates"]}
    assert "06.1021.99" not in names("1985.228.8a")                       # a century apart
    assert "X.1" not in names("1985.228.8a") and not by["X.1"]["candidates"]  # a hydria cannot join a kylix


def test_two_feet_cannot_share_a_vase_and_visual_evidence_counts():
    a, b = fragments.from_met(FRAGS[1]), fragments.from_met(obj(9, "X.9", "Terracotta foot fragment of a kylix", "Kylix fragment"))
    assert fragments.score_pair(a, b)["evidence"]["parts"] == 0.1
    c = fragments.from_met(FRAGS[2])
    plain = fragments.score_pair(fragments.from_met(FRAGS[0]), c, 0.5)
    seen = fragments.score_pair(fragments.from_met(FRAGS[0]), c, 0.5, {"combined": 0.9, "edge": 0.9})
    assert seen["confidence"] > plain["confidence"] and seen["tier"] == "possible" and seen["measures"]["edge"] == 0.9


# ---------------------------------------------------------------- stages 5 and 6

PERSEUS = {"aa_1": {"id": "aa_1", "name": "Berlin F 2285", "url": "u1", "beazley_number": "205092", "painter": "Attributed to the Brygos Painter",
                    "potter": "", "findspot": "Vulci", "citations": ["ARV2, 369.1"], "sources_used": ["Boardman 1975"],
                    "comparanda": ["Louvre G 152", "Nowhere 1"]},
           "aa_2": {"id": "aa_2", "name": "Louvre G 152", "url": "u2", "beazley_number": "", "painter": "", "potter": "",
                    "findspot": "", "citations": [], "sources_used": [], "comparanda": []}}
RUN = {"objectID": "1", "accessionNumber": "1985.228.8a", "title": "Rim fragment", "catalogue": {"shape": "kylix", "technique": "red-figure"},
       "model": {"shape_id": "eye-cup", "technique_id": "red-figure", "subjects": ["satyrs", "maenads"]},
       "matches": [{"id": "aa_1", "name": "Berlin F 2285", "score": 0.82, "painter": "Attributed to the Brygos Painter"},
                   {"id": "aa_2", "name": "Louvre G 152", "score": 0.41, "painter": ""}]}


def test_terms_references_and_queries():
    by_name = {r["name"]: r for r in PERSEUS.values()}
    item = sources.enrich(RUN, PERSEUS, by_name, use_contentdm=False)
    kinds = {(t["kind"], t["term"]) for t in item["terms"]}
    assert {("accession", "1985.228.8a"), ("shape", "eye-cup"), ("shape", "kylix"), ("greek", "κύλιξ"),
            ("technique", "red-figure"), ("painter", "Brygos Painter"), ("subject", "satyrs")} <= kinds
    ref = item["references"][0]
    assert len(item["references"]) == 1 and ref["beazley_number"] == "205092" and ref["citations"] == ["ARV2, 369.1"]
    assert ref["comparanda"] == [{"name": "Louvre G 152", "url": "u2"}, {"name": "Nowhere 1", "url": None}]
    q = item["queries"]
    assert q[0] == {"term": "1985.228.8a", "mode": "exact", "weight": 5.0, "kind": "accession"}
    assert [x["kind"] for x in q] == ["accession", "painter", "technique + shape", "subject + shape", "subject + shape", "shape"]
    assert not any("κ" in x["term"] for x in q)
    assert any("lexicon" in l["label"] for l in item["links"])


def test_contentdm_url_and_merge(monkeypatch):
    monkeypatch.delenv("CONTENTDM_BASE_URL", raising=False)
    monkeypatch.delenv("CONTENTDM_COLLECTIONS", raising=False)
    monkeypatch.delenv("CONTENTDM_FIELDS", raising=False)
    url = contentdm.query_url("Brygos/Painter ^x", "exact", 5)
    assert url.endswith("?q=dmQuery/all/CISOSEARCHALL^Brygos%20Painter%20x^exact^and/title!creato!date!subjec!descri/nosort/5/1/0/0/0/0/0/0/json")
    answers = {"1985.228.8a": [{"collection": "/p1", "pointer": 7, "title": "Bulletin 1986", "creato": {}, "date": "1986"}],
               "Greek kylix": [{"collection": "/p1", "pointer": 7, "title": "Bulletin 1986"}, {"collection": "/p2", "pointer": 3, "title": "Handbook"}]}
    monkeypatch.setattr(contentdm, "_get", lambda url, **kw: {"pager": {"total": 2}, "records": next(v for k, v in answers.items() if k.replace(" ", "%20") in url)})
    results, log = contentdm.find([{"term": "1985.228.8a", "mode": "exact", "weight": 5.0, "kind": "accession"},
                                   {"term": "Greek kylix", "mode": "all", "weight": 1.0, "kind": "shape"}])
    assert [(r["pointer"], r["score"]) for r in results] == [(7, 6.0), (3, 1.0)]
    assert results[0]["url"] == "https://libmma.contentdm.oclc.org/digital/collection/p1/id/7" and results[0]["creator"] == ""
    assert [m["kind"] for m in results[0]["matched"]] == ["accession", "shape"] and log[0]["total"] == 2


def test_contentdm_outage_is_recorded_not_fatal(monkeypatch):
    def down(url, **kw):
        raise contentdm.ContentdmError("Could not reach CONTENTdm at x: ConnectionError")
    monkeypatch.setattr(contentdm, "_get", down)
    results, log = contentdm.find([{"term": "a", "weight": 1}, {"term": "b", "weight": 1}])
    assert results == [] and len(log) == 1 and "reach" in log[0]["error"]


# ---------------------------------------------------------------- command line, end to end

def test_commands_chain_together(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "DATA", tmp_path / "data")
    monkeypatch.setattr(cli, "MET_FEATURES", tmp_path / "data" / "features_met.npz")
    monkeypatch.setattr(cli, "PERSEUS_FEATURES", tmp_path / "data" / "features_perseus.npz")
    (tmp_path / "data").mkdir()
    imgs = {}
    for name, (color, shape) in {"a": ((200, 90, 40), "circle"), "b": ((205, 95, 45), "circle"), "c": ((40, 90, 200), "bar")}.items():
        imgs[name] = str(tmp_path / f"{name}.png")
        picture(color, shape).save(imgs[name])
    objs = [dict(FRAGS[0], primaryImageSmall=imgs["a"]), dict(FRAGS[1], primaryImageSmall=imgs["b"]), dict(FRAGS[2], primaryImageSmall=imgs["c"])]
    (tmp_path / "data" / "met_objects.json").write_text(json.dumps(objs))
    base = {"collection": "Berlin", "shape_raw": "Kylix", "shape": "kylix", "ware": "Attic Red Figure", "technique": "red-figure",
            "fabric": "attic", "period": "Archaic", "year": -490, "year_estimated": False, "summary": "Satyrs and maenads",
            "decoration": "", "shape_description": "", "image": "", "fragment": False, "condition": ""}
    (tmp_path / "data" / "perseus.json").write_text(json.dumps([dict(base, **PERSEUS["aa_1"]), dict(base, **PERSEUS["aa_2"], fragment=True)]))
    perseus_store = visual.Store(cli.PERSEUS_FEATURES)
    perseus_store.add("aa_1", "v", visual.features(picture((200, 90, 40), "circle"), use_clip=False))
    perseus_store.add("aa_2", "v", visual.features(picture((40, 90, 200), "bar"), use_clip=False))
    perseus_store.flush()
    ns = __import__("argparse").Namespace
    cli.cmd_visual_index(ns(source="met", views="all", no_clip=True))
    cli.cmd_run(ns(mode="catalogue", objects=str(tmp_path / "data" / "met_objects.json"), limit=None, only_with_images=False,
                   resume=False, visual=None, max_views=0))
    runs = cli._read_jsonl(tmp_path / "data" / "runs.jsonl")
    assert runs[0]["matches"][0]["id"] == "aa_1" and runs[0]["matches"][0]["visual"]["combined"] > 0.9
    assert "visual" in runs[0]["match_basis"] and runs[0]["matches"][0]["components"]["visual"] == 1.0
    cli.cmd_fragments(ns(include_perseus=True, top=5, min_confidence=0.0))
    frag = {r["name"]: r for r in cli._read_jsonl(tmp_path / "data" / "fragments.jsonl")}
    best = frag["1985.228.8a"]["candidates"][0]
    assert best["name"] == "1985.228.8b" and best["tier"] == "strong" and best["evidence"]["visual"] > 0.9
    monkeypatch.setattr(contentdm, "_get", lambda url, **kw: {"pager": {"total": 1}, "records": [{"collection": "/p1", "pointer": 1, "title": "T"}]})
    cli.cmd_sources(ns(limit=None, no_contentdm=False, min_score=0.6))
    src = cli._read_jsonl(tmp_path / "data" / "sources.jsonl")
    assert src[0]["references"][0]["beazley_number"] == "205092" and src[0]["contentdm"][0]["url"].endswith("/p1/id/1")
    assert "not a calibrated probability" in capsys.readouterr().out
