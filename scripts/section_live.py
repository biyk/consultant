# -*- coding: utf-8 -*-
"""Живая проверка /section на реальном клиенте К+ (GUI держит сервер).

Семь сценариев, первые четыре со СВЕЖИМ /search (после /section читалка
уходит с выдачи, openable=False — поэтому выдачу каждый раз перезасеваем):
  a) позитив: берём реальный заголовок из available[] -> ok, отдаёт тело раздела;
  b) граница номера: want «Глава 1» НЕ должен вернуть «Глава 11 …»;
  c) nonexistent want («глава 999999»)   -> честный 400 unknown_section + available[];
  d) без want                            -> честный 400 want_required;
  e) анкоринг: available[] должен включать большинство пунктов toc (>=80%);
  f) /toc кэш: второй /toc по тому же title -> cached=true, GUI не дёргается;
  g) /section кэш: после прогрева content+toc -> /section полностью офлайн
     (cached=true, doc_age+toc_age есть).
В конце /health — убедиться, что GUI жив и не завис.

Запуск: venv\\Scripts\\python.exe scripts\\section_live.py
"""
import json
import re
import urllib.request

BASE = "http://127.0.0.1:8000"
QUERY = "КоАП РФ статья"


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").replace("\u00a0", " ")).strip().lower()


def call(path, body, timeout=240):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            return e.code, {}


