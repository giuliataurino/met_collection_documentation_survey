"""Command line: python -m vasepipe <command>"""
import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import link, met, perseus, prompt, validate, vocab

DATA = Path("data")
MET_FEATURES, PERSEUS_FEATURES = DATA / "features_met.npz", DATA / "features_perseus.npz"


def _load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv()
        load_dotenv(".env.local")
    except ImportError:
        pass


def cmd_fetch_perseus(args):
    path = perseus.download(force=args.force)
    records = perseus.build(path)
    mapped = sum(1 for r in records if r["shape"])
    named = sum(1 for r in records if r["shape_raw"])
    print(f"Perseus: {len(records)} vases; {mapped} of {named} named shapes resolve to the vocabulary; "
          f"{sum(1 for r in records if r['decoration'])} have a decoration description. -> data/perseus.json")


def cmd_introspect(args):
    for line in met.introspect(args.table):
        print(line)


def cmd_fetch_met(args):
    if args.source == "hasura":
        rows = met.fetch_hasura(args.query, page_size=args.page_size, limit=args.limit)
    elif args.source == "public-api":
        rows = met.fetch_public_api(limit=args.limit, query=args.search)
    else:
        if not args.file:
            raise SystemExit("--source file needs --file PATH (JSON or CSV).")
        rows = met.load_file(args.file)
    objs = met.prepare(rows, keep_only_vases=not args.keep_all)
    DATA.mkdir(exist_ok=True)
    (DATA / "met_objects.json").write_text(json.dumps(objs, ensure_ascii=False, indent=1))
    cats = [met.catalogue_terms(o) for o in objs]
    print(f"Met: read {len(rows)} rows, kept {len(objs)} vases and fragments "
          f"({sum(c['fragment'] for c in cats)} fragments; {sum(1 for c in cats if c['shape'])} resolve to a "
          f"vocabulary shape; {sum(1 for o in objs if met.images_of(o))} have an image; "
          f"{sum(len(met.images_of(o)) for o in objs)} images in all). "
          "-> data/met_objects.json")


def cmd_check_hasura(args):
    """One small request, to prove the endpoint, the secret, the query and the department id."""
    rows, _ = met.fetch_hasura_page(0, args.rows, args.query)
    names = met.check_department(rows)
    vases = [o for o in (met.normalise(r) for r in rows) if met.is_vase(o)]
    print(f"Hasura answered. Department id {met.dept_id()} -> {sorted(names) or 'no department name returned'}.")
    print(f"First {len(rows)} objects: {len(vases)} are vases or fragments.")
    for o in vases[:5]:
        print(f"  {o['accessionNumber']}  {o['objectName']}  |  {o['title'][:60]}  |  {len(met.images_of(o))} images")


def cmd_serve(args):
    from . import server
    server.serve(args.port)


def cmd_prompt(args):
    print(prompt.constrained())


def run_one(obj, index, by_accession, mode, weights=None, visual_index=None, top=8, max_views=0):
    cat = met.catalogue_terms(obj)
    images = met.images_of(obj)
    if max_views:
        images = images[:max_views]
    image = images[0] if images else ""
    rec = {"objectID": obj["objectID"], "accessionNumber": obj["accessionNumber"], "title": obj["title"],
           "objectURL": obj["objectURL"], "objectName": obj["objectName"], "culture": obj["culture"],
           "objectDate": obj["objectDate"], "image": image, "images": images,
           "webLabel": obj.get("webLabel", ""), "artist": obj.get("artist", ""), "mode": mode, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "catalogue": cat, "baseline": None, "model": None, "validation": None, "error": None}
    acc = re.sub(r"[^0-9a-z.\-]", "", obj["accessionNumber"].lower())
    rec["perseus_same_accession"] = by_accession.get(acc)
    query = {"shape": cat["shape"], "technique": cat["technique"], "fabric": cat["fabric"], "year": met.year(obj),
             "text": " ".join([obj["title"], obj["objectName"], " ".join(obj["tags"]), obj.get("webLabel", "")])}
    if mode == "image":
        if not image:
            rec["error"] = "no image link on this record; linked from the catalogue instead"
        else:
            from . import describe
            try:
                out = describe.describe(images)
            except Exception as exc:  # network, auth or image problems: record and carry on
                out = {"baseline": None, "model": None, "error": f"{type(exc).__name__}: {exc}"}
            rec["baseline"], rec["model"], rec["error"] = out["baseline"], out["model"], out["error"]
            if out["baseline"]:
                rec["baseline_scan"] = validate.scan_text(out["baseline"])
            if out["model"]:
                m = out["model"]
                rec["validation"] = validate.validate(m, cat)
                period = vocab.PERIODS.get(m.get("period_id"))
                query = {"shape": m.get("shape_id") if m.get("shape_id") in vocab.SHAPES else None,
                         "technique": m.get("technique_id") if m.get("technique_id") in vocab.TECHNIQUES else None,
                         "fabric": m.get("fabric_id") if m.get("fabric_id") in vocab.FABRICS else None,
                         "year": round((period["start"] + period["end"]) / 2) if period else None,
                         "text": " ".join([str(m.get("description") or ""),
                                           " ".join(str(d.get("text", "")) for d in (m.get("decoration") or [])
                                                    if isinstance(d, dict)),
                                           " ".join(map(str, m.get("subjects") or []))])}
    visual_scores = None
    if visual_index is not None:
        from . import visual
        met_store, perseus_store = visual_index
        visual_scores = visual.object_scores(met_store, obj["objectID"], perseus_store) or None
    rec["query"] = query
    # Which signals the ranking had. A text-only basis (e.g. an unnamed fragment) is a weak match
    # however high the score, because the text component is scaled to its best hit.
    rec["match_basis"] = [k for k in ("shape", "technique", "fabric", "year") if query.get(k) is not None] \
        + (["text"] if query.get("text", "").strip() else []) + (["visual"] if visual_scores and weights and weights.get("visual") else [])
    rec["matches"] = index.match(query, top=top, weights=weights, visual_scores=visual_scores)
    return rec


