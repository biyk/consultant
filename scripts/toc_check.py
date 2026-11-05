# -*- coding: utf-8 -*-
"""Живая проверка /toc: поиск крупного кодекса -> открыть строку -> оглавление.

Только HTTP к локальному серверу (GUI держит сервер; в это время других
запросов не слать). Запуск: venv\\Scripts\\python.exe scripts\\toc_check.py [запрос]
"""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000"
QUERY = sys.argv[1] if len(sys.argv) > 1 else "кодекс"


def post(path, body, timeout=180):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    s = post("/search", {"query": QUERY, "page_size": 3, "fresh": True})
    print("/search ok=%s total=%s parsed=%s category=%r" %
          (s.get("ok"), s.get("total"), s.get("parsed_count"), s.get("category")))
    docs = s.get("docs") or []
    if not docs:
        print("нет docs — стоп"); return 1
    row = docs[0]
    print("row0: index=%s abs=%s title=%r" % (row.get("index"), row.get("abs"),
                                              (row.get("title") or "")[:70]))
    t = post("/toc", {"index": 0})
    print("/toc ok=%s count=%s has_toc=%s matched=%r msg=%r" %
          (t.get("ok"), t.get("count"), t.get("has_toc"),
           (t.get("matched_title") or "")[:50], t.get("message")))
    for e in (t.get("toc") or [])[:12]:
        print("   lvl=%s  %s" % (e.get("level"), (e.get("title") or "")[:78]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
