"""Met ingest: fetch Greek and Roman vases (fragments included) and normalise them.

Three sources, all producing records in the Met public API's field names:
  hasura      your GraphQL endpoint, key read from the environment
  public-api  collectionapi.metmuseum.org, no key, slow (one request per object)
  csv         the Met Open Access MetObjects.csv, no key, no image links
"""
import csv
import io
import json
import os
import re
import time
from pathlib import Path

import requests

from . import vocab

PUBLIC_API = "https://collectionapi.metmuseum.org/public/collection/v1"
GREEK_ROMAN_DEPARTMENT_ID = 13
FIELDS = ["objectID", "accessionNumber", "title", "objectName", "culture", "period", "objectDate",
          "objectBeginDate", "objectEndDate", "medium", "classification", "department",
          "primaryImage", "primaryImageSmall", "objectURL", "tags", "additionalImages", "webLabel", "artist"]
# normalised source key -> canonical field
_ALIASES = {
    "objectid": "objectID", "id": "objectID",
    "accessionnumber": "accessionNumber", "accessionnum": "accessionNumber", "objectnumber": "accessionNumber",
    "title": "title", "objectname": "objectName", "name": "objectName",
    "culture": "culture", "period": "period",
    "objectdate": "objectDate", "datedisplay": "objectDate", "date": "objectDate",
    "objectbegindate": "objectBeginDate", "begindate": "objectBeginDate",
    "objectenddate": "objectEndDate", "enddate": "objectEndDate",
    "medium": "medium", "classification": "classification",
    "department": "department", "departmentname": "department",
    "primaryimage": "primaryImage", "imageurl": "primaryImage", "image": "primaryImage",
    "primaryimagesmall": "primaryImageSmall",
    "objecturl": "objectURL", "url": "objectURL", "linkresource": "objectURL",
    "tags": "tags", "tagterms": "tags",
    "additionalimages": "additionalImages", "weblabel": "webLabel",
    "artist": "artist", "artistdisplayname": "artist",
}


def _nk(key):
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def normalise(raw):
    """Map any reasonably named record (camelCase, snake_case, CSV headers) to FIELDS."""
    out = {f: "" for f in FIELDS}
    for key, value in raw.items():
        field = _ALIASES.get(_nk(key))
        if field and value not in (None, "") and not out[field]:
            out[field] = value
    tags = out["tags"]
    if isinstance(tags, str):
        tags = [t for t in tags.split("|") if t]
    out["tags"] = [t if isinstance(t, str) else (t or {}).get("term") or (t or {}).get("name") or ""
                   for t in (tags or [])]
    out["tags"] = [t for t in out["tags"] if t]
    out["objectBeginDate"], out["objectEndDate"] = _int(out["objectBeginDate"]), _int(out["objectEndDate"])
    extra = out["additionalImages"]
    if isinstance(extra, str):
        extra = [u for u in re.split(r"[|\s]+", extra) if u]
    out["additionalImages"] = [str(u) for u in (extra or []) if u]
    out["webLabel"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(out["webLabel"] or ""))).strip()
    for f in FIELDS:
        if f not in ("tags", "objectBeginDate", "objectEndDate", "additionalImages"):
            out[f] = str(out[f]).strip()
    if not out["objectURL"] and out["objectID"].isdigit():
        out["objectURL"] = f"https://www.metmuseum.org/art/collection/search/{out['objectID']}"
    return out


def year(obj):
    b, e = obj.get("objectBeginDate"), obj.get("objectEndDate")
    if b is not None and e is not None:
        return round((b + e) / 2)
    return b if b is not None else e