def summarise(runs):
    image_runs = [r for r in runs if r["model"]]
    comparable = [r for r in image_runs if r["catalogue"]["shape"] and r["model"].get("shape_id") in vocab.SHAPES]
    rel = [next(x["relation"] for x in r["validation"]["rows"] if x["field"] == "shape") for r in comparable]
    agree = sum(x in ("exact", "more specific") for x in rel)
    lines = [f"Runs: {len(runs)} ({len(image_runs)} with a model description).",
             f"Catalogue object name resolves to a vocabulary shape: "
             f"{sum(1 for r in runs if r['catalogue']['shape'])} of {len(runs)}."]
    if comparable:
        lines.append(f"Constrained shape agrees with the catalogue (exact or more specific): {agree} of {len(comparable)}.")
        lines.append("Unconstrained description used no vocabulary shape term: "
                     f"{sum(1 for r in image_runs if not (r.get('baseline_scan') or {}).get('deepest'))} of {len(image_runs)}.")
        lines.append(f"Identifiers outside the vocabulary: {sum(r['validation']['out_of_vocabulary'] for r in image_runs)}.")
    scored = [r["matches"][0]["score"] for r in runs if r["matches"]]
    if scored:
        lines.append(f"Mean top Perseus match score: {sum(scored) / len(scored):.2f}.")
    lines.append(f"Same accession found in Perseus: {sum(1 for r in runs if r['perseus_same_accession'])}.")
    return lines


def write_vocab_json():
    """Labels for the results dashboard, written each run so it never drifts from vocab.py."""
    DATA.mkdir(exist_ok=True)
    (DATA / "vocab.json").write_text(json.dumps({
        "fn": vocab.FN,
        "shapes": [{k: s[k] for k in ("id", "label", "greek", "parent", "fn", "grounding")} for s in vocab.SHAPES.values()],
        "techniques": {t["id"]: t["label"] for t in vocab.TECHNIQUES.values()},
        "fabrics": {f["id"]: f["label"] for f in vocab.FABRICS.values()},
        "periods": {x["id"]: x["label"] for x in vocab.PERIODS.values()}}, ensure_ascii=False))


