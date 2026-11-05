# -*- coding: utf-8 -*-
"""Живая проверка /search?type= (алиас фильтра по виду материала).

Запуск: venv\\Scripts\\python.exe scripts\\type_check.py [запрос]
"""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
QUERY = sys.argv[1] if len(sys.argv) > 1 else "неустойка"


def post(path, body, timeout=200):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def show(label, body):
    st, j = post("/search", body)
    print("\n[%s] type=%r category=%r -> HTTP %s" %
          (label, body.get("type"), body.get("category"), st))
    if j.get("error"):
        print("   error=%s  allowed=%s" % (j.get("error"), j.get("allowed")))
        return
    print("   ok=%s requested_type=%r selected_category=%r section_count=%s total=%s" %
          (j.get("ok"), j.get("requested_type"), j.get("selected_category"),
           j.get("section_count"), j.get("total")))
    print("   parsed=%s empty_reason=%s scope_mismatch=%s selection_rule=%s" %
          (j.get("parsed_count"), j.get("empty_reason"),
           j.get("scope_mismatch"), j.get("selection_rule")))
    for d in (j.get("docs") or [])[:3]:
        print("     · %s" % (d.get("title") or "")[:72])


def main():
    for t in ("practice", "consult", "law"):
        show(t, {"query": QUERY, "type": t, "page_size": 3, "fresh": True})
    show("bad", {"query": QUERY, "type": "zzz"})
    show("conflict", {"query": QUERY, "type": "practice",
                      "category": "Комментарии законодательства"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
