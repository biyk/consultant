# -*- coding: utf-8 -*-
"""Живой прогон REST-контракта через HTTP (urllib). Печатает статусы/счётчики/длины,
без тел документов."""
import json
import urllib.request

BASE = "http://127.0.0.1:8000"


def call(method, path, body=None, timeout=180):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:  # noqa: BLE001
            return e.code, {"_raw": raw[:200]}
    except Exception as e:  # noqa: BLE001
        return -1, {"_err": str(e)}


def main():
    s, j = call("GET", "/health")
    print("GET /health ->", s, j.get("ok"))

    s, j = call("GET", "/state")
    print("GET /state ->", s, "busy.active=", (j.get("busy") or {}).get("active"),
          "tabs=", j.get("tabs"))

    s, j = call("POST", "/search", {"query": "гражданский кодекс",
                                    "page_size": 5, "fresh": True})
    print("POST /search ->", s, "total=", j.get("total"),
          "categories=", len(j.get("categories") or []),
          "docs=", len(j.get("docs") or []),
          "sel=", (j.get("selected_category") or "")[:30],
          "parsed/expected=", j.get("parsed_count"), j.get("expected_count"))
    docs = j.get("docs") or []
    for d in docs[:5]:
        print("   doc idx=%s abs=%s titlelen=%s" % (d.get("index"), d.get("abs"),
                                                    len(d.get("title") or "")))

    if docs:
        s, j = call("POST", "/doc", {"page": 1, "index": 0, "fresh": True})
        print("POST /doc ->", s, "kind=", j.get("title") and j.get("kind"),
              "titlelen=", len(j.get("title") or ""),
              "contentlen=", len(j.get("content") or ""))

    s, j = call("POST", "/page", {"page": 2})
    print("POST /page(2) ->", s, "docs=", len(j.get("docs") or []))

    s, j = call("POST", "/open", {"title": "гражданский кодекс", "fresh": True})
    print("POST /open ->", s, "kind=", j.get("kind"),
          "contentlen=", len(j.get("content") or ""))

    print("LIVE_TEST_DONE")


if __name__ == "__main__":
    main()
