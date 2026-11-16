"""Stage 6: search a CONTENTdm site for bibliographic and archival material.

Uses CONTENTdm's read-only dmwebservices API (no key):
  {base}/digital/bl/dmwebservices/index.php?q=dmQuery/{alias}/{searchstrings}/{fields}/{sortby}/{max}/{start}/0/0/0/0/0/0/json
  searchstrings: field^term^mode^operator, joined with "!"; CISOSEARCHALL searches every field.

Defaults point at the Met's Watson Library digital collections. The host and
the field nicknames are assumptions that have NOT been checked from here:
run `python -m vasepipe check-contentdm` once. Override with CONTENTDM_BASE_URL,
CONTENTDM_COLLECTIONS (aliases joined with "!", default "all") and
CONTENTDM_FIELDS.
"""
import hashlib
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

import requests

DEFAULT_BASE = "https://libmma.contentdm.oclc.org"
DEFAULT_FIELDS = "title!creato!date!subjec!descri"


class ContentdmError(RuntimeError):
    pass


def base_url():
    return (os.environ.get("CONTENTDM_BASE_URL") or DEFAULT_BASE).rstrip("/")


def _clean_term(term):
    """The API puts the search in the URL path: drop the characters it uses as separators."""
    return re.sub(r"\s+", " ", re.sub(r"[/^!?#%&\\\"]", " ", term)).strip()


def query_url(term, mode="all", max_records=10, start=1):
    """mode: all (every word), exact (the phrase), any."""
    alias = os.environ.get("CONTENTDM_COLLECTIONS") or "all"
    fields = os.environ.get("CONTENTDM_FIELDS") or DEFAULT_FIELDS
    search = f"CISOSEARCHALL^{_clean_term(term)}^{mode}^and"
    return (f"{base_url()}/digital/bl/dmwebservices/index.php?q=dmQuery/{alias}/{quote(search, safe='^')}/{fields}"
            f"/nosort/{int(max_records)}/{int(start)}/0/0/0/0/0/0/json")


def _get(url, cache_dir="data/cache/contentdm", pause=0.2):
    path = Path(cache_dir) / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    if path.exists():
        return json.loads(path.read_text())
    try:
        resp = requests.get(url, timeout=60, headers={"User-Agent": "vase-pipeline/0.1 (research prototype)"})
    except requests.RequestException as exc:
        raise ContentdmError(f"Could not reach CONTENTdm at {base_url()}: {type(exc).__name__}") from None
    time.sleep(pause)
    if resp.status_code != 200:
        raise ContentdmError(f"CONTENTdm answered HTTP {resp.status_code}.")
    try:
        data = resp.json()
    except ValueError:
        raise ContentdmError("CONTENTdm did not answer with JSON; check CONTENTDM_BASE_URL.") from None
    if isinstance(data, dict) and data.get("code") and data.get("message"):
        raise ContentdmError(f"CONTENTdm error: {data['message']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data


def collections():
    """[{alias, name}] for the site: also the quickest check that the host is right."""
    data = _get(f"{base_url()}/digital/bl/dmwebservices/index.php?q=dmGetCollectionList/json")
    return [{"alias": str(c.get("secondary_alias") or c.get("alias", "")).strip("/"), "name": c.get("name", "")}
            for c in data if isinstance(c, dict)]


def search(term, mode="all", max_records=10):
    """Records matching one term: [{collection, pointer, title, creator, date, subject, url}], and the total."""
    data = _get(query_url(term, mode, max_records))
    records = []
    for r in data.get("records") or []:
        alias = str(r.get("collection", "")).strip("/")
        pointer = r.get("pointer")
        if not alias or pointer in (None, ""):
            continue
        text = lambda k: r[k] if isinstance(r.get(k), str) else ""
        records.append({"collection": alias, "pointer": pointer, "title": text("title"), "creator": text("creato"),
                        "date": text("date"), "subject": text("subjec"),
                        "url": f"{base_url()}/digital/collection/{alias}/id/{pointer}"})
    return records, int((data.get("pager") or {}).get("total") or 0)


def find(queries, max_per_query=10, max_results=25):
    """Run several weighted queries and merge the hits.

    queries: [{"term", "mode", "weight", "kind"}]. A record's score is the sum of the weights of
    the queries that found it, so material matching the accession number and the shape ranks above
    material matching the shape alone.
    """
    merged, log = {}, []
    for q in queries:
        try:
            records, total = search(q["term"], q.get("mode", "all"), max_per_query)
        except ContentdmError as exc:
            log.append({**q, "total": None, "error": str(exc)})
            if "reach" in str(exc) or "JSON" in str(exc):
                break  # the site itself is unavailable: no point trying the rest
            continue
        log.append({**q, "total": total})
        for rec in records:
            key = (rec["collection"], rec["pointer"])
            hit = merged.setdefault(key, {**rec, "score": 0.0, "matched": []})
            hit["score"] += q.get("weight", 1.0)
            hit["matched"].append({"term": q["term"], "kind": q.get("kind", "")})
    results = sorted(merged.values(), key=lambda r: -r["score"])[:max_results]
    for r in results:
        r["score"] = round(r["score"], 2)
    return results, log