def health():
    with urllib.request.urlopen(BASE + "/health", timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def seed_row():
    # после рестарта первое /search бывает холодным (tree_not_read) — повторяем.
    # берём ИМЕННО структурированный КоАП (с Раздел/Глава), а не справочную
    # информацию на первом месте выдачи — иначе /section честно вернёт no_toc.
    for _ in range(3):
        st, s = call("/search", {"query": QUERY, "page_size": 12, "fresh": True})
        docs = s.get("docs") or []
        for i, d in enumerate(docs):
            t = (d.get("title") or "").lower()
            if "административн" in t and "правонаруш" in t and "кодекс" in t:
                return i, d.get("title")
    return (None, None)


def main():
    idx, title = seed_row()
    print("seed row=%s  %r" % (idx, (title or "")[:60]))
    if idx is None:
        print("нет структурированного КоАП в выдаче — стоп"); return 2

    # a) позитивная выдача: берём реальный заголовок из available[] самого
    #    инструмента (значит он точно найден как заголовок в тексте)
    st, probe = call("/section", {"index": idx, "want": "zzz-нет-такой-главы"})
    avail = probe.get("available") or []
    print("\nreal headings (available)=%d, первые: %r" % (len(avail), avail[:3]))
    pick = next((a for a in avail if _norm(a).startswith("глава")),
                 avail[0] if avail else None)
    idx, _ = seed_row()
    st, j = call("/section", {"index": idx, "want": pick})
    sec = j.get("section") or {}
    a_ok = (st == 200 and j.get("ok") and (sec.get("text_len") or 0) > 50
            and _norm(sec.get("title")) == _norm(pick))
    print("a) позитив want=%r -> HTTP %s ok=%s title=%r text_len=%s"
          % (pick, st, j.get("ok"), sec.get("title"), sec.get("text_len")))
    print("   text[:150]=%r" % (sec.get("text") or "")[:150])

    # b) граница номера: «Глава 1» НЕ должна открыть «Глава 1<цифра> …»;
    #    допустимо — либо настоящая Глава 1, либо честный unknown_section
    idx, _ = seed_row()
    st, j = call("/section", {"index": idx, "want": "Глава 1"})
    sec = j.get("section") or {}
    t = _norm(sec.get("title")) if sec else ""
    greedy = bool(re.match(r"глава 1\d", t))                 # «глава 11/12…» = ошибка
    honest = bool(re.match(r"глава 1(\.|\s|$)", t)) or j.get("ok") is False
    b_ok = (not greedy) and honest
    print("\nb) want='Глава 1' -> HTTP %s ok=%s error=%s title=%r | greedy=%s b_ok=%s"
          % (st, j.get("ok"), j.get("error"), sec.get("title"), greedy, b_ok))

    # c) nonexistent -> честный unknown_section + список available
    idx, _ = seed_row()
    st, j = call("/section", {"index": idx, "want": "глава 999999"})
    avail2 = j.get("available") or []
    c_ok = st == 400 and j.get("error") == "unknown_section" and len(avail2) > 0
    print("\nc) nonexistent want -> HTTP %s error=%s available=%d"
          % (st, j.get("error"), len(avail2)))

    # d) без want -> 400 want_required (GUI не трогается)
    idx, _ = seed_row()
    st, j = call("/section", {"index": idx})
    d_ok = st == 400 and j.get("error") == "want_required"
    print("\nd) без want -> HTTP %s error=%s" % (st, j.get("error")))

    # e) глубина анкоринга: toc_found/toc_total обязан быть >= 80%
    #    (до фикса было 8/38=21%; после bidirectional-префикса 38/38=100%
    #    на реальном КоАП. Не ниже 80% — регресс).
    idx, _ = seed_row()
    st, j = call("/section", {"index": idx, "want": "zzz"})
    total = j.get("toc_total") or 0
    found = j.get("toc_found") or 0
    e_ok = bool(total) and (found / max(total, 1)) >= 0.80
    print("\ne) anchoring: toc_found=%s / toc_total=%s = %s%% (порог 80%%) -> e_ok=%s"
          % (found, total, round(100.0 * found / max(total, 1)), e_ok))

    # f) /toc кэш: warm-up холодным /search -> /toc кладёт entries в кэш,
    #    затем повтор /search (возвращает openable) и второй /toc обязан
    #    прийти cached=true, GUI не трогается, openable остаётся True.
    idx, _ = seed_row()
    st1, j1 = call("/toc", {"index": idx})
    if j1.get("cached"):
        # уже прогрето предыдущим прогоном — ок
        pass
    idx, _ = seed_row()
    st2, j2 = call("/toc", {"index": idx})
    f_ok = bool(j2.get("cached")) and j2.get("count", 0) == j1.get("count", 0)
    print("\nf) /toc кэш: 1st cached=%s count=%s; 2nd cached=%s count=%s -> f_ok=%s"
          % (j1.get("cached"), j1.get("count"),
             j2.get("cached"), j2.get("count"), f_ok))

    # g) /section тёплый путь: после /doc (прошлые прогоны) + /toc — cached=true
    #    и doc_age/toc_age заполнены
    idx, _ = seed_row()
    st3, j3 = call("/doc", {"index": idx})         # кладёт doc cache
    idx, _ = seed_row()
    st4, j4 = call("/toc", {"index": idx})         # кладёт toc cache
    idx, _ = seed_row()
    st5, j5 = call("/section", {"index": idx, "want": pick})
    g_ok = bool(j5.get("cached")) and j5.get("doc_age") is not None \
        and j5.get("toc_age") is not None
    print("\ng) /section кэш: cached=%s doc_age=%s toc_age=%s ok=%s -> g_ok=%s"
          % (j5.get("cached"), j5.get("doc_age"), j5.get("toc_age"),
             j5.get("ok"), g_ok))

    h = health()
    print("\n/health ok=%s window=%r tabs=%s" %
          (h.get("ok"), (h.get("gui") or {}).get("window"), (h.get("gui") or {}).get("tabs")))

    verdict = all([a_ok, b_ok, c_ok, d_ok, e_ok, f_ok, g_ok, bool(h.get("ok"))])
    print("\n=== ИТОГ: a=%s b=%s c=%s d=%s e=%s f=%s g=%s health=%s -> %s ===" %
          (a_ok, b_ok, c_ok, d_ok, e_ok, f_ok, g_ok, h.get("ok"),
           "PASS" if verdict else "FAIL"))
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
