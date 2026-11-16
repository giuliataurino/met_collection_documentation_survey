"""Stage 3: visual similarity between vase images.

Four measures per image pair, each in 0..1:
  clip   cosine of CLIP embeddings (what the image shows). Needs the optional
         requirements-visual.txt; skipped if not installed.
  edge   cosine of a gradient-orientation grid (outline and drawing direction).
  hist   intersection of hue/saturation/value histograms (clay, glaze, added colour).
  dhash  agreement of a 64-bit difference hash (near-identical photographs).

`combined` is their weighted mean over whichever measures are present. Two
objects are compared through their best-matching pair of views.

Features are computed once and kept in data/features_<name>.npz. The CLIP path
has not been run in testing; the other three are covered by the test suite.
"""
import io
import re
from pathlib import Path

import numpy as np
import requests

WEIGHTS = {"clip": 0.6, "edge": 0.2, "hist": 0.15, "dhash": 0.05}
CLIP_MODEL = "clip-ViT-B-32"
_clip_model = None
_clip_failed = False


def open_image(source, cache_dir="data/cache/images"):
    """PIL image from a URL (cached on disk), a path, or raw bytes."""
    from PIL import Image
    if isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
    elif re.match(r"https?://", str(source)):
        cache = Path(cache_dir)
        cache.mkdir(parents=True, exist_ok=True)
        path = cache / (re.sub(r"[^A-Za-z0-9._-]", "_", source)[-150:])
        if not path.exists():
            resp = requests.get(source, timeout=120, headers={"User-Agent": "vase-pipeline/0.1 (research prototype)"})
            resp.raise_for_status()
            path.write_bytes(resp.content)
        raw = path.read_bytes()
    else:
        raw = Path(source).read_bytes()
    return Image.open(io.BytesIO(raw)).convert("RGB")


def _clip():
    """The CLIP model, or None when the optional dependency is absent."""
    global _clip_model, _clip_failed
    if _clip_model is None and not _clip_failed:
        try:
            from sentence_transformers import SentenceTransformer
            _clip_model = SentenceTransformer(CLIP_MODEL)
        except Exception as exc:  # not installed, or weights unavailable
            _clip_failed = True
            print(f"  CLIP unavailable ({type(exc).__name__}); using edge, colour and hash measures only.")
    return _clip_model


def features(image, use_clip=True):
    """All per-image descriptors as a dict of float32 arrays."""
    small = np.asarray(image.resize((128, 128)), dtype=np.float32) / 255.0
    grey = small.mean(axis=2)
    # hist: 8 hue x 4 saturation x 4 value bins
    hsv = np.asarray(image.resize((64, 64)).convert("HSV"), dtype=np.float32) / 256.0
    bins = (np.minimum((hsv[..., 0] * 8).astype(int), 7) * 16 + np.minimum((hsv[..., 1] * 4).astype(int), 3) * 4
            + np.minimum((hsv[..., 2] * 4).astype(int), 3))
    hist = np.bincount(bins.ravel(), minlength=128).astype(np.float32)
    hist /= hist.sum() or 1.0
    # edge: 9 orientation bins on a 4x4 grid, weighted by gradient strength
    gy, gx = np.gradient(grey)
    mag, ang = np.hypot(gx, gy), (np.arctan2(gy, gx) % np.pi)
    obin = np.minimum((ang / np.pi * 9).astype(int), 8)
    edge = np.zeros((4, 4, 9), dtype=np.float32)
    for i in range(4):
        for j in range(4):
            cell = (slice(i * 32, (i + 1) * 32), slice(j * 32, (j + 1) * 32))
            edge[i, j] = np.bincount(obin[cell].ravel(), weights=mag[cell].ravel(), minlength=9)
    edge = edge.ravel()
    edge /= np.linalg.norm(edge) or 1.0
    # dhash: 8x8 horizontal difference bits
    tiny = np.asarray(image.convert("L").resize((9, 8)), dtype=np.float32)
    dhash = (tiny[:, 1:] > tiny[:, :-1]).astype(np.float32).ravel()
    out = {"hist": hist, "edge": edge, "dhash": dhash}
    model = _clip() if use_clip else None
    if model is not None:
        out["clip"] = np.asarray(model.encode([image], normalize_embeddings=True)[0], dtype=np.float32)
    return out


def pair_measures(a, b):
    """Similarity measures between two feature dicts (single images)."""
    out = {"hist": float(np.minimum(a["hist"], b["hist"]).sum()),
           "edge": float(np.clip(a["edge"] @ b["edge"], 0, 1)),
           "dhash": float(1 - np.abs(a["dhash"] - b["dhash"]).mean())}
    if "clip" in a and "clip" in b:
        # CLIP cosines between photographs sit roughly in 0.4..1; stretch that to 0..1
        out["clip"] = float(np.clip((a["clip"] @ b["clip"] - 0.4) / 0.6, 0, 1))
    return out


