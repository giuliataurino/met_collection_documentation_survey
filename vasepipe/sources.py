"""Stage 5: from the vocabulary terms and the matched Perseus records, work out
where else to look, and (stage 6) hand the resulting search terms to CONTENTdm.

For one pipeline run this produces:
  terms       vocabulary and metadata terms worth searching on, each with its kind and origin
  references  what the matched Perseus records cite: Beazley numbers, ARV/ABV-style citations,
              bibliography, comparanda (resolved to Perseus records where the name matches)
  links       lookups keyed by a vocabulary term: Perseus lexicon, Getty AAT
  queries     the CONTENTdm searches those terms turn into
"""
import re
from urllib.parse import quote

from . import vocab

LEXICON = "https://www.perseus.tufts.edu/hopper/morph?l={term}&la=greek"
AAT_FIND = "https://www.getty.edu/vow/AATServlet?english=N&find={term}&logic=AND&page=1&note="


def _shape_of(run):
    model = (run.get("model") or {}).get("shape_id")
    return model if model in vocab.SHAPES else run["catalogue"].get("shape")


def _painter_name(text):
    return re.sub(r"^(Attributed to|In the manner of|Near|Manner of|Circle of|Signed by|Related to|Compare(?: to)?|Recalls)\s+(the\s+)?", "",
                  (text or "").strip(), flags=re.I).strip()


def terms_for(run, matches, min_score=0.6):
    """Search terms with their kind and where each came from."""
    out, seen = [], set()

    def add(term, kind, origin):
        term = (term or "").strip()
        if term and term.lower() not in seen:
            seen.add(term.lower())
            out.append({"term": term, "kind": kind, "origin": origin})

    add(run.get("accessionNumber"), "accession", "Met record")
    sid = _shape_of(run)
    if sid:
        s = vocab.SHAPES[sid]
        add(s["label"], "shape", "vocabulary")
        add(s["aat"], "shape", "vocabulary (AAT-style label)")
        root = vocab.SHAPES[(vocab.ancestors(sid) or [sid])[-1]]
        if root["id"] != sid:
            add(root["label"], "shape", "vocabulary (parent term)")
        if s["greek"] or root["greek"]:
            add(s["greek"] or root["greek"], "greek", "vocabulary")
    model = run.get("model") or {}
    tech = model.get("technique_id") if model.get("technique_id") in vocab.TECHNIQUES else run["catalogue"].get("technique")
    if tech:
        add(vocab.TECHNIQUES[tech]["label"], "technique", "vocabulary")
    for subject in (model.get("subjects") or [])[:6]:
        add(str(subject), "subject", "model description")
    if run.get("artist"):
        add(_painter_name(run["artist"]), "painter", "Met record")
    # Painters of the two closest Perseus vases only: a lead about relatives, not an attribution of this object.
    for m in [m for m in matches if m["score"] >= min_score][:2]:
        if m.get("painter"):
            add(_painter_name(m["painter"]), "painter", f"Perseus match {m['name']}")
    return out


def references_for(matches, perseus_by_id, perseus_by_name, min_score=0.6, top=3):
    """What the best-matching Perseus records cite."""
    out = []
    for m in [m for m in matches if m["score"] >= min_score][:top]:
        rec = perseus_by_id.get(m["id"])
        if not rec:
            continue
        comparanda = [{"name": name, "url": perseus_by_name[name]["url"] if name in perseus_by_name else None}
                      for name in rec.get("comparanda", [])]
        if not (rec.get("beazley_number") or rec.get("citations") or rec.get("sources_used") or comparanda):
            continue
        out.append({"perseus": {"id": rec["id"], "name": rec["name"], "url": rec["url"], "score": m["score"]},
                    "beazley_number": rec.get("beazley_number") or None,
                    "citations": rec.get("citations", []), "sources_used": rec.get("sources_used", []),
                    "comparanda": comparanda, "painter": rec.get("painter") or None, "potter": rec.get("potter") or None,
                    "findspot": rec.get("findspot") or None})
    return out


def links_for(terms):
    out = []
    for t in terms:
        if t["kind"] == "greek":
            out.append({"label": f"{t['term']} in the Perseus lexicon", "url": LEXICON.format(term=quote(t["term"].split(" ")[0]))})
        if t["kind"] == "shape" and "AAT" in t["origin"]:
            out.append({"label": f"“{t['term']}” in the Getty AAT", "url": AAT_FIND.format(term=quote(t["term"]))})
    return out


def contentdm_queries(terms):
    """Turn terms into weighted CONTENTdm searches, most specific first.

    The accession number as an exact phrase is the strongest lead to material about this very
    object. Painter and shape-with-technique find material about its close relatives. Shape alone
    is broad and weighted low. Greek-script terms are not sent: the catalogue is in English.
    """
    by_kind = {}
    for t in terms:
        by_kind.setdefault(t["kind"], []).append(t["term"])
    shape = (by_kind.get("shape") or [None])[0]
    technique = (by_kind.get("technique") or [None])[0]
    queries = []
    for acc in by_kind.get("accession", []):
        queries.append({"term": acc, "mode": "exact", "weight": 5.0, "kind": "accession"})
    for painter in by_kind.get("painter", [])[:2]:
        queries.append({"term": painter, "mode": "exact", "weight": 3.0, "kind": "painter"})
    if shape and technique:
        queries.append({"term": f"{technique} {shape}", "mode": "all", "weight": 2.0, "kind": "technique + shape"})
    for subject in by_kind.get("subject", [])[:2]:
        if shape:
            queries.append({"term": f"{subject} {shape}", "mode": "all", "weight": 1.5, "kind": "subject + shape"})
    if shape:
        queries.append({"term": f"Greek {shape}", "mode": "all", "weight": 1.0, "kind": "shape"})
    return queries


def enrich(run, perseus_by_id, perseus_by_name, use_contentdm=True, min_score=0.6):
    matches = run.get("matches") or []
    terms = terms_for(run, matches, min_score)
    out = {"objectID": run["objectID"], "accessionNumber": run.get("accessionNumber"), "title": run.get("title"),
           "terms": terms, "references": references_for(matches, perseus_by_id, perseus_by_name, min_score),
           "links": links_for(terms), "queries": contentdm_queries(terms), "contentdm": None, "contentdm_log": None}
    if use_contentdm and out["queries"]:
        from . import contentdm
        out["contentdm"], out["contentdm_log"] = contentdm.find(out["queries"])
    return out
