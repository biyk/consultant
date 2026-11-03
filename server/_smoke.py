# -*- coding: utf-8 -*-
"""Ручной smoke-тест живых эндпоинтов (UTF-8, без искажений PowerShell).
Печатает только счётчики/заголовки и длины — тела документов в консоль не льём.
"""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"


def post(path, obj, timeout=180):
    data = json.dumps(obj).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return 0, {"error": repr(e)}


def main():
    q = sys.argv[1] if len(sys.argv) > 1 else "гражданский кодекс"
    ps = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    code, j = post("/search", {"query": q, "page_size": ps, "fresh": True})
    print("SEARCH HTTP", code)
    if code != 200:
        print(json.dumps(j, ensure_ascii=False)[:800])
        return
    print("total=%s pages=%s sel=%s parsed=%s docs=%s cats=%s empty=%s" % (
        j.get("total"), j.get("pages"), j.get("selected_category"),
        j.get("parsed_count"), len(j.get("docs", [])), len(j.get("categories", [])),
        j.get("empty_reason")))
    print("--- categories ---")
    for c in j.get("categories", []):
        print(f"  {c['name']} :: raw={c['raw_count']!r} count={c['count']} leaf={c['leaf']}")
    print("--- docs (index/abs/titlelen/head40) ---")
    for d in j.get("docs", []):
        t = d.get("title", "")
        print(f"  {d['index']} abs={d['abs']} len={len(t)} head={t[:40]!r}")


if __name__ == "__main__":
    main()
