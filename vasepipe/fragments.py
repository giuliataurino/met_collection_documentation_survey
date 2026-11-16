"""Stage 4: propose complementary fragments, i.e. fragments that may come from the same vase.

Every pair of fragments is scored on independent kinds of evidence, each in
0..1, and only where both sides have the information:

  accession   same accession number with different suffixes, or the same lot
  shape       same vocabulary shape, or one a variant of the other
  technique   same technique
  fabric      same fabric
  date        overlapping date ranges
  attribution same painter or workshop named on both
  parts       the named parts can coexist on one vase (a rim and a foot can; two feet cannot)
  text        shared vocabulary in titles, tags, labels and model descriptions
  visual      best-view image similarity (see visual.py)

Pairs are dropped outright when the records contradict each other: different
techniques, shapes from different families, or date ranges more than 75 years
apart.

`confidence` rests on the evidence specific to a pair (accession, attribution,
parts, text, visual), pulled toward a low prior, then scaled by how well the
general cataloguing (shape, technique, fabric, date) agrees. Agreement on the
general cataloguing alone never produces a confident candidate. It is a
ranking heuristic, NOT a calibrated probability: nothing here has been checked
against known joins.
Image similarity compares surface, colour and drawing; it does not test
whether break edges fit. Treat every candidate as a lead for a specialist.
"""
import re

from . import link, met, vocab

WEIGHTS = {"accession": 3.0, "attribution": 2.0, "visual": 2.0, "shape": 1.5, "technique": 1.0,
           "fabric": 1.0, "date": 1.0, "parts": 1.0, "text": 1.0}
GENERIC = ("shape", "technique", "fabric", "date")
PRIOR, PRIOR_WEIGHT = 0.2, 2.0
DATE_GAP_LIMIT = 75
PARTS = {"rim": r"\brim|\blip\b", "foot": r"\bfoot|\bbase\b|\bstem\b", "handle": r"\bhandle", "neck": r"\bneck",
         "shoulder": r"\bshoulder", "body": r"\bbody|\bwall\b", "lid": r"\blid\b", "tondo": r"\btondo|\binterior\b",
         "mouth": r"\bmouth"}
SINGULAR = {"foot", "neck", "lid", "tondo", "mouth"}  # a vase has one of each


def from_met(obj, model=None):
    """A fragment record from a Met object, optionally sharpened by a model description."""
    cat = met.catalogue_terms(obj)
    m = model or {}
    text = " ".join([obj["title"], obj["objectName"], " ".join(obj["tags"]), obj.get("webLabel", ""),
                     str(m.get("description") or ""),
                     " ".join(str(d.get("text", "")) for d in (m.get("decoration") or []) if isinstance(d, dict))])
    return {
        "key": "met:" + obj["objectID"], "source": "met", "id": obj["objectID"], "name": obj["accessionNumber"] or obj["objectID"],
        "title": obj["title"] or obj["objectName"], "url": obj["objectURL"], "accession": obj["accessionNumber"],
        "shape": cat["shape"] or (m.get("shape_id") if m.get("shape_id") in vocab.SHAPES else None),
        "technique": cat["technique"] or (m.get("technique_id") if m.get("technique_id") in vocab.TECHNIQUES else None),
        "fabric": cat["fabric"] or (m.get("fabric_id") if m.get("fabric_id") in vocab.FABRICS else None),
        "begin": obj.get("objectBeginDate"), "end": obj.get("objectEndDate"),
        "attribution": _painter(obj.get("artist", "") + " " + obj["title"]),
        "parts": parts_of(obj["title"] + " " + obj["objectName"]), "text": text,
        "image": (met.images_of(obj) or [""])[0], "is_fragment": cat["fragment"] or bool(m.get("is_fragment")),
    }


