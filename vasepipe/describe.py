"""Generation stage: ask Claude for an unconstrained and a vocabulary-constrained
description of one photograph. Needs ANTHROPIC_API_KEY in the environment."""
import base64
import io
import json
import os
import re
from pathlib import Path

import requests

from . import prompt

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
MAX_SIDE = 1568  # larger images are downscaled before sending


def load_image(source, cache_dir="data/cache/images"):
    """Return (jpeg_bytes, media_type) for a URL, a local path or raw image bytes. URLs are cached on disk."""
    from PIL import Image

    if isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
    elif re.match(r"https?://", source):
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
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=90)
    return buf.getvalue(), "image/jpeg"


MAX_IMAGES_PER_REQUEST = 20  # keeps a many-view object inside one request's size limits


def _ask(client, text, images, max_tokens):
    content = [{"type": "image", "source": {"type": "base64", "media_type": media_type,
                                            "data": base64.b64encode(data).decode()}} for data, media_type in images]
    if len(images) > 1:
        text = f"These are {len(images)} photographs of the same object.\n\n" + text
    content.append({"type": "text", "text": text})
    message = client.messages.create(model=MODEL, max_tokens=max_tokens, messages=[{"role": "user", "content": content}])
    return "".join(block.text for block in message.content if block.type == "text")


def parse_json(text):
    """Accept bare JSON, a fenced block, or JSON with a sentence around it."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start:end + 1])


def describe(image_sources, constrained_prompt=None, client=None):
    """Two requests: unconstrained, then vocabulary-constrained. Every view is sent with both."""
    if isinstance(image_sources, (str, bytes, bytearray)):
        image_sources = [image_sources]
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    images, skipped = [], 0
    for source in image_sources[:MAX_IMAGES_PER_REQUEST]:
        try:
            images.append(load_image(source))
        except Exception:  # a missing or restricted view must not lose the others
            skipped += 1
    if not images:
        raise RuntimeError("none of this object's images could be loaded")
    baseline = _ask(client, prompt.BASELINE, images, 600)
    reply = _ask(client, constrained_prompt or prompt.constrained(), images, 1500)
    try:
        model = parse_json(reply)
        if not isinstance(model, dict):
            raise ValueError("reply was not a JSON object")
        error = None
    except (ValueError, json.JSONDecodeError) as exc:
        model, error = None, f"constrained reply was not readable JSON: {exc}"
    notes = []
    if skipped:
        notes.append(f"{skipped} image(s) could not be loaded")
    if len(image_sources) > MAX_IMAGES_PER_REQUEST:
        notes.append(f"{len(image_sources) - MAX_IMAGES_PER_REQUEST} image(s) beyond the first {MAX_IMAGES_PER_REQUEST} were not sent")
    error = "; ".join(filter(None, [error] + notes)) or None
    return {"baseline": baseline, "model": model, "raw": reply, "error": error, "model_name": MODEL,
            "images_sent": len(images)}
