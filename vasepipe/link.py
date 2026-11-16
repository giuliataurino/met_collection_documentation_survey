"""Rank Perseus vases against one query (a Met record or a model description).

The match is description-mediated: shape, technique, fabric and date are
compared as vocabulary terms, decoration as TF-IDF cosine over text. An
optional visual score (see visual.py) can be blended in as a sixth component.
"""
import math
import re
from collections import Counter, defaultdict

from . import vocab

DEFAULT_WEIGHTS = {"shape": 30, "technique": 15, "fabric": 10, "date": 15, "text": 30, "visual": 0}
_STOP = set("the and with for from that this which who whom his her its their has have had are was were holds "
            "holding wears wearing stands standing one two left right side between both over under into each "
            "other while there also only very not but all above below behind front".split())


def tokens(text):
    return [w for w in re.findall(r"[a-zα-ω]{3,}", (text or "").lower()) if w not in _STOP]


class Index:
    def __init__(self, records):
        self.records = records
        docs = [Counter(tokens(" ".join([r["summary"], r["decoration"], r["shape_raw"]]))) for r in records]
        self.df = Counter(t for d in docs for t in d)
        n = len(docs)
        self.idf = {t: math.log(1 + n / c) for t, c in self.df.items()}
        self.postings = defaultdict(list)
        for i, d in enumerate(docs):
            w = {t: (1 + math.log(c)) * self.idf[t] for t, c in d.items()}
            norm = math.sqrt(sum(x * x for x in w.values())) or 1.0
            for t, x in w.items():
                self.postings[t].append((i, x / norm))

    def text_scores(self, text):
        q = Counter(t for t in tokens(text) if t in self.df)
        w = {t: (1 + math.log(c)) * self.idf[t] for t, c in q.items()}
        norm = math.sqrt(sum(x * x for x in w.values())) or 1.0
        scores = defaultdict(float)
        for t, x in w.items():
            for i, y in self.postings[t]:
                scores[i] += (x / norm) * y
        return scores

    def match(self, query, top=8, weights=None, visual_scores=None):
        """query: dict with shape, technique, fabric, year, text, exclude (all optional)."""
        weights = {**DEFAULT_WEIGHTS, **(weights or {})}
        # visual_scores: {perseus id: {"combined": x, "clip": .., ...}} from visual.object_scores.
        # The combined similarity is rescaled across the corpus so it can discriminate; raw measures are reported.
        v_lo = v_span = 0.0
        if visual_scores:
            vals = [v["combined"] for v in visual_scores.values()]
            v_lo, v_span = min(vals), (max(vals) - min(vals)) or 1.0
        text = self.text_scores(query.get("text", ""))
        tmax = max(text.values(), default=0.0)
        use = {"shape": bool(query.get("shape")), "technique": bool(query.get("technique")),
               "fabric": bool(query.get("fabric")), "date": query.get("year") is not None,
               "text": tmax > 0, "visual": bool(visual_scores) and weights["visual"] > 0}
        wsum = sum(weights[k] for k in use if use[k]) or 1.0
        out = []
        for i, r in enumerate(self.records):
            if r["id"] == query.get("exclude"):
                continue
            c = {}
            if use["shape"]:
                c["shape"] = vocab.shape_relation(r["shape"], query["shape"])[1]
            if use["technique"]:
                c["technique"] = 1.0 if r["technique"] == query["technique"] else 0.0
            if use["fabric"]:
                same_region = r["fabric"] in vocab.SOUTH_ITALIAN and query["fabric"] in vocab.SOUTH_ITALIAN
                c["fabric"] = 1.0 if r["fabric"] == query["fabric"] else (0.5 if same_region else 0.0)
            if use["date"]:
                c["date"] = 0.0 if r["year"] is None else 1 - min(abs(r["year"] - query["year"]) / 200, 1)
            if use["text"]:
                c["text"] = text.get(i, 0.0) / tmax
            if use["visual"]:
                c["visual"] = (visual_scores[r["id"]]["combined"] - v_lo) / v_span if r["id"] in visual_scores else 0.0
            score = sum(weights[k] * v for k, v in c.items()) / wsum
            out.append({"id": r["id"], "name": r["name"], "url": r["url"], "score": round(score, 4),
                        "components": {k: round(v, 3) for k, v in c.items()},
                        "shape": r["shape_raw"], "shape_id": r["shape"], "ware": r["ware"], "painter": r["painter"],
                        "period": r["period"], "summary": r["summary"],
                        "images": [i.strip() for i in r["image"].split(",") if i.strip()],
                        "visual": ({k: (round(v, 3) if isinstance(v, float) else v)
                                    for k, v in visual_scores[r["id"]].items()}
                                   if visual_scores and r["id"] in visual_scores else None)})
        out.sort(key=lambda m: -m["score"])
        return out[:top]