def from_perseus(rec):
    year = rec["year"]
    return {
        "key": "perseus:" + rec["id"], "source": "perseus", "id": rec["id"], "name": rec["name"], "title": rec["shape_raw"],
        "url": rec["url"], "accession": "", "shape": rec["shape"], "technique": rec["technique"], "fabric": rec["fabric"],
        "begin": year - 15 if year is not None else None, "end": year + 15 if year is not None else None,
        "attribution": _painter(rec["painter"]), "parts": parts_of(rec["shape_raw"] + " " + rec.get("condition", "")),
        "text": " ".join([rec["summary"], rec["decoration"]]), "image": "", "is_fragment": rec["fragment"],
    }


def _painter(text):
    """'Attributed to the Berlin Painter' -> 'berlin painter'. Empty when no painter, group or class is named."""
    m = re.search(r"((?:[A-Z][\w'.-]*\s+){1,4}(?:Painter|Group|Class|Workshop))|(?:Painter|Group|Class|Workshop) of ((?:[A-Z0-9][\w'.-]*\s*){1,4})",
                  text or "")
    return re.sub(r"\s+", " ", m.group(0)).strip().lower() if m else ""


def parts_of(text):
    return sorted(p for p, rx in PARTS.items() if re.search(rx, text or "", re.I))


def _accession(a, b):
    a, b = a.strip().lower(), b.strip().lower()
    if not a or not b or a == b:
        return None
    base = lambda x: re.sub(r"[\s\-–]*[a-z]{1,3}$", "", x)              # 1985.228.8a -> 1985.228.8
    lot = lambda x: x.rsplit(".", 1)[0] if x.count(".") >= 2 else None    # 1985.228.8 -> 1985.228
    if base(a) == base(b):
        return 1.0
    if lot(base(a)) and lot(base(a)) == lot(base(b)):
        return 0.6
    return None


def _date(a, b):
    if None in (a["begin"], a["end"], b["begin"], b["end"]):
        return None, 0
    gap = max(a["begin"], b["begin"]) - min(a["end"], b["end"])     # > 0 when the ranges do not touch
    return (1.0 if gap <= 0 else max(0.0, 1 - gap / DATE_GAP_LIMIT)), gap


def score_pair(a, b, text_sim=None, visual=None):
    """Evidence and confidence for two fragment records, or None when they contradict each other."""
    ev = {}
    if a["shape"] and b["shape"]:
        relation, sim = vocab.shape_relation(a["shape"], b["shape"])
        if relation in ("different", "same function group"):
            return None
        ev["shape"] = {"exact": 1.0, "more specific": 0.8, "less specific": 0.8}.get(relation, 0.4)
    if a["technique"] and b["technique"]:
        if a["technique"] != b["technique"] and "bilingual" not in (a["technique"], b["technique"]):
            return None
        ev["technique"] = 1.0 if a["technique"] == b["technique"] else 0.6
    if a["fabric"] and b["fabric"]:
        same_region = a["fabric"] in vocab.SOUTH_ITALIAN and b["fabric"] in vocab.SOUTH_ITALIAN
        ev["fabric"] = 1.0 if a["fabric"] == b["fabric"] else (0.4 if same_region else 0.0)
    date, gap = _date(a, b)
    if date is not None:
        if gap > DATE_GAP_LIMIT:
            return None
        ev["date"] = date
    if a["attribution"] and b["attribution"]:
        ev["attribution"] = 1.0 if a["attribution"] == b["attribution"] else 0.1
    acc = _accession(a["accession"], b["accession"])
    if acc is not None:
        ev["accession"] = acc
    if a["parts"] and b["parts"]:
        clash = set(a["parts"]) & set(b["parts"]) & SINGULAR
        ev["parts"] = 0.1 if clash else (0.8 if set(a["parts"]) != set(b["parts"]) else 0.5)
    if text_sim is not None:
        ev["text"] = float(min(1.0, text_sim))
    if visual:
        ev["visual"] = float(visual["combined"])
    if not ev:
        return None
    # Agreement on shape, technique, fabric and date is necessary but common: thousands of sherds are
    # "Attic red-figure kylix, about 500 BCE". It only scales the result. The confidence itself comes
    # from evidence specific to a pair, pulled toward a low prior so that one weak signal stays weak.
    generic = [ev[k] for k in GENERIC if k in ev]
    compatibility = sum(generic) / len(generic) if generic else 0.7
    specific = {k: v for k, v in ev.items() if k not in GENERIC}
    weight = PRIOR_WEIGHT + sum(WEIGHTS[k] for k in specific)
    support = (PRIOR * PRIOR_WEIGHT + sum(WEIGHTS[k] * v for k, v in specific.items())) / weight
    confidence = support * (0.5 + 0.5 * compatibility)
    strong_signal = ev.get("accession", 0) >= 0.6 or ev.get("attribution", 0) == 1.0 or ev.get("visual", 0) >= 0.75
    tier = "strong" if confidence >= 0.7 and strong_signal else "possible" if confidence >= 0.45 else "weak"
    return {"confidence": round(confidence, 3), "tier": tier, "evidence": {k: round(v, 3) for k, v in ev.items()},
            "measures": ({k: round(v, 3) for k, v in visual.items() if isinstance(v, float)} if visual else None)}


