# -*- coding: utf-8 -*-
"""Сколько документов показывал раздел для шага 2 живой проверки?
Сверяем section_count (из дерева) с total (из читалки) на КЭШЕ — без GUI."""
import io
import json
import sys
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

BASE = "http://127.0.0.1:8000"


def post(path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def show(tag, q, extra=None):
    body = {"query": q, "page": 1, "page_size": 5}
    body.update(extra or {})
    st, j = post("/search", body)
    print("\n=== %s | query=%r | HTTP %s | cached=%s ===" % (tag, q, st,
                                                             j.get("cached")))
    for k in ("ok", "empty_reason", "error", "selected_category", "section_count",
              "total", "total_source", "parsed_count", "expected_count",
              "truncated", "enum_attempts", "note"):
        print("  %-16s %r" % (k, j.get(k)))
    print("  sections         %r" % (j.get("sections"),))
    for d in (j.get("docs") or []):
        print("    ref=%-7s title=%r" % (d.get("ref"), (d.get("title") or "")[:70]))
    return j


if __name__ == "__main__":
    out = []
    for tag, q in (("шаг 2 (живой прогон)", "ключевая ставка"),
                   ("шаг 5 (длинный запрос)", "обзор судебной практики верховный суд")):
        try:
            out.append(show(tag, q))
        except Exception as exc:  # noqa: BLE001
            print("  ! %r" % exc)
    json.dump(out, io.open("logs/_scope_check.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
