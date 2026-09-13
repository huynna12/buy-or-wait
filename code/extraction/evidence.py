"""Collect a request's amendments from its messages and images, with a JSON cache.

The cache is keyed by prompt version plus a hash of exactly what the model
sees, so editing a prompt or a message re-extracts only what changed. With no
model available (offline), uncached evidence is simply skipped.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

from data.loader import Dataset
from engine.amendments import Amendment
from engine.models import Request
from extraction import images, messages
from extraction.usage import CallUsage, UsageLog

CACHE_DIR = Path(__file__).resolve().parent / "cache"


class JsonModel(Protocol):
    def extract(self, system: str, content, schema: dict, purpose: str) -> tuple[dict, CallUsage]: ...


class JsonCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, object] = json.loads(path.read_text()) if path.exists() else {}

    def get(self, key: str):
        return self.data.get(key)

    def put(self, key: str, value) -> None:
        self.data[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True))


class EvidenceExtractor:
    def __init__(self, model: JsonModel | None, usage: UsageLog, *, cache_dir: Path = CACHE_DIR,
                 refresh: bool = False) -> None:
        self.model, self.usage, self.refresh = model, usage, refresh
        self.message_cache = JsonCache(cache_dir / "messages.json")
        self.image_cache = JsonCache(cache_dir / "images.json")

    def amendments_for(self, ds: Dataset, request: Request) -> list[Amendment]:
        found: list[Amendment] = []
        for event in ds.events_by_user.get(request.user_id, []):
            image = ds.images_by_event.get(event.event_id)
            if event.amount is None and image is not None and image.path.exists():
                raw = self._call(self.image_cache, f"{image.image_id}:{event.event_id}",
                                 images.PROMPT_VERSION + image.path.read_bytes().hex()[:4000] + event.description,
                                 images.SYSTEM_PROMPT, lambda: images.user_content(image, event), images.SCHEMA, "image")
                amendment = images.to_amendment(raw, image, event)
                if amendment:
                    found.append(amendment)
        for message in ds.messages_for(request):  # oldest first, so newer facts apply last
            content = messages.user_content(message)
            raw = self._call(self.message_cache, message.message_id, messages.PROMPT_VERSION + content,
                             messages.SYSTEM_PROMPT, lambda: content, messages.SCHEMA, "message")
            found += messages.to_amendments(messages.parse_facts(raw), message, request.request_date)
        return found

    def _call(self, cache: JsonCache, item_id: str, fingerprint: str, system: str, content_fn, schema: dict,
              purpose: str):
        key = f"{item_id}:{hashlib.sha256(fingerprint.encode()).hexdigest()[:16]}"
        cached = cache.get(key)
        if cached is not None and not self.refresh:
            self.usage.cache_hits += 1
            return cached
        if self.model is None:
            return None
        raw, call = self.model.extract(system, content_fn(), schema, purpose)
        self.usage.add(call)
        cache.put(key, raw)
        return raw