def cmd_run(args):
    objs_path = Path(args.objects)
    if not objs_path.exists():
        raise SystemExit(f"{objs_path} not found. Run `python -m vasepipe fetch-met` first.")
    objs = json.loads(objs_path.read_text())
    if args.only_with_images:
        objs = [o for o in objs if met.images_of(o)]
    if args.limit:
        objs = objs[:args.limit]
    records = perseus.load()
    index = link.Index(records)
    by_accession = {perseus.accession_of(r): {"id": r["id"], "name": r["name"], "url": r["url"]}
                    for r in records if perseus.accession_of(r)}
    weights, visual_index = None, None
    if args.visual is None:
        args.visual = 25 if MET_FEATURES.exists() and PERSEUS_FEATURES.exists() else 0
    if args.visual:
        from . import visual
        visual_index = (visual.Store(MET_FEATURES), visual.Store(PERSEUS_FEATURES))
        if not len(visual_index[0]) or not len(visual_index[1]):
            raise SystemExit("No image features yet. Run `python -m vasepipe visual-index` first.")
        weights = {"visual": args.visual}
    out_path = DATA / "runs.jsonl"
    DATA.mkdir(exist_ok=True)
    write_vocab_json()
    done = set()
    if args.resume and out_path.exists():
        done = {(json.loads(l)["objectID"], json.loads(l)["mode"]) for l in out_path.read_text().splitlines() if l.strip()}
    runs = []
    with open(out_path, "a" if args.resume else "w", encoding="utf-8") as fh:
        for n, obj in enumerate(objs, 1):
            if (obj["objectID"], args.mode) in done:
                continue
            rec = run_one(obj, index, by_accession, args.mode, weights, visual_index, max_views=args.max_views)
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            runs.append(rec)
            top = rec["matches"][0] if rec["matches"] else None
            print(f"[{n}/{len(objs)}] {obj['accessionNumber']} {obj['title'][:50]} -> "
                  f"{top['name'] + ' ' + format(top['score'], '.2f') if top else 'no match'}"
                  + (f"  ! {rec['error']}" if rec["error"] else ""))
    all_runs = [json.loads(l) for l in out_path.read_text().splitlines() if l.strip()]
    with open(DATA / "runs.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["objectID", "accessionNumber", "title", "mode", "catalogue_shape", "baseline_deepest_term",
                    "model_shape", "shape_relation", "out_of_vocabulary", "top_perseus", "top_score",
                    "match_basis", "perseus_same_accession", "error"])
        for r in all_runs:
            v = r["validation"] or {}
            rel = next((x["relation"] for x in v.get("rows", []) if x["field"] == "shape"), "")
            top = r["matches"][0] if r["matches"] else {}
            w.writerow([r["objectID"], r["accessionNumber"], r["title"], r["mode"], r["catalogue"]["shape"] or "",
                        (r.get("baseline_scan") or {}).get("deepest") or "", (r["model"] or {}).get("shape_id") or "",
                        rel, v.get("out_of_vocabulary", ""), top.get("name", ""), top.get("score", ""),
                        " ".join(r.get("match_basis", [])), (r["perseus_same_accession"] or {}).get("name", ""), r["error"] or ""])
    print("\n" + "\n".join(summarise(all_runs)))
    print("-> data/runs.jsonl, data/runs.csv\nView them: python -m vasepipe serve, then http://localhost:8000/dashboard/results.html")


def perseus_image_items(records, views="all", width=450):
    for r in records:
        ids = perseus.image_ids(r)
        for image_id in (ids if views == "all" else ids[:1]):
            yield r["id"], perseus.image_url(image_id, width)


def cmd_visual_index(args):
    """Stage 3: compute image features for Perseus vases and the fetched Met objects."""
    from . import visual
    use_clip = not args.no_clip
    if args.source in ("perseus", "both"):
        store = visual.Store(PERSEUS_FEATURES)
        done, failed = visual.build(store, perseus_image_items(perseus.load(), args.views), use_clip,
                                    label="Perseus images")
        print(f"Perseus: {len(store)} images indexed ({done} new, {failed} failed) -> {PERSEUS_FEATURES}")
    if args.source in ("met", "both"):
        objs = json.loads((DATA / "met_objects.json").read_text()) if (DATA / "met_objects.json").exists() else []
        if not objs:
            print("Met: no data/met_objects.json yet; run fetch-met first.")
        else:
            store = visual.Store(MET_FEATURES)
            items = [(o["objectID"], u) for o in objs for u in (met.images_of(o) if args.views == "all" else met.images_of(o)[:1])]
            done, failed = visual.build(store, items, use_clip, label="Met images")
            print(f"Met: {len(store)} images indexed ({done} new, {failed} failed) -> {MET_FEATURES}")
    print("Measures available: " + ", ".join(k for k in visual.WEIGHTS if k in visual.Store(PERSEUS_FEATURES).arrays))


