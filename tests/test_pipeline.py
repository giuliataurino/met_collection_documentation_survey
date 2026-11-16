"""Offline tests. The fixture records are invented for testing, not real Met objects."""
import json
from pathlib import Path

import pytest

from vasepipe import cli, link, met, prompt, validate, vocab

FIXTURE = Path(__file__).parent / "fixtures" / "met_sample.json"

PERSEUS = [
    {"id": "aa_1", "name": "Test 1", "collection": "Somewhere", "shape_raw": "Calyx krater", "shape": "calyx-krater",
     "ware": "Attic Red Figure", "technique": "red-figure", "fabric": "attic", "painter": "", "period": "Classical",
     "year": -450, "year_estimated": False, "summary": "Amazonomachy", "decoration": "Amazons fighting Greeks.",
     "shape_description": "", "image": "", "fragment": False, "url": "u1"},
    {"id": "aa_2", "name": "New York TEST.1", "collection": "New York, Metropolitan Museum of Art",
     "shape_raw": "Volute krater", "shape": "volute-krater", "ware": "Attic Red Figure", "technique": "red-figure",
     "fabric": "attic", "painter": "", "period": "Classical", "year": -450, "year_estimated": False,
     "summary": "Amazons", "decoration": "Battle of Greeks and Amazons.", "shape_description": "", "image": "",
     "fragment": False, "url": "u2"},
    {"id": "aa_3", "name": "Test 3", "collection": "Elsewhere", "shape_raw": "Lekythos", "shape": "lekythos",
     "ware": "Attic Black Figure", "technique": "black-figure", "fabric": "attic", "painter": "", "period": "Archaic",
     "year": -520, "year_estimated": False, "summary": "Herakles and the lion", "decoration": "", "shape_description": "",
     "image": "", "fragment": False, "url": "u3"},
]


@pytest.mark.parametrize("text,expected", [
    ("Terracotta hydria (water jar)", "hydria"),
    ("Terracotta stamnos (jar)", "stamnos"),
    ("Terracotta column-krater (bowl for mixing wine and water)", "column-krater"),
    ("Terracotta kylix: eye-cup (drinking cup)", "eye-cup"),
    ("Cup", "kylix"),
    ("Terracotta Nolan neck-amphora (jar)", "nolan-amphora"),
    ("Jar", "jar"),
    ("Marble head of a youth", None),
])
def test_match_shape(text, expected):
    assert vocab.match_shape(text) == expected


def test_vocabulary_is_consistent():
    assert all(not s["parent"] or s["parent"] in vocab.SHAPES for s in vocab.SHAPES.values())
    assert {s["fn"] for s in vocab.SHAPES.values()} <= set(vocab.FN_LABEL)
    assert {s["grounding"] for s in vocab.SHAPES.values()} == {"ancient", "conventional", "modern"}


def test_shape_relation():
    assert vocab.shape_relation("calyx-krater", "krater")[0] == "more specific"
    assert vocab.shape_relation("krater", "calyx-krater")[0] == "less specific"
    assert vocab.shape_relation("calyx-krater", "volute-krater")[0] == "sibling type"
    assert vocab.shape_relation("lekythos", "kylix")[0] == "different"


def test_prepare_keeps_vases_and_fragments():
    objs = met.prepare(met.load_file(FIXTURE))
    assert [o["accessionNumber"] for o in objs] == ["TEST.1", "TEST.2", "TEST.3", "TEST.5"]
    cats = {o["accessionNumber"]: met.catalogue_terms(o) for o in objs}
    assert cats["TEST.1"] == {"shape": "volute-krater", "technique": "red-figure", "fabric": "attic",
                              "period": "classical", "fragment": False}
    assert cats["TEST.2"]["shape"] == "kylix" and cats["TEST.2"]["fragment"]
    assert cats["TEST.3"]["fabric"] == "apulian"
    assert cats["TEST.5"]["shape"] is None and cats["TEST.5"]["fragment"]
    assert objs[0]["tags"] == ["Amazons"]


def test_normalise_reads_public_api_and_csv_names():
    api = met.normalise({"objectID": 1, "objectName": "Kylix", "objectBeginDate": -500, "objectEndDate": -480})
    sheet = met.normalise({"Object ID": "1", "Object Name": "Kylix", "Object Begin Date": "-500",
                           "Object End Date": "-480", "Tags": "Men|Horses"})
    assert api["objectName"] == sheet["objectName"] == "Kylix"
    assert met.year(api) == met.year(sheet) == -490
    assert sheet["tags"] == ["Men", "Horses"]


