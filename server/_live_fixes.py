# -*- coding: utf-8 -*-
"""Живая проверка закрытых issues (GUI). Печатает только статусы/счётчики/ключи, без тел."""
import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"


def call(path, body, timeout=200):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:  # noqa: BLE001
            return e.code, {"_raw": raw[:150]}
    except Exception as e:  # noqa: BLE001
        return -1, {"_err": str(e)}


def main():
    passed, failed = [], []

    def check(name, cond, extra=""):
        (passed if cond else failed).append(name)
        print(("  OK   " if cond else "  FAIL ") + name + (" " + extra if extra else ""))

    # 1) search базовый: взять leaf-имя из выданных categories
    s, j = call("/search", {"query": "гражданский кодекс", "page_size": 5, "fresh": True})
    cats = j.get("categories") or []
    leaves = [c["name"] for c in cats if c.get("leaf") and c.get("count")]
    print("1) search:", s, "categories=", len(cats), "leaves=", len(leaves))
    check("search ok + categories не пустой", s == 200 and len(cats) > 0)

    # 2) BLOCKER 47ac: точное имя из categories[] принимается (не 400)
    if leaves:
        s2, j2 = call("/search", {"query": "гражданский кодекс",
                                  "category": leaves[0], "page_size": 5, "fresh": True})
        print("2) search с category=%r ->" % leaves[0], s2, "sel=", j2.get("selected_category"))
        check("47ac category из categories[] принята", s2 == 200 and
              j2.get("selected_category") is not None)

    # 3) 400 unknown_category → categories[] НЕ пустой (issue 47ac вторая часть)
    s3, j3 = call("/search", {"query": "гражданский кодекс",
                              "category": "СОВСЕМ_НЕТ_ТАКОГО_РАЗДЕЛА", "fresh": True})
    n_cat_err = len(j3.get("categories") or [])
    print("3) bad category ->", s3, "categories_in_body=", n_cat_err)
    check("47ac 400 несёт непустой categories[]", s3 == 400 and n_cat_err > 0)

    # 4) нет stale-протечки (df48/f501): мусор-запрос не должен вернуть старый total
    s4, j4 = call("/search", {"query": "qqzzxxjjjvvalkwwnn0zzz", "fresh": True})
    print("4) garbage ->", s4, "total=", j4.get("total"), "empty_reason=", j4.get("empty_reason"))
    check("df48 garbage не протекает (total=0/no_matches)",
          s4 == 200 and (j4.get("total") == 0 or j4.get("empty_reason") == "no_matches"))

    # 5) /doc links несут href/label (62ca); kind/entries для collection
    #    ВАЖНО: шаг 4 (garbage) очистил сессию — это и есть фикс anti-stale.
    #    Поэтому ПЕРЕ-СЕВАЕМ реальный поиск, чтобы /doc был над чем.
    sR, jR = call("/search", {"query": "гражданский кодекс",
                              "page_size": 5, "fresh": True})
    title = (jR.get("docs") or [{}])[0].get("title")
    s5, j5 = call("/doc", {"page": 1, "index": 0, "fresh": True})
    links = j5.get("links") or []
    has_fields = all(("href" in l and "label" in l) for l in links) if links else False
    print("5) /doc ->", s5, "kind=", j5.get("kind"), "content_len=", j5.get("content_len"),
          "links=", len(links), "href/label есть=", has_fields)
    check("62ca links[] со href+label", has_fields)
    check("doc kind не None и ok==True при нормальном экспорте",
          j5.get("kind") in ("document", "collection") and j5.get("ok") is True)

    # 6) /open по реальному заголовку выдаёт содержательный текст (4ca)
    s6, j6 = call("/open", {"title": title})
    print("6) /open title=... ->", s6, "kind=", j6.get("kind"),
          "content_len=", j6.get("content_len"), "matched_abs=", j6.get("matched_abs"))
    check("4ca /open вернул содержательный content_len>200",
          s6 == 200 and (j6.get("content_len") or 0) > 200)

    print("\nPASSED=%d FAILED=%d" % (len(passed), len(failed)))
    if failed:
        print("FAILED:", failed)
    print("LIVE_FIXES_DONE")


if __name__ == "__main__":
    main()