def _read_jsonl(path):
    path = Path(path)
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def cmd_fragments(args):
    """Stage 4: complementary-fragment candidates with confidence scores."""
    from . import fragments
    objs_path = DATA / "met_objects.json"
    if not objs_path.exists():
        raise SystemExit("data/met_objects.json not found. Run `python -m vasepipe fetch-met` first.")
    models = {r["objectID"]: r["model"] for r in _read_jsonl(DATA / "runs.jsonl") if r.get("model")}
    pool = [fragments.from_met(o, models.get(o["objectID"])) for o in json.loads(objs_path.read_text())]
    pool = [f for f in pool if f["is_fragment"]]
    n_met = len(pool)
    if args.include_perseus:
        pool += [fragments.from_perseus(r) for r in perseus.load() if r["fragment"]]
    visual_fn = None
    if MET_FEATURES.exists():
        from . import visual
        store = visual.Store(MET_FEATURES)
        if len(store):
            def visual_fn(key):
                if not key.startswith("met:"):
                    return {}
                scores = visual.object_scores(store, key[4:], store)
                scores.pop(key[4:], None)
                return {"met:" + k: v for k, v in scores.items()}
    results = fragments.propose(pool, visual_fn, top=args.top, min_confidence=args.min_confidence)
    _write_jsonl(DATA / "fragments.jsonl", results)
    tiers = [c["tier"] for r in results for c in r["candidates"]]
    print(f"Fragments: {n_met} from the Met" + (f", {len(pool) - n_met} from Perseus" if args.include_perseus else "")
          + f". Evidence used: metadata and text{', image similarity' if visual_fn else ' (no image features: run visual-index to add them)'}.")
    print(f"Candidates: {tiers.count('strong')} strong, {tiers.count('possible')} possible, {tiers.count('weak')} weak "
          f"across {sum(1 for r in results if r['candidates'])} fragments. -> data/fragments.jsonl")
    print("Confidence is a ranking heuristic, not a calibrated probability.")


def cmd_sources(args):
    """Stages 5 and 6: further sources through the vocabulary, then CONTENTdm."""
    from . import contentdm, sources
    runs = _read_jsonl(DATA / "runs.jsonl")
    if not runs:
        raise SystemExit("data/runs.jsonl not found. Run `python -m vasepipe run` first.")
    if args.limit:
        runs = runs[:args.limit]
    records = perseus.load()
    by_id, by_name = {r["id"]: r for r in records}, {r["name"]: r for r in records}
    use_cdm, out = not args.no_contentdm, []
    for n, run in enumerate(runs, 1):
        item = sources.enrich(run, by_id, by_name, use_cdm, args.min_score)
        log = item["contentdm_log"] or []
        if use_cdm and log and log[-1].get("error") and item["contentdm"] == []:
            print(f"  CONTENTdm stopped answering ({log[-1]['error']}); continuing without it.")
            use_cdm = False
        out.append(item)
        if n % 50 == 0:
            print(f"  sources: {n} of {len(runs)}")
    _write_jsonl(DATA / "sources.jsonl", out)
    print(f"Sources: {len(out)} objects; {sum(1 for i in out if i['references'])} with Perseus references "
          f"({sum(len(r['citations']) for i in out for r in i['references'])} citations, "
          f"{sum(1 for i in out for r in i['references'] if r['beazley_number'])} Beazley numbers); "
          f"{sum(1 for i in out if i['contentdm'])} with CONTENTdm material "
          f"({sum(len(i['contentdm'] or []) for i in out)} records). -> data/sources.jsonl")


def cmd_check_contentdm(args):
    from . import contentdm
    cols = contentdm.collections()
    print(f"CONTENTdm at {contentdm.base_url()} answered with {len(cols)} collections:")
    for c in cols[:40]:
        print(f"  {c['alias']}  {c['name']}")
    records, total = contentdm.search(args.term, "all", 5)
    print(f"Search for '{args.term}': {total} records. First {len(records)}:")
    for r in records:
        print(f"  [{r['collection']}] {r['title'][:80]}  {r['url']}")


def cmd_all(args):
    """Every stage in order."""
    ns = argparse.Namespace
    cmd_fetch_perseus(ns(force=False))
    cmd_fetch_met(ns(source=args.source, query="queries/vases.graphql", file=None, limit=args.limit, search=args.search,
                     page_size=200, keep_all=False))
    if not args.no_visual:
        cmd_visual_index(ns(source="both", views=args.views, no_clip=False))
    cmd_run(ns(mode=args.mode, objects="data/met_objects.json", limit=None, only_with_images=False, resume=False,
               visual=None, max_views=0))
    cmd_fragments(ns(include_perseus=True, top=5, min_confidence=0.3))
    cmd_sources(ns(limit=None, no_contentdm=args.no_contentdm, min_score=0.6))


