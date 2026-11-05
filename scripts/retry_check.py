# -*- coding: utf-8 -*-
"""Повторяемый ли поиск после list_not_rendered? (проверка retryable=true)"""
import ctypes
import json
import urllib.error
import urllib.request

try:  # не отъедаем CPU у пользователя
    _k = ctypes.windll.kernel32
    _k.SetPriorityClass(_k.GetCurrentProcess(), 0x00004000)  # BELOW_NORMAL
except Exception:  # noqa: BLE001
    pass

BASE = "http://127.0.0.1:8000"
OUT = r"D:\ConsPlus\logs\retry_check.txt"
lines = []


def post(path, body):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    r = urllib.request.Request(BASE + path, data=data,
                               headers={"Content-Type": "application/json"},
                               method="POST")
    try:
        with urllib.request.urlopen(r, timeout=200) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", "replace"))


def brief(j):
    keys = ("ok", "error", "empty_reason", "total", "total_source", "parsed_count",
            "selected_category", "selection_rule", "section_count", "rows_identical",
            "stale_suspect", "tree_reads", "note")
    d = {k: j.get(k) for k in keys if k in j}
    d["titles"] = [(x.get("title") or "")[:60] for x in (j.get("docs") or [])][:5]
    return d


cases = [
    ("повтор того же запроса", {"query": "обзор судебной практики верховный суд",
                                 "page_size": 3, "fresh": True}),
    ("тот же запрос, раздел Судебная практика",
     {"query": "обзор судебной практики верховный суд",
      "category": "Судебная практика", "page_size": 3, "fresh": True}),
    ("покороче", {"query": "обзор практики", "page_size": 3, "fresh": True}),
]

for name, body in cases:
    st, j = post("/search", body)
    lines.append("### %s  body=%s -> HTTP %s" % (name, json.dumps(body, ensure_ascii=False), st))
    lines.append(json.dumps(brief(j), ensure_ascii=False, indent=1))
    print("%-50s ok=%s %s" % (name, j.get("ok"), j.get("error")))

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print("->", OUT)
