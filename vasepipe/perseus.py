"""Perseus Art and Archaeology Browser: download the published metadata and
build the vase corpus the linking stage ranks against.

Source: the site's own repository (https://github.com/perseus-aa/perseus-aa.github.io),
file _data/metadata.csv. That is the data the website is generated from, so
no page scraping is needed.
"""
import csv
import html
import io
import json
import re
from pathlib import Path

import requests

from . import vocab

METADATA_URL = "https://raw.githubusercontent.com/perseus-aa/perseus-aa.github.io/main/_data/metadata.csv"
ITEM_URL = "https://perseus-aa.github.io/items/{id}.html"
IMAGE_URL = "http://iiif.perseus.tufts.edu/iiif/3/{image}/full/^{width},/0/default.jpg"
# Used only when a record has no usable date fields.
PERIOD_MIDPOINT = {"Geometric": -750, "Early Archaic": -650, "Archaic": -540, "High Archaic": -550,
                   "Late Archaic": -500, "Late Archaic/Early Classical": -480, "Early Classical": -465,
                   "Classical": -430, "High Classical": -430, "Late Classical": -360,
                   "Late Classical/Early Hellenistic": -325, "Hellenistic": -200, "Early Roman Imperial": 20,
                   "Roman Imperial": 150, "Late Roman Imperial": 350, "Late Bronze Age": -1300}


def _clean(text, limit=None):
    if not text:
        return ""
    text = html.unescape(re.sub(r"<[^>]+>", " ", text)).replace("\ufffd", "").replace("\x1a", "")
    text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def _split_bibl(text):
    """Perseus bibliography fields: '<bibl>ARV2, 604.48</bibl>; <bibl>...</bibl>; free text' -> list of citations."""
    if not text:
        return []
    return [c for c in (_clean(part) for part in re.split(r";\s*(?=<bibl|[A-Z])", text)) if c]


def _num(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def download(path="data/perseus_metadata.csv", force=False):
    path = Path(path)
    if path.exists() and not force:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(METADATA_URL, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        with open(path, "wb") as fh:
            for chunk in resp.iter_content(1 << 20):
                fh.write(chunk)
    return path


def build(csv_path="data/perseus_metadata.csv", out_path="data/perseus.json", decoration_limit=None):
    """Keep the vase records; normalise shape, ware and date through the vocabulary."""
    csv.field_size_limit(1 << 30)
    records = []
    with open(csv_path, newline="", encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            if r.get("objtype") != "Vase":
                continue
            shape = _clean(r.get("shape"))
            ware = _clean(r.get("ware"))
            date, estimated = _num(r.get("date_for_sort")), False
            if date == 0:  # Perseus stores 0 where no sort date was entered
                date = None
            if date is None and _num(r.get("unitary_date")):
                date = _num(r.get("unitary_date"))
            if date is None and _num(r.get("start_date")) and _num(r.get("end_date")):
                date = (_num(r["start_date"]) + _num(r["end_date"])) // 2
            if date is None:
                date = PERIOD_MIDPOINT.get(_clean(r.get("period")))
                estimated = date is not None
            painter = _clean(r.get("painter"))
            records.append({
                "id": r["objectid"], "name": _clean(r.get("name")), "collection": _clean(r.get("collection")),
                "shape_raw": shape, "shape": vocab.match_shape(shape), "ware": ware,
                "technique": vocab.first_hit(vocab.TECHNIQUES, ware), "fabric": vocab.first_hit(vocab.FABRICS, ware),
                "painter": (_clean(r.get("painter_mod")) + " " + painter).strip() if painter else "",
                "period": _clean(r.get("period")), "year": date, "year_estimated": estimated,
                "summary": _clean(r.get("summary")),
                "decoration": _clean(r.get("decoration_description"), decoration_limit),
                "shape_description": _clean(r.get("shape_description")),
                "image": _clean(r.get("image")),
                "fragment": bool(re.search("fragment", shape + " " + _clean(r.get("condit")), re.I)),
                "url": ITEM_URL.format(id=r["objectid"]),
                # pointers to further sources, used by sources.py
                "beazley_number": str(_num(r.get("beazley_number")) or ""),
                "potter": _clean(r.get("potter")), "findspot": _clean(r.get("context")),
                "citations": _split_bibl(r.get("primary_citation")) + _split_bibl(r.get("other_bibliography")),
                "sources_used": _split_bibl(r.get("sources_used")),
                "comparanda": [_clean(x) for x in re.findall(r"<rs[^>]*>(.*?)</rs>", r.get("comparanda") or "", re.S)],
                "condition": _clean(r.get("condit")),
            })
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(records, ensure_ascii=False))
    return records


def load(path="data/perseus.json"):
    if not Path(path).exists():
        raise SystemExit(f"{path} not found. Run `python -m vasepipe fetch-perseus` first.")
    return json.loads(Path(path).read_text())


def accession_of(record):
    """'New York 07.286.84' -> '07.286.84' for the vases Perseus records as held by the Met."""
    if "Metropolitan" not in record["collection"]:
        return None
    return re.sub(r"[^0-9a-z.\-]", "", re.sub(r"^new york\s*", "", record["name"].lower()))


def image_ids(record):
    """Perseus lists every view of a vase, comma-separated; the first is the lead image."""
    return [i.strip() for i in record["image"].split(",") if i.strip()]


def image_url(image_id, width=450):
    return IMAGE_URL.format(image=image_id, width=width)