def combine(measures):
    w = {k: WEIGHTS[k] for k in measures}
    return sum(w[k] * measures[k] for k in w) / (sum(w.values()) or 1.0)


class Store:
    """Features for many images, grouped by object id. Saved as one .npz."""

    def __init__(self, path):
        self.path = Path(path)
        self.owner, self.source, self.arrays = [], [], {}
        if self.path.exists():
            data = np.load(self.path, allow_pickle=False)
            self.owner, self.source = [str(x) for x in data["owner"]], [str(x) for x in data["source"]]
            self.arrays = {k: data[k] for k in ("hist", "edge", "dhash", "clip") if k in data}
        self._pending = []

    def has(self, owner, source):
        return (str(owner), str(source)) in self._seen()

    def _seen(self):
        if not hasattr(self, "_seen_cache") or len(self._seen_cache) != len(self.owner):
            self._seen_cache = set(zip(self.owner, self.source))
        return self._seen_cache

    def add(self, owner, source, feats):
        self._pending.append((str(owner), str(source), feats))

    def flush(self):
        if not self._pending:
            return
        keys = set(self.arrays) if self.arrays else set(self._pending[0][2])
        keys &= set.intersection(*(set(f) for _, _, f in self._pending))
        for k in keys:
            new = np.stack([f[k] for _, _, f in self._pending]).astype(np.float32)
            self.arrays[k] = np.concatenate([self.arrays[k], new]) if k in self.arrays and len(self.owner) else new
        self.arrays = {k: v for k, v in self.arrays.items() if k in keys}
        self.owner += [o for o, _, _ in self._pending]
        self.source += [s for _, s, _ in self._pending]
        self._pending = []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(self.path, owner=np.array(self.owner), source=np.array(self.source), **self.arrays)

    def rows_of(self, owner):
        owner = str(owner)
        return [i for i, o in enumerate(self.owner) if o == owner]

    def __len__(self):
        return len(self.owner)


def build(store, items, use_clip=True, every=25, label="images"):
    """items: iterable of (owner id, image source). Skips what the store has and images that fail."""
    items = [(o, s) for o, s in items if not store.has(o, s)]
    done = failed = 0
    for owner, source in items:
        try:
            store.add(owner, source, features(open_image(source), use_clip))
            done += 1
        except Exception as exc:  # one bad or restricted image must not stop the run
            failed += 1
            if failed <= 5:
                print(f"  skipped {source}: {type(exc).__name__}")
        if (done + failed) % every == 0:
            store.flush()
            print(f"  {label}: {done + failed} of {len(items)} ({failed} failed)")
    store.flush()
    return done, failed


def matrix(a_store, a_rows, b_store, b_rows=None):
    """Per-measure similarity matrices between two sets of images (rows of the stores)."""
    out = {}
    b_rows = slice(None) if b_rows is None else b_rows
    for k in WEIGHTS:
        if k not in a_store.arrays or k not in b_store.arrays:
            continue
        a, b = a_store.arrays[k][a_rows], b_store.arrays[k][b_rows]
        if k == "hist":
            out[k] = np.minimum(a[:, None, :], b[None, :, :]).sum(axis=2)
        elif k == "dhash":
            out[k] = 1 - np.abs(a[:, None, :] - b[None, :, :]).mean(axis=2)
        elif k == "clip":
            out[k] = np.clip((a @ b.T - 0.4) / 0.6, 0, 1)
        else:
            out[k] = np.clip(a @ b.T, 0, 1)
    return out


def object_scores(query_store, query_owner, corpus_store):
    """Best-view similarity of one object to every object in the corpus.

    Returns {corpus owner: {"combined": x, "clip": .., "edge": .., "hist": .., "dhash": .., "view": source}}.
    """
    rows = query_store.rows_of(query_owner)
    if not rows or not len(corpus_store):
        return {}
    mats = matrix(query_store, rows, corpus_store)
    weights = {k: WEIGHTS[k] for k in mats}
    combined = sum(weights[k] * mats[k] for k in mats) / sum(weights.values())
    best_q = combined.argmax(axis=0)                       # best query view for each corpus image
    best = combined.max(axis=0)
    out = {}
    for j, owner in enumerate(corpus_store.owner):
        if owner not in out or best[j] > out[owner]["combined"]:
            out[owner] = {"combined": float(best[j]), "view": corpus_store.source[j],
                          **{k: float(mats[k][best_q[j], j]) for k in mats}}
    return out