def catalogue_terms(obj):
    """What the existing record already says, read through the vocabulary."""
    name, title = obj["objectName"], obj["title"]
    return {
        "shape": vocab.match_shape(name) or vocab.match_shape(title),
        "technique": vocab.first_hit(vocab.TECHNIQUES, " ".join([title, obj["medium"], obj["classification"], name])),
        "fabric": vocab.first_hit(vocab.FABRICS, obj["culture"] + " " + title),
        "period": vocab.period_of_year(year(obj)) or vocab.first_hit(vocab.PERIODS, obj["period"]),
        "fragment": bool(re.search(r"fragment|sherd", name + " | " + title, re.I)),
    }


def is_vase(obj):
    """Greek and Roman vases and vase fragments."""
    if obj["department"] and not re.search(r"greek|roman", obj["department"], re.I):
        return False
    if re.search(r"vase", obj["classification"], re.I):
        return True
    if obj["classification"] and not re.search(r"terracotta|ceramic|pottery|misc", obj["classification"], re.I):
        return False
    if vocab.match_shape(obj["objectName"]) or vocab.match_shape(obj["title"]):
        return True
    return bool(re.search(r"fragment|sherd", obj["objectName"] + obj["title"], re.I)
                and re.search(r"terracotta|ceramic|clay", obj["medium"] + obj["title"], re.I))


def find_rows(payload):
    """First list of objects anywhere in a JSON payload (e.g. data.<table>)."""
    if isinstance(payload, list):
        return payload if payload and isinstance(payload[0], dict) else []
    if isinstance(payload, dict):
        if {"objectid", "accessionnumber", "objectname"} & {_nk(k) for k in payload}:
            return [payload]
        for value in payload.values():
            rows = find_rows(value)
            if rows:
                return rows
    return []


# ---------------------------------------------------------------- Hasura
# Names below follow the Met private collection API guide. The department id is
# an inference: the guide shows CRDDeptID 11 for European Paintings, which is
# also that department's public API id, and Greek and Roman Art is 13 there.
# fetch_hasura checks the department name on the first page before going on.
DEFAULT_CRD_DEPT_ID = 13
MAX_PAGE_SIZE = 500


def images_of(obj):
    """Every image URL on a record, primary first, without duplicates."""
    urls = [obj.get("primaryImageSmall") or obj.get("primaryImage") or ""] + list(obj.get("additionalImages") or [])
    return list(dict.fromkeys(u for u in urls if u))


def _secret():
    for name in ("HASURA_ADMIN_SECRET", "HASURA_KEY", "HASURA_PREVIEW_ADMIN_SECRET"):
        if os.environ.get(name):
            return os.environ[name].strip().strip('"').strip("'")
    return None


def env_report():
    """Where settings were looked for and which names were found. Never prints values."""
    found = []
    for name in (".env", ".env.local"):
        path = Path(name)
        if path.is_file():
            keys = [line.split("=", 1)[0].replace("export ", "").strip() for line in path.read_text().splitlines()
                    if "=" in line and not line.lstrip().startswith("#")]
            found.append(f"{name} has: {', '.join(keys) or 'no settings'}")
        else:
            found.append(f"no {name}")
    try:
        import dotenv  # noqa: F401
        loader = ""
    except ImportError:
        loader = " python-dotenv is not installed, so .env files are not read: run `pip install -r requirements.txt`."
    return f"Looked in {Path.cwd()}: {'; '.join(found)}.{loader}"


def hasura_configured():
    return bool(os.environ.get("HASURA_GRAPHQL_URL") and _secret())


def _hasura_headers():
    key = _secret()
    if not key:
        raise HasuraError("HASURA_ADMIN_SECRET is not set. Put it in .env or .env.local (never commit it). " + env_report())
    header = os.environ.get("HASURA_AUTH_HEADER", "x-hasura-admin-secret")
    headers = {"Content-Type": "application/json", header: f"Bearer {key}" if header.lower() == "authorization" else key}
    if os.environ.get("HASURA_ROLE"):
        headers["x-hasura-role"] = os.environ["HASURA_ROLE"]
    return headers


class HasuraError(RuntimeError):
    pass


