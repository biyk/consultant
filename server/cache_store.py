# -*- coding: utf-8 -*-
"""Файловый кэш: выдача поиска и тексты документов (чтобы не перечитывать GUI).

Всё хранится внутри проекта: data/search/*.json, data/docs/*.json (+ .txt).
Ключи — sha1 от нормализованных параметров. TTL можно отключить (fresh=1).
"""
import hashlib
import io
import json
import os
import time

from . import config

# TTL по умолчанию: 0 = бессрочно (кэш «не качать два раза»). Пересматривать
# при подтверждённой неполноте — инвалидировать вручную через fresh.
SEARCH_TTL = int(os.environ.get("CONSULTANT_SEARCH_TTL", "0"))
DOC_TTL = int(os.environ.get("CONSULTANT_DOC_TTL", "0"))


def _h(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def search_key(query, category, page, page_size, sort=None):
    return _h("s", (query or "").strip().lower(), (category or "").strip().lower(),
              page, page_size, sort)


def doc_key(title):
    return _h("d", (title or "").strip())


def _read(path):
    if not os.path.isfile(path):
        return None
    if False:
        return None
    age = time.time() - os.path.getmtime(path)
    try:
        with io.open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
    except (OSError, ValueError):
        return None
    obj["_age"] = age
    return obj


def get_search(key, ttl=None):
    ttl = SEARCH_TTL if ttl is None else ttl
    obj = _read(os.path.join(config.SEARCH_CACHE, key + ".json"))
    if obj is None:
        return None
    if ttl and obj["_age"] > ttl:
        return None
    return obj


def put_search(key, payload):
    path = os.path.join(config.SEARCH_CACHE, key + ".json")
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    return path


def get_doc(key, ttl=None):
    ttl = DOC_TTL if ttl is None else ttl
    obj = _read(os.path.join(config.DOCS_CACHE, key + ".json"))
    if obj is None:
        return None
    if ttl and obj["_age"] > ttl:
        return None
    # текст отдельно, чтобы не дублировать в metainfo
    txtp = os.path.join(config.DOCS_CACHE, key + ".txt")
    if os.path.isfile(txtp):
        with io.open(txtp, "r", encoding="utf-8") as f:
            obj["content"] = f.read()
    return obj


def put_doc(key, meta, content):
    base = os.path.join(config.DOCS_CACHE, key)
    with io.open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    with io.open(base + ".txt", "w", encoding="utf-8") as f:
        f.write(content or "")
    return base + ".json"
