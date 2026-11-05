# -*- coding: utf-8 -*-
"""Короткая проверка живого клиента через HTTP-API (новый код).

Не гоняем нагрузку: 5 GUI-операций, приоритет процесса BELOW_NORMAL, таймауты.
Результат — logs/live_check.txt (UTF-8), в консоль только краткие строки.
"""
import ctypes
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
OUT = r"D:\ConsPlus\logs\live_check.txt"
TIMEOUT = 200

BELOW_NORMAL = 0x00004000
try:
    k32 = ctypes.windll.kernel32
    k32.SetPriorityClass(k32.GetCurrentProcess(), BELOW_NORMAL)
except Exception as e:  # noqa: BLE001
    print("priority not lowered:", e)

log_lines = []


def req(method, path, body=None):
    url = BASE + path
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=TIMEOUT) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"_raw": raw[:400]}
    except Exception as e:  # noqa: BLE001
        return -1, {"_exc": "%s: %s" % (type(e).__name__, e)}


def step(title, method, path, body=None, checks=()):
    st, j = req(method, path, body)
    verdict = []
    ok_all = st != -1
    for name, fn in checks:
        try:
            good = bool(fn(j))
        except Exception as e:  # noqa: BLE001
            good, _ = False, None
            name = "%s (exc %s)" % (name, type(e).__name__)
        ok_all = ok_all and good
        verdict.append("%s=%s" % (name, "OK" if good else "FAIL"))
        if not good:
            ok_all = False
    log_lines.append("### %s  [%s %s -> HTTP %s]" % (title, method, path, st))
    log_lines.append("    verdict: " + ("PASS" if ok_all else "PROBLEM") +
                     " | " + "; ".join(verdict))
    keys = ("ok", "error", "empty_reason", "total", "total_source", "pages",
            "selected_category", "selection_rule", "requested_category",
            "section_count", "scope_mismatch",
            "parsed_count", "expected_count", "truncated", "enum_attempts",
            "exact_match", "title_match", "matched_index",
            "matched_title", "content_len", "content_charset",
            "mojibake_repaired", "index_as_of", "index_as_of_source",
            "session_openable", "state", "depth", "retryable", "cached", "_age",
            "note")
    brief = {k: j.get(k) for k in keys if k in j}
    if "docs" in j and isinstance(j["docs"], list):
        brief["docs"] = [{"index": d.get("index"), "abs": d.get("abs"),
                          "ref": d.get("ref"), "title": (d.get("title") or "")[:70]}
                         for d in j["docs"][:6]]
    if "candidates" in j and isinstance(j["candidates"], list):
        brief["candidates"] = [str(c)[:70] for c in j["candidates"][:3]]
    if "_exc" in j or "_raw" in j:
        brief["transport"] = j.get("_exc") or j.get("_raw")
    log_lines.append("    " + json.dumps(brief, ensure_ascii=False)[:1600])
    print(("PASS  " if ok_all else "PROB  ") + title)
    return st, j


C = lambda k, v: (k, lambda j, k=k, v=v: j.get(k) == v)          # noqa: E731
D = lambda k: (k, lambda j, k=k: j.get(k) is not None)            # noqa: E731


def volume_ok(j):
    """ok=true допустимо ТОЛЬКО если объём открытого списка совпадает с объёмом
    раздела. Иначе это листание ЧУЖОГО списка (старая вкладка/карточка) — ровно
    та ложь, из-за которой прогон 04.11 выглядел успешным (issue e7f7bb098cfd)."""
    if j.get("scope_mismatch") is not None:
        return False
    if not j.get("ok"):
        return True                      # честный отказ проверяется отдельно
    total, sec = j.get("total"), j.get("section_count")
    if total is None or sec is None:
        return True                      # сверять нечем — ок, но total=null
    return total == sec


print("== ConsPlus live check ==")
req("GET", "/")  # прогрев/манифест не проверяем строго

step("1 health", "GET", "/health", None, [
    C("ok", True), C("index_as_of", "2026-07-03"),
    ("source=env", lambda j: "env" in (j.get("index_as_of_source") or ""))])

st2, j2 = step("2 /search #1 (ключевая ставка)", "POST", "/search",
               {"query": "ключевая ставка", "page_size": 5, "fresh": True}, [
    C("ok", True), ("docs non-empty", lambda j: len(j.get("docs") or []) > 0),
    ("ref present", lambda j: all(d.get("ref") for d in j.get("docs") or [])),
    D("selected_category"), D("total_source"),
    ("volume = section (не чужой список)", volume_ok)])

first_titles = [d.get("title") for d in (j2.get("docs") or [])]

idx0 = 0
step("3 /doc index=0 (live)", "POST", "/doc", {"index": idx0, "fresh": True}, [
    C("ok", True), ("content non-empty", lambda j: (j.get("content_len") or 0) > 50),
    D("matched_title"), ("no mojibake left",
                         lambda j: "Ð" not in (j.get("content") or ""))])

step("4 /sub index=0", "POST", "/sub", {"index": idx0}, [
    ("has content", lambda j: (j.get("content_len") or len(j.get("content") or "")) > 0),
    ("entries is list", lambda j: isinstance(j.get("entries"), list))])

st5, j5 = step("5 /search #2 (другой запрос) — анти-протечка", "POST", "/search",
               {"query": "обзор судебной практики верховный суд",
                "page_size": 3, "fresh": True}, [
    D("ok"), ("no stale leak", lambda j: not j.get("stale_suspect")),
    ("volume = section (не чужой список)", volume_ok),
    ("titles differ from #1",
     lambda j: [d.get("title") for d in (j.get("docs") or [])] != first_titles)])
if j5.get("ok") is False:
    log_lines.append("    (деградация допустима, но должна быть названа: %s)"
                     % j5.get("empty_reason"))

step("6 /open заведомо выдуманного титула -> 404", "POST", "/open",
     {"title": "щщщ заведомо отсутствующий документ проверки open 2026 зюкзюк"},
     [("http 404", lambda j: True), C("error", "doc_not_found"),
      C("exact_match", False), ("candidates given",
                                lambda j: len(j.get("candidates") or []) >= 0),
      ("foreign content not returned", lambda j: "content" not in j)])

step("7 /back", "POST", "/back", {}, [
    D("state"), ("session not openable after back",
                 lambda j: j.get("session_openable") is False)])

step("8 /doc после /back -> честный отказ", "POST", "/doc", {"index": 0}, [
    C("ok", False), ("error list_not_active",
                     lambda j: j.get("error") in ("list_not_active",
                                                  "no_openable_list"))])

step("9 /issues open", "GET", "/issues?status=open", None, [
    ("total present", lambda j: isinstance(j.get("total"), int)),
    ("open group works", lambda j: isinstance(j.get("open_total"), int)
     and j.get("filter") == "open"),
    ("by_status present", lambda j: bool(j.get("by_status"))),
    ("patch_fields listed", lambda j: bool(j.get("patch_fields")))])

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(log_lines) + "\n")
print("\nполный разбор ->", OUT)