def _hasura_post(body):
    url = os.environ.get("HASURA_GRAPHQL_URL")
    if not url:
        raise HasuraError("HASURA_GRAPHQL_URL is not set (the full .../v1/graphql address). " + env_report())
    try:
        resp = requests.post(url, headers=_hasura_headers(), json=body, timeout=120, allow_redirects=False)
    except requests.RequestException as exc:
        raise HasuraError(f"Could not reach Hasura: {type(exc).__name__}") from None
    if resp.status_code != 200:
        raise HasuraError(f"Hasura request failed: HTTP {resp.status_code}")
    data = resp.json()
    if data.get("errors"):  # GraphQL failures arrive with HTTP 200
        raise HasuraError("Hasura returned GraphQL errors: " + "; ".join(e.get("message", "?") for e in data["errors"]))
    if data.get("data") is None:
        raise HasuraError("Hasura returned no data")
    return data["data"]


def dept_id():
    return int(os.environ.get("MET_CRD_DEPT_ID") or DEFAULT_CRD_DEPT_ID)


def flatten_hasura(row):
    """One objects_crd row (with apiObject) -> the public API's field names."""
    api = row.get("apiObject") or {}
    images = api.get("images") or {}
    primary = images.get("primary") or {}
    lead = {primary.get("sourceImageUrl"), primary.get("thumbnailImageUrl")}
    extra = [i.get("thumbnailImageUrl") or i.get("sourceImageUrl") for i in (images.get("all") or []) if i]
    return {
        "objectID": row.get("CRD_ObjectId") or api.get("objectID"),
        "accessionNumber": (api.get("accessionNumber") or row.get("ObjectNumber") or "").strip(),
        "title": (((api.get("titles") or {}).get("primary") or {}).get("title")) or "",
        "objectName": row.get("ObjectName") or "", "culture": row.get("Culture") or "", "period": row.get("Period") or "",
        "objectDate": row.get("Dated") or "", "objectBeginDate": row.get("DateBegin"), "objectEndDate": row.get("DateEnd"),
        "medium": row.get("Medium") or "",
        "classification": (((api.get("classifications") or {}).get("primary") or {}).get("classification")) or "",
        "department": api.get("department") or "",
        "primaryImage": primary.get("sourceImageUrl") or "", "primaryImageSmall": primary.get("thumbnailImageUrl") or "",
        "additionalImages": [u for u in dict.fromkeys(extra) if u and u not in lead],
        "tags": [t.get("Term") for t in (row.get("tags") or []) if t and t.get("Term")],
        "webLabel": api.get("webLabel") or "",
        "artist": (((api.get("artists") or {}).get("primary") or {}).get("displayName")) or "",
    }


def fetch_hasura_page(offset, limit, query_path="queries/vases.graphql"):
    """One bounded page of Greek and Roman objects, flattened. Fixed query; only paging varies."""
    limit = max(1, min(int(limit), MAX_PAGE_SIZE))
    variables = {"where": {"CRDDeptID": {"_eq": dept_id()}}, "limit": limit, "offset": max(0, int(offset))}
    rows = _hasura_post({"query": Path(query_path).read_text(), "variables": variables}).get("objects_crd") or []
    return [flatten_hasura(r) for r in rows], limit


def check_department(flat_rows):
    names = {r["department"] for r in flat_rows if r["department"]}
    if names and not any(re.search(r"greek|roman", n, re.I) for n in names):
        raise HasuraError(f"CRDDeptID {dept_id()} returned department {sorted(names)}, not Greek and Roman Art. "
                          "Set MET_CRD_DEPT_ID to the right id and run again.")
    return names


