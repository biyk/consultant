# -*- coding: utf-8 -*-
"""Офлайн-проверка осуществимости извлечения подразделов по оглавлению.

Смысл (продолжение §13.4 п.1/п.5, без рискованной GUI-навигации): можно ли
привязать пункты /toc к кускам уже экспортированного текста /doc и резать
документ на секции чистым матчингом? Для реального структурированного документа
снимаем content (/doc) и toc (/toc) и меряем, сколько заголовков оглавления
встречаются в тексте — по нескольким стратегиям.

Запуск (GUI держит сервер; других запросов в это время не слать):
    venv\\Scripts\\python.exe scripts\\section_probe.py ["запрос"]
"""
import json
import re
import sys
import urllib.request

BASE = "http://127.0.0.1:8000"
QUERY = sys.argv[1] if len(sys.argv) > 1 else "КоАП РФ статья"


def post(path, body, timeout=200):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def norm(s):
    s = (s or "").replace("\u00a0", " ").replace("\u2116", "N")
    s = s.lower().replace("\u0441.", "с.").replace("\t", " ")
    return re.sub(r"\s+", " ", s).strip()


def leading_token(title):
    """Первый «номерной» токен: 12.1 / 156 / глава 3 / статья 12 — по началу."""
    t = norm(title)
    m = re.match(r"^((?:раздел|глава|статья|параграф|§)?\s*\d[\d.\-]*(?:\s*\d+)*)", t)
    return m.group(1).strip() if m else t[:16]


def main():
    s = post("/search", {"query": QUERY, "page_size": 5, "fresh": True})
    docs = s.get("docs") or []
    if not docs:
        print("нет docs (error=%s empty_reason=%s)" % (s.get("error"), s.get("empty_reason")))
        return 1
    # взять самую «кодексовидную» строку
    row = None
    for i, d in enumerate(docs):
        t = norm(d.get("title"))
        if "кодекс" in t or "коап" in t or "гк рф" in t or "ск рф" in t:
            row = (i, d); break
    if row is None:
        row = (0, docs[0])
    idx = row[0]
    print("row %d: %r  abs=%s" % (idx, (row[1].get("title") or "")[:70], row[1].get("abs")))

    d = post("/doc", {"index": idx, "fresh": True})
    content = d.get("content") or ""
    print("/doc ok=%s kind=%s content_len=%d" % (d.get("ok"), d.get("kind"), len(content)))
    if len(content) < 200:
        print("текст слишком короткий — стоп"); return 3

    # /toc ИДЁТ ПОСЛЕ /doc: /toc в конце ставит openable=False (читалка ушла
    # с списка), поэтому /doc после /toc честно упал бы 400 list_not_active.
    t = post("/toc", {"index": idx})
    toc = t.get("toc") or []
    print("/toc ok=%s count=%s has_toc=%s" % (t.get("ok"), t.get("count"), t.get("has_toc")))
    if not toc:
        print("оглавления нет — стоп"); return 2

    ncontent = norm(content)
    # строки текста как они есть (для матчинга по началу строки)
    lines_norm = [norm(ln) for ln in content.splitlines() if ln.strip()]

    full = lead = 0
    miss_examples = []
    for e in toc:
        title = e.get("title") or ""
        nt = norm(title)
        hit_full = nt in ncontent
        tok = leading_token(title)
        hit_lead = bool(tok) and any(ln.startswith(tok) for ln in lines_norm)
        if hit_full:
            full += 1
        if hit_lead:
            lead += 1
        if not (hit_full or hit_lead) and len(miss_examples) < 8:
            miss_examples.append(title)

    n = len(toc)
    print("\n=== совпадения toc→text (n=%d) ===" % n)
    print("  точный заголовок подстрокой текста : %d/%d (%.0f%%)" % (full, n, 100.0*full/n))
    print("  начал строкой по номеру-токену     : %d/%d (%.0f%%)" % (lead, n, 100.0*lead/n))
    print("\nпервые toc-пункты:")
    for e in toc[:10]:
        print("   lvl=%s  %r" % (e.get("level"), (e.get("title") or "")[:70]))
    if miss_examples:
        print("\nпримеры НЕ найденных заголовков:")
        for m in miss_examples:
            print("   - %r" % m[:80])

    # сколько toc-пунктов вообще «нумерованные заголовки» vs служебные
    print("\nпервые 200 симв. контента: %r" % content[:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