def _hasura_row(i, name="Kylix", classification="Vases", department="Greek and Roman Art"):
    return {"CRD_ObjectId": i, "ObjectNumber": f"T.{i}   ", "ObjectName": name, "Culture": "Greek, Attic", "Period": None,
            "Dated": "ca. 500 BCE", "DateBegin": -510, "DateEnd": -490, "Medium": "Terracotta; red-figure",
            "tags": [{"Term": "Men"}],
            "apiObject": {"objectID": i, "accessionNumber": f"T.{i}", "department": department, "webLabel": "A <i>cup</i>.",
                          "titles": {"primary": {"title": f"Terracotta {name.lower()}"}},
                          "classifications": {"primary": {"classification": classification}},
                          "images": {"primary": {"sourceImageUrl": "src", "thumbnailImageUrl": "thumb"},
                                     "all": [{"sourceImageUrl": "src", "thumbnailImageUrl": "thumb"},
                                             {"sourceImageUrl": "src2", "thumbnailImageUrl": "thumb2"}]}}}


@pytest.fixture
def fake_hasura(monkeypatch):
    rows = [_hasura_row(1), _hasura_row(2, "Head", "Stone Sculpture"), _hasura_row(3, "Hydria"),
            _hasura_row(4, "Fragment"), _hasura_row(5, "Lekythos")]
    calls = []

    class Resp:
        status_code = 200
        def __init__(self, page): self.page = page
        def json(self): return {"data": {"objects_crd": self.page}}

    def fake_post(url, headers, json, timeout, allow_redirects):
        calls.append((headers, json["variables"]))
        off, lim = json["variables"]["offset"], json["variables"]["limit"]
        return Resp(rows[off:off + lim])

    monkeypatch.setenv("HASURA_GRAPHQL_URL", "https://example.invalid/v1/graphql")
    monkeypatch.setenv("HASURA_ADMIN_SECRET", '"not-a-real-secret"')
    for name in ("HASURA_AUTH_HEADER", "HASURA_ROLE", "HASURA_KEY", "MET_CRD_DEPT_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(met.requests, "post", fake_post)
    return rows, calls


def test_hasura_fetch_pages_filters_and_flattens(fake_hasura):
    rows, calls = fake_hasura
    kept = met.fetch_hasura(page_size=2)
    assert [r["objectID"] for r in kept] == [1, 3, 4, 5]          # the marble head is dropped
    assert [c[1]["offset"] for c in calls] == [0, 2, 4]
    assert calls[0][1]["where"] == {"CRDDeptID": {"_eq": 13}}
    assert calls[0][0]["x-hasura-admin-secret"] == "not-a-real-secret"  # dotenv quotes are not sent
    obj = met.normalise(kept[0])
    assert obj["accessionNumber"] == "T.1" and obj["classification"] == "Vases" and obj["webLabel"] == "A cup ."
    assert met.images_of(obj) == ["thumb", "thumb2"] and obj["tags"] == ["Men"]


def test_hasura_wrong_department_stops(fake_hasura):
    rows, _ = fake_hasura
    for r in rows:
        r["apiObject"]["department"] = "European Paintings"
    with pytest.raises(met.HasuraError, match="European Paintings"):
        met.fetch_hasura(page_size=2)


def test_server_page_and_static_rules(fake_hasura, tmp_path, monkeypatch):
    from vasepipe import server
    page = server.met_vases_page(0, 2)
    assert page["scanned"] == 2 and page["next_offset"] == 2 and [o["objectID"] for o in page["objects"]] == ["1"]
    assert server.met_vases_page(4, 2)["next_offset"] is None
    (tmp_path / "dashboard").mkdir(); (tmp_path / "data").mkdir()
    (tmp_path / "dashboard" / "index.html").write_text("x"); (tmp_path / ".env").write_text("SECRET")
    (tmp_path / "data" / "runs.jsonl").write_text("{}"); (tmp_path / "data" / "perseus_metadata.csv").write_text("x")
    monkeypatch.setattr(server, "ROOT", tmp_path)
    assert server.resolve_static("/dashboard/") and server.resolve_static("/data/runs.jsonl")
    for blocked in ("/.env", "/dashboard/../.env", "/data/perseus_metadata.csv", "/vasepipe/met.py", "/data/../.env"):
        assert server.resolve_static(blocked) is None


def test_link_ranks_by_shape_and_text():
    index = link.Index(PERSEUS)
    top = index.match({"shape": "calyx-krater", "technique": "red-figure", "fabric": "attic", "year": -450,
                       "text": "Amazons fighting Greeks"})
    assert top[0]["id"] == "aa_1" and top[-1]["id"] == "aa_3"
    assert top[0]["score"] > top[1]["score"] > top[2]["score"]


def test_validate_flags_unknown_ids_and_generic_words():
    model = {"is_fragment": False, "shape_id": "amphora-ish", "technique_id": "red-figure", "fabric_id": "attic",
             "period_id": "classical", "description": "An Attic red-figure calyx-krater. The vase shows Amazons.",
             "out_of_vocabulary": ["rim plate"]}
    v = validate.validate(model, {"shape": "volute-krater", "technique": "red-figure", "fabric": "attic",
                                  "period": "classical", "fragment": False})
    assert v["out_of_vocabulary"] == 1
    assert v["description_scan"] == {"deepest": "calyx-krater", "terms": ["calyx-krater", "krater"], "generic": ["vase"]}
    assert v["declared_gaps"] == ["rim plate"]


def test_run_one_image_mode_with_stubbed_model(monkeypatch):
    from vasepipe import describe
    reply = {"baseline": "A decorated vase with figures.", "error": None,
             "model": {"is_fragment": False, "shape_id": "calyx-krater", "technique_id": "red-figure",
                       "fabric_id": "attic", "period_id": "classical", "subjects": ["Amazons"],
                       "decoration": [{"zone": "Side A", "text": "Amazons fighting Greeks"}],
                       "description": "Attic red-figure calyx-krater with an Amazonomachy."}}
    monkeypatch.setattr(describe, "describe", lambda images: reply)
    obj = met.prepare(met.load_file(FIXTURE))[0]
    obj["primaryImageSmall"] = "https://example.invalid/image.jpg"
    rec = cli.run_one(obj, link.Index(PERSEUS), {"test.1": {"id": "aa_2", "name": "New York TEST.1", "url": "u2"}}, "image")
    assert rec["baseline_scan"]["deepest"] is None and rec["baseline_scan"]["generic"] == ["vase"]
    assert rec["validation"]["rows"][0]["relation"] == "sibling type"
    assert rec["matches"][0]["id"] == "aa_1"
    assert rec["perseus_same_accession"]["id"] == "aa_2"
    assert "Run" in cli.summarise([rec])[0]


def test_prompt_lists_every_shape():
    text = prompt.constrained()
    assert all(f"{sid} | " in text for sid in vocab.SHAPES)


def test_perseus_image_ids_are_split():
    from vasepipe import perseus
    assert perseus.image_ids({"image": "1990.05.0407, 1990.05.0408"}) == ["1990.05.0407", "1990.05.0408"]
    assert perseus.image_ids({"image": ""}) == []


def test_describe_endpoint_only_fetches_met_and_perseus_images(monkeypatch):
    from vasepipe import describe, server
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.delenv("MET_IMAGE_HOSTS", raising=False)
    seen = {}
    monkeypatch.setattr(describe, "describe", lambda sources, prompt=None: seen.update(sources=sources) or
                        {"baseline": "b", "model": {}, "error": None, "model_name": "stub", "images_sent": len(sources)})
    out = server.describe_request({"images": ["https://images.metmuseum.org/a.jpg"], "image_data": ["data:image/png;base64,AAAA"]})
    assert out["images_sent"] == 2 and seen["sources"][0].startswith("https://") and isinstance(seen["sources"][1], bytes)
    for bad in ("http://169.254.169.254/latest", "file:///etc/passwd", "https://evilmetmuseum.org/a.jpg", "/etc/passwd"):
        with pytest.raises(ValueError):
            server.describe_request({"images": [bad]})
    with pytest.raises(ValueError):
        server.describe_request({})


def test_public_api_page_keeps_vases_and_caches(monkeypatch, tmp_path):
    from vasepipe import server
    records = {1: {"objectID": 1, "objectName": "Kylix", "classification": "Vases", "department": "Greek and Roman Art",
                   "primaryImageSmall": "https://images.metmuseum.org/a.jpg", "additionalImages": ["https://images.metmuseum.org/b.jpg"]},
               2: {"objectID": 2, "objectName": "Head", "classification": "Stone Sculpture", "department": "Greek and Roman Art"},
               3: {"objectID": 3, "objectName": "Hydria fragment", "classification": "Vases", "department": "Greek and Roman Art"}}
    calls = []

    class Resp:
        def __init__(self, status, body): self.status_code, self.body = status, body
        def json(self): return self.body

    def fake_get(path, params=None):
        calls.append((path, params))
        if path in ("objects", "search"):
            return Resp(200, {"objectIDs": [3, 1, 2, 99]})
        oid = int(path.split("/")[1])
        return Resp(200, records[oid]) if oid in records else Resp(404, {})

    monkeypatch.setattr(met, "_public_get", fake_get)
    monkeypatch.setattr(met.time, "sleep", lambda s: None)
    monkeypatch.chdir(tmp_path)
    server._public_ids.clear()
    page = server.met_public_page(0, 3, "")
    assert page["total"] == 4 and page["scanned"] == 3 and page["next_offset"] == 3
    assert [o["objectID"] for o in page["objects"]] == ["1", "3"]
    assert met.images_of(page["objects"][0]) == ["https://images.metmuseum.org/a.jpg", "https://images.metmuseum.org/b.jpg"]
    assert server.met_public_page(3, 3, "")["next_offset"] is None            # id 99 has no record
    before = len(calls)
    server.met_public_page(0, 3, "")                                           # ids and objects are reused
    assert len(calls) == before
    server.met_public_page(0, 1, "kylix")
    assert calls[-1] == ("search", {"departmentId": 13, "q": "kylix"})      # object 1 came from the cache