def fetch_hasura(query_path="queries/vases.graphql", page_size=200, limit=None):
    """Every Greek and Roman vase and fragment. `limit` caps the vases kept, not the rows scanned."""
    kept, offset = [], 0
    while True:
        rows, size = fetch_hasura_page(offset, page_size, query_path)
        if offset == 0:
            check_department(rows)
        kept.extend(r for r in rows if is_vase(normalise(r)))
        offset += size
        print(f"  hasura: checked {offset - size + len(rows)} objects, kept {len(kept)} vases and fragments")
        if len(rows) < size or (limit and len(kept) >= limit):
            break
    return kept[:limit] if limit else kept


def introspect(table=None):
    """List the query root's fields, or one type's fields."""
    if table:
        q = '{ __type(name: "%s") { name fields { name type { name kind ofType { name kind } } } } }' % table
        t = _hasura_post({"query": q})["__type"]
        if not t:
            raise HasuraError(f"No type named {table}.")
        return [f"{f['name']}: {f['type']['name'] or (f['type']['ofType'] or {}).get('name')}" for f in t["fields"] or []]
    q = "{ __schema { queryType { fields { name } } } }"
    return [f["name"] for f in _hasura_post({"query": q})["__schema"]["queryType"]["fields"]]


# ---------------------------------------------------------------- public API
# https://metmuseum.github.io/ : no key. One request lists the ids, then one request per object.

class MetApiError(RuntimeError):
    pass


_session = None


def _public_get(path, params=None):
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers["User-Agent"] = "vase-pipeline/0.1 (research prototype)"
    try:
        resp = _session.get(f"{PUBLIC_API}/{path}", params=params, timeout=60)
    except requests.RequestException as exc:
        raise MetApiError(f"Could not reach the Met public API: {type(exc).__name__}") from None
    return resp


def public_object_ids(query=None):
    """Ids to check: the whole Greek and Roman department, or a search within it."""
    if query:
        resp = _public_get("search", {"departmentId": GREEK_ROMAN_DEPARTMENT_ID, "q": query})
    else:
        resp = _public_get("objects", {"departmentIds": GREEK_ROMAN_DEPARTMENT_ID})
    if resp.status_code != 200:
        raise MetApiError(f"The Met public API answered HTTP {resp.status_code} to the id listing.")
    return sorted(resp.json().get("objectIDs") or [])


def public_object(object_id, cache_dir="data/cache/met", pause=0.02):
    """One object record, cached on disk. None if the API has no record for the id."""
    path = Path(cache_dir) / f"{int(object_id)}.json"
    if path.exists():
        return json.loads(path.read_text())
    resp = _public_get(f"objects/{int(object_id)}")
    time.sleep(pause)  # the API asks for under 80 requests a second
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise MetApiError(f"The Met public API answered HTTP {resp.status_code} for object {object_id}.")
    raw = resp.json()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw))
    return raw


def fetch_public_api(limit=None, query=None):
    """Greek and Roman vases and fragments. `limit` caps the vases kept, not the objects checked."""
    ids = public_object_ids(query)
    print(f"  public API: {len(ids)} Greek and Roman objects to check" + (f" for '{query}'" if query else ""))
    rows = []
    for n, oid in enumerate(ids, 1):
        raw = public_object(oid)
        if raw and is_vase(normalise(raw)):
            rows.append(raw)
            if limit and len(rows) >= limit:
                break
        if n % 500 == 0:
            print(f"  public API: checked {n}, kept {len(rows)}")
    return rows


def load_file(path):
    """JSON (array, GraphQL response, JSON lines) or CSV with a header row."""
    text = Path(path).read_text(encoding="utf-8-sig")
    if str(path).lower().endswith(".csv"):
        return list(csv.DictReader(io.StringIO(text)))
    try:
        return find_rows(json.loads(text))
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]


def prepare(rows, keep_only_vases=True):
    objs = [normalise(r) for r in rows]
    objs = [o for o in objs if o["objectID"] or o["accessionNumber"]]
    if keep_only_vases:
        objs = [o for o in objs if is_vase(o)]
    seen = {}
    for o in objs:
        seen[o["objectID"] or o["accessionNumber"]] = o
    return list(seen.values())
