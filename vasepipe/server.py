"""Local dashboard server: python -m vasepipe serve

Serves the dashboards and the pipeline's output on 127.0.0.1 only, and gives
the dashboard one fixed, paged Hasura lookup. The secret stays in this
process: it is never sent to the browser, and the page cannot supply its own
GraphQL. Only dashboard/ and data/ result files are served, so .env files
cannot be fetched. Do not use `python -m http.server` in this folder: it would
serve .env to your whole network.
"""
import base64
import json
import mimetypes
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import met

ROOT = Path.cwd()
DATA_FILES = {"runs.jsonl", "runs.csv", "vocab.json", "met_objects.json", "fragments.jsonl", "sources.jsonl"}


def resolve_static(url_path):
    """Map a URL path to a file we are willing to serve, or None."""
    parts = [p for p in url_path.split("/") if p]
    if not parts:
        parts = ["dashboard", "index.html"]
    if any(p.startswith(".") or p in ("..",) for p in parts):
        return None
    if parts[0] == "dashboard":
        if len(parts) == 1:
            parts.append("index.html")
        path = ROOT.joinpath(*parts)
        return path if path.is_file() and path.suffix in (".html", ".css", ".js", ".json", ".svg", ".png") else None
    if parts[0] == "data" and len(parts) == 2 and parts[1] in DATA_FILES:
        path = ROOT / "data" / parts[1]
        return path if path.is_file() else None
    return None


def met_vases_page(offset, limit):
    """One page for the dashboard: only vases and fragments, only display fields."""
    rows, size = met.fetch_hasura_page(offset, limit)
    if offset == 0:
        met.check_department(rows)
    objects = [o for o in (met.normalise(r) for r in rows) if met.is_vase(o)]
    return {"objects": objects, "scanned": len(rows), "next_offset": offset + size if len(rows) == size else None}


_public_ids = {}  # search term -> id list, kept for the life of the server


def met_public_page(offset, limit, query=""):
    """A slice of the public API's Greek and Roman ids, fetched one object at a time; vases only."""
    query = (query or "").strip()[:80]
    if query not in _public_ids:
        _public_ids[query] = met.public_object_ids(query or None)
    ids = _public_ids[query]
    chunk = ids[offset:offset + max(1, min(int(limit), 80))]
    objects = []
    for oid in chunk:
        raw = met.public_object(oid)
        if raw:
            obj = met.normalise(raw)
            if met.is_vase(obj):
                objects.append(obj)
    end = offset + len(chunk)
    return {"objects": objects, "scanned": len(chunk), "total": len(ids), "next_offset": end if end < len(ids) else None}


MAX_BODY = 40 * 1024 * 1024
IMAGE_HOSTS = ("metmuseum.org", "iiif.perseus.tufts.edu")


def allowed_image_url(url):
    """Only fetch images from the Met and Perseus (plus MET_IMAGE_HOSTS), never arbitrary addresses."""
    parsed = urlparse(str(url))
    host = (parsed.hostname or "").lower()
    extra = tuple(h.strip().lower() for h in os.environ.get("MET_IMAGE_HOSTS", "").split(",") if h.strip())
    return parsed.scheme in ("http", "https") and any(host == h or host.endswith("." + h) for h in IMAGE_HOSTS + extra)


def describe_request(payload):
    """The test bench's image run: both descriptions for one object, made with the server's API key."""
    from . import describe
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("ANTHROPIC_API_KEY is not set. Add it to .env and restart the server.")
    urls = [str(u) for u in (payload.get("images") or [])]
    blocked = sorted({urlparse(u).hostname or "?" for u in urls if not allowed_image_url(u)})
    if blocked:
        raise ValueError("Images from " + ", ".join(blocked) + " are not fetched. Add the host to MET_IMAGE_HOSTS if it is the Met's.")
    sources = list(urls)
    for data_url in payload.get("image_data") or []:
        match = re.match(r"data:image/[a-z+.-]+;base64,(.+)$", str(data_url), re.S)
        if not match:
            raise ValueError("An attached image could not be read.")
        sources.append(base64.b64decode(match.group(1)))
    if not sources:
        raise ValueError("No image to describe.")
    prompt_text = payload.get("prompt")
    out = describe.describe(sources, prompt_text if isinstance(prompt_text, str) and prompt_text.strip() else None)
    return {k: out[k] for k in ("baseline", "model", "error", "model_name", "images_sent")}


class Handler(BaseHTTPRequestHandler):
    server_version = "vasepipe"

    def _send(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, payload):
        self._send(status, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/status":
            host = urlparse(os.environ.get("HASURA_GRAPHQL_URL", "")).hostname or ""
            env = "preview" if "preview" in host else "production" if "production" in host else ("custom" if host else "")
            return self._json(200, {"hasura_configured": met.hasura_configured(), "environment": env,
                                    "claude_configured": bool(os.environ.get("ANTHROPIC_API_KEY"))})
        if url.path == "/api/met/vases":
            q = parse_qs(url.query)
            try:
                offset, limit = int(q.get("offset", ["0"])[0]), int(q.get("limit", ["200"])[0])
                return self._json(200, met_vases_page(max(0, offset), limit))
            except ValueError:
                return self._json(400, {"error": "offset and limit must be whole numbers"})
            except met.HasuraError as exc:  # message is ours, never the upstream body or the secret
                return self._json(502, {"error": str(exc)})
        if url.path == "/api/met/public":
            q = parse_qs(url.query)
            try:
                offset, limit = int(q.get("offset", ["0"])[0]), int(q.get("limit", ["40"])[0])
                return self._json(200, met_public_page(max(0, offset), limit, q.get("q", [""])[0]))
            except ValueError:
                return self._json(400, {"error": "offset and limit must be whole numbers"})
            except met.MetApiError as exc:
                return self._json(502, {"error": str(exc)})
        if url.path in ("/", "/dashboard"):
            self.send_response(302)
            self.send_header("Location", "/dashboard/")
            self.end_headers()
            return
        path = resolve_static(url.path)
        if not path:
            return self._send(404, b"Not found", "text/plain")
        ctype = "application/x-ndjson" if path.suffix == ".jsonl" else (mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self._send(200, path.read_bytes(), ctype + ("; charset=utf-8" if path.suffix in (".html", ".json", ".jsonl", ".csv", ".js") else ""))

    def do_POST(self):
        if urlparse(self.path).path != "/api/describe":
            return self._send(404, b"Not found", "text/plain")
        # Same-origin only: a page on another site must not be able to spend the API key.
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).hostname not in ("localhost", "127.0.0.1"):
            return self._json(403, {"error": "Requests are accepted from this dashboard only."})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                return self._json(413, {"error": "The request is empty or too large."})
            payload = json.loads(self.rfile.read(length))
            return self._json(200, describe_request(payload))
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})
        except Exception as exc:  # API, network or image failures: name the kind, not the details
            return self._json(502, {"error": f"The description request failed ({type(exc).__name__}). Check the server window."})

    def log_message(self, fmt, *args):  # keep query strings and errors out of the console noise
        pass


def serve(port=8000):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Test bench:  http://localhost:{port}/dashboard/\nResults:     http://localhost:{port}/dashboard/results.html\n"
          f"Hasura:      {'configured' if met.hasura_configured() else 'not configured (set HASURA_GRAPHQL_URL and HASURA_ADMIN_SECRET)'}\n"
          f"Claude:      {'configured' if os.environ.get('ANTHROPIC_API_KEY') else 'not configured (set ANTHROPIC_API_KEY for image runs)'}\n"
          "Only this computer can reach it. Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