def propose(fragments, visual_fn=None, top=5, shortlist=40, min_confidence=0.3):
    """Candidates for each fragment.

    fragments: records from from_met / from_perseus (is_fragment already true).
    visual_fn(key) -> {other key: measures dict} or {} ; None when no image features exist.
    Each fragment is compared with a shortlist: the nearest by text, the nearest by image, and
    everything sharing its accession lot.
    """
    index = _TextIndex(fragments)
    by_key = {f["key"]: f for f in fragments}
    lots = {}
    for f in fragments:
        acc = f["accession"].strip().lower()
        if acc.count(".") >= 1:
            lots.setdefault(re.sub(r"[\s\-–]*[a-z]{1,3}$", "", acc).rsplit(".", 1)[0], []).append(f["key"])
    out = []
    for f in fragments:
        text = index.similar(f["key"])
        vis = visual_fn(f["key"]) if visual_fn else {}
        acc = f["accession"].strip().lower()
        lot = re.sub(r"[\s\-–]*[a-z]{1,3}$", "", acc).rsplit(".", 1)[0] if acc.count(".") >= 1 else None
        keys = set(sorted(text, key=text.get, reverse=True)[:shortlist])
        keys |= set(sorted(vis, key=lambda k: vis[k]["combined"], reverse=True)[:shortlist])
        keys |= set(lots.get(lot, []))
        keys.discard(f["key"])
        cands = []
        for key in keys:
            other = by_key.get(key)
            if not other or (f["source"] == "perseus" and other["source"] == "perseus" and f["name"] == other["name"]):
                continue
            s = score_pair(f, other, text.get(key), vis.get(key))
            if s and s["confidence"] >= min_confidence:
                cands.append({"key": key, "source": other["source"], "id": other["id"], "name": other["name"],
                              "title": other["title"], "url": other["url"], "image": other["image"], **s})
        cands.sort(key=lambda c: -c["confidence"])
        out.append({"key": f["key"], "source": f["source"], "id": f["id"], "name": f["name"], "title": f["title"],
                    "url": f["url"], "image": f["image"], "shape": f["shape"], "parts": f["parts"],
                    "candidates": cands[:top]})
    return out


class _TextIndex:
    """TF-IDF cosine between fragment texts."""

    def __init__(self, fragments):
        self.keys = [f["key"] for f in fragments]
        self.pos = {k: i for i, k in enumerate(self.keys)}
        self.index = link.Index([{"id": f["key"], "name": f["name"], "url": f["url"], "summary": f["text"],
                                  "decoration": "", "shape_raw": "", "shape": None, "technique": None, "fabric": None,
                                  "year": None, "ware": "", "painter": "", "period": "", "image": ""} for f in fragments])
        self.texts = {f["key"]: f["text"] for f in fragments}

    def similar(self, key):
        scores = self.index.text_scores(self.texts[key])
        scores.pop(self.pos[key], None)
        return {self.keys[i]: s for i, s in scores.items() if s > 0}