def main(argv=None):
    _load_env()
    p = argparse.ArgumentParser(prog="vasepipe", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("fetch-perseus", help="download Perseus metadata and build the vase corpus")
    s.add_argument("--force", action="store_true", help="download again even if cached")
    s.set_defaults(fn=cmd_fetch_perseus)

    s = sub.add_parser("introspect", help="list Hasura query fields, or one type's fields")
    s.add_argument("--table", help="a type name, to list its fields")
    s.set_defaults(fn=cmd_introspect)

    s = sub.add_parser("fetch-met", help="fetch Greek and Roman vases and fragments")
    s.add_argument("--source", choices=["hasura", "public-api", "file"], default="hasura")
    s.add_argument("--query", default="queries/vases.graphql")
    s.add_argument("--file", help="JSON or CSV to load when --source file")
    s.add_argument("--limit", type=int)
    s.add_argument("--search", metavar="TERM", help="public-api only: check just the objects matching this search")
    s.add_argument("--page-size", type=int, default=200, help="rows per Hasura request (at most 500)")
    s.add_argument("--keep-all", action="store_true", help="skip the vase filter (file source only)")
    s.set_defaults(fn=cmd_fetch_met)

    s = sub.add_parser("check-hasura", help="one small Hasura request to verify the setup")
    s.add_argument("--rows", type=int, default=25)
    s.add_argument("--query", default="queries/vases.graphql")
    s.set_defaults(fn=cmd_check_hasura)

    s = sub.add_parser("serve", help="serve the dashboards on localhost, with a live Hasura lookup")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("prompt", help="print the constrained prompt")
    s.set_defaults(fn=cmd_prompt)

    s = sub.add_parser("run", help="run the pipeline over data/met_objects.json")
    s.add_argument("--mode", choices=["catalogue", "image"], default="catalogue",
                   help="catalogue: validate and link the existing record, no model calls. "
                        "image: two Claude requests per object, then validate and link.")
    s.add_argument("--objects", default="data/met_objects.json")
    s.add_argument("--limit", type=int)
    s.add_argument("--only-with-images", action="store_true")
    s.add_argument("--max-views", type=int, default=0, metavar="N",
                   help="send at most N images of each object to the model (default: all of them)")
    s.add_argument("--resume", action="store_true", help="append to runs.jsonl and skip objects already run")
    s.add_argument("--visual", type=float, default=None, metavar="WEIGHT",
                   help="weight of image similarity in the Perseus ranking (default: 25 if visual-index has been run, else 0)")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("visual-index", help="stage 3: compute image features for Perseus and Met images")
    s.add_argument("--source", choices=["both", "perseus", "met"], default="both")
    s.add_argument("--views", choices=["all", "lead"], default="all", help="every view of each object, or only the first")
    s.add_argument("--no-clip", action="store_true", help="skip CLIP even if installed (edge, colour and hash only)")
    s.set_defaults(fn=cmd_visual_index)

    s = sub.add_parser("fragments", help="stage 4: complementary-fragment candidates with confidence scores")
    s.add_argument("--include-perseus", action="store_true", help="also consider Perseus fragments as partners")
    s.add_argument("--top", type=int, default=5, help="candidates kept per fragment")
    s.add_argument("--min-confidence", type=float, default=0.3)
    s.set_defaults(fn=cmd_fragments)

    s = sub.add_parser("sources", help="stages 5-6: sources via the vocabulary, then CONTENTdm")
    s.add_argument("--no-contentdm", action="store_true", help="stop after the Perseus references and term links")
    s.add_argument("--min-score", type=float, default=0.6, help="only trust Perseus matches at or above this score")
    s.add_argument("--limit", type=int)
    s.set_defaults(fn=cmd_sources)

    s = sub.add_parser("check-contentdm", help="list the CONTENTdm collections and run one search")
    s.add_argument("--term", default="Greek vases")
    s.set_defaults(fn=cmd_check_contentdm)

    s = sub.add_parser("all", help="run every stage in order")
    s.add_argument("--source", choices=["hasura", "public-api"], default="hasura")
    s.add_argument("--mode", choices=["catalogue", "image"], default="catalogue")
    s.add_argument("--limit", type=int, help="cap the number of Met vases fetched")
    s.add_argument("--search", help="public-api only: restrict to objects matching this term")
    s.add_argument("--views", choices=["all", "lead"], default="all")
    s.add_argument("--no-visual", action="store_true")
    s.add_argument("--no-contentdm", action="store_true")
    s.set_defaults(fn=cmd_all)

    args = p.parse_args(argv)
    try:
        args.fn(args)
    except met.HasuraError as exc:
        raise SystemExit(f"Hasura: {exc}")
    except met.MetApiError as exc:
        raise SystemExit(str(exc))
    except Exception as exc:
        if type(exc).__name__ == "ContentdmError":
            raise SystemExit(f"CONTENTdm: {exc}")
        raise


if __name__ == "__main__":
    main()
