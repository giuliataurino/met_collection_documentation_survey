"""Check model output against the vocabulary and against the catalogue."""
import re

from . import vocab

_GENERIC_WORDS = re.compile(r"\b(vase|vessel|pot|urn|container|jar|jug|cup|bowl)s?\b", re.I)
_LABELS = sorted({x for s in vocab.SHAPES.values() for x in (s["label"], s["aat"])}, key=len, reverse=True)


def scan_text(text):
    """Deepest vocabulary shape a free text mentions, and the generic vessel words left over."""
    text = text or ""
    hits = [s["id"] for s in vocab.SHAPES.values() if s["id"] not in vocab.GENERIC and s["re"].search(text)]
    deepest = max(hits, key=vocab.depth, default=None)
    stripped = text
    for label in _LABELS:
        stripped = re.sub(re.escape(label), " ", stripped, flags=re.I)
    generic = sorted({w.lower() for w in _GENERIC_WORDS.findall(stripped)})
    return {"deepest": deepest, "terms": hits, "generic": generic}


def validate(model, catalogue):
    """model: the constrained JSON reply. catalogue: met.catalogue_terms(obj)."""
    rows = []
    for field, key, table in (("shape", "shape_id", vocab.SHAPES), ("technique", "technique_id", vocab.TECHNIQUES),
                              ("fabric", "fabric_id", vocab.FABRICS), ("period", "period_id", vocab.PERIODS)):
        value, ref = model.get(key), catalogue.get(field)
        status = "none" if value is None else ("ok" if value in table else "out_of_vocabulary")
        if value is None or not ref or status != "ok":
            relation = ""
        elif field == "shape":
            relation = vocab.shape_relation(value, ref)[0]
        else:
            relation = "exact" if value == ref else "different"
        rows.append({"field": field, "model": value, "status": status, "catalogue": ref, "relation": relation})
    rows.append({"field": "fragment", "model": bool(model.get("is_fragment")), "status": "ok",
                 "catalogue": bool(catalogue.get("fragment")),
                 "relation": "exact" if bool(model.get("is_fragment")) == bool(catalogue.get("fragment")) else "different"})
    return {"rows": rows, "out_of_vocabulary": sum(r["status"] == "out_of_vocabulary" for r in rows),
            "description_scan": scan_text(model.get("description")),
            "declared_gaps": [str(x) for x in (model.get("out_of_vocabulary") or []) if x]}
