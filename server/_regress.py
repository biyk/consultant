# -*- coding: utf-8 -*-
"""Regression-границы на живом сервере. Печатает статусы/счётчики/empty_reason/hint.
Без тел документов."""
import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"


def call(method, path, body=None, timeout=180):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:  # noqa: BLE001
            return e.code, {"_raw": raw[:200]}
    except Exception as e:  # noqa: BLE001
        return -1, {"_err": str(e)}


def show(tag, s, j, keys):
    parts = [f"{k}={j.get(k)}" for k in keys if k in j]
    print(f"[{tag}] HTTP {s} " + " ".join(parts))


def main():
    # 1) пустой query -> 400 empty_query
    s, j = call("POST", "/search", {"query": "   "})
    show("empty_query", s, j, ["ok", "error"])

    # 2) несуществующая category -> 400 unknown_category + categories + hint
    s, j = call("POST", "/search", {"query": "гражданский кодекс",
                                    "category": "НЕСУЩЕСТВЕННЫЙ_РАЗДЕЛ_XX",
                                    "page_size": 5, "fresh": True})
    show("unknown_category", s, j, ["ok", "error", "hint"])
    print("     categories_in_400 =", len(j.get("categories") or []))

    # 3) мусорный запрос (нет совпадений) -> total=0 + empty_reason
    s, j = call("POST", "/search", {"query": "qqzzxxjjjvvalkwwnn0x",
                                    "page_size": 5, "fresh": True})
    show("no_matches", s, j, ["ok", "total", "empty_reason", "parsed_count",
                              "expected_count", "truncated"])

    # 4) дефисная форма номера дела -> total=0 + note
    s, j = call("POST", "/search", {"query": "А-55/2024-1", "page_size": 5, "fresh": True})
    show("hyphen_case", s, j, ["ok", "total", "empty_reason", "note"])

    # 5) category="Судебная практика" -> selected_category непустой
    s, j = call("POST", "/search", {"query": "гражданский кодекс",
                                    "category": "Судебная практика",
                                    "page_size": 5, "fresh": True})
    show("cat_sud", s, j, ["ok", "total", "selected_category", "parsed_count",
                           "expected_count"])
    print("     docs =", len(j.get("docs") or []))

    # 6) целостность: len(docs)==min(total,page_size), parsed==expected
    s, j = call("POST", "/search", {"query": "договор", "page_size": 10, "fresh": True})
    total = j.get("total") or 0
    docs = j.get("docs") or []
    print(f"[integrity] HTTP {s} total={total} len(docs)={len(docs)} "
          f"parsed={j.get('parsed_count')} expected={j.get('expected_count')} "
          f"pages={j.get('pages')} truncated={j.get('truncated')}")
    print("REGRESS_DONE")


if __name__ == "__main__":
    main()
