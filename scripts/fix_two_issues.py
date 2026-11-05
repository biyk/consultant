# -*- coding: utf-8 -*-
"""Закрыть две заявки живыми фактами. PATCH /issues/<id> {status, note}.
ASCII-имя файла; текст — русский, уходит как JSON utf-8 (ensure_ascii=False не
нужен: urllib сам кодирует)."""
import io
import json
import sys
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8000"

NOTE_E7 = (
    "Корень найден живым зондом (server/probe_results_uia.py, режимы titles/grid): "
    "в нижней строке состояния К+ ДВА парных счётчика — «Док. N» «/total» (индекс и "
    "ОБЪЁМ СПИСКА раздела, напр. 3/1588) и «Абз. K» «/L» (абзац и объём ВСЕГО "
    "результата, напр. 2668/10061). Старый _doc_position() брал total из ПОСЛЕДНЕГО "
    "«/число» → читал объём абзацев вместо объёма списка; отсюда все «чужие» числа "
    "(1868/4621/10061 против 1588/817). Переписан: «Док.» сопоставляется с ближайшим "
    "«/total» геометрически (стоп на «Абз.»). Второй дефект того же симптома: "
    "_doc_title() отбрасывал как «эхо» ЛЮБОЙ заголовок, СОДЕРЖАЩИЙ слова запроса, "
    "поэтому легальный документ («Справочная информация: \u00abКлючевая ставка и "
    "процентная ставка\u2026\u00bb при запросе \u00abставка\u00bb») терялся и возвращалась "
    "полоса раздела «Российское законодательство (Версия Проф)»; теперь гасится "
    "только ВЕРБАТИМ-эхо. Живая проверка (logs/live_check.txt 9/9 PASS и "
    "scripts/scope_check.py): /search \u00abключевая ставка\u00bb \u2192 total=1588 == "
    "section_count, полные 5 реальных строк, truncated=false, enum_attempts=1; "
    "\u00abобзор судебной практики верховный суд\u00bb \u2192 total=817 == section_count, "
    "5 реальных строк. Юнит-тесты: 95/95 (TestDocPosition, TestListScopeMismatch)."
)

NOTE_E15 = (
    "Открытие строки больше не «вслепую»: open_first_doc() сначала зовёт "
    "ensure_list_page() (уход из залипшей читалки кнопкой «Назад»), затем кликает и "
    "возвращает True ТОЛЬКО если «Док.N/total» реально изменился; иначе честный "
    "False \u2192 enumerate_titles() отдаёт [] и никогда не выдаёт чужой список. "
    "Добавлен контроль объёма: enumerate_titles(expect_total=\u2026) и шлюз "
    "list_scope_mismatch в /search (поле scope_mismatch), если открытый список не "
    "равен объёму раздела. Порядок точек проверен живым зондом: на этой сборке "
    "первая строка результата лежит в полосе «Наиболее соответствуют запросу» "
    "(~900,300), а pane-область списка начинается НИЖЕ (top\u2248339) и клики по её "
    "отступам открывают не тот подсписок \u2014 поэтому доказанная точка идёт первой, "
    "pane-точки запасными (гарантия не в порядке, а в проверке «Док.N»). Лог: "
    "dbl-click (900,300) \u2192 pos=1/1588 за один клик (раньше 4 холостых клика). "
    "Юнит-тесты: TestGuiOpenFirstDoc."
)

PATCHES = [
    ("e7f7bb098cfd", NOTE_E7),
    ("e15c0d424393", NOTE_E15),
]


def patch(iid, note):
    body = json.dumps({"status": "fixed", "note": note}).encode("utf-8")
    req = urllib.request.Request(BASE + "/issues/" + iid, data=body,
                                 method="PATCH",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            j = json.loads(r.read().decode("utf-8"))
            st = r.status
    except urllib.error.HTTPError as e:
        j = json.loads(e.read().decode("utf-8"))
        st = e.code
    iss = j.get("issue") or {}
    print("=== PATCH %s -> HTTP %s ===" % (iid, st))
    print("  ok=%s status=%r resolution_note_set=%s"
          % (j.get("ok"), iss.get("status"), bool(iss.get("resolution_note"))))
    hist = iss.get("history") or []
    if hist:
        print("  last_history=%r" % (hist[-1],))
    return j.get("ok")


def main():
    ok_all = True
    for iid, note in PATCHES:
        ok_all = bool(patch(iid, note)) and ok_all
    # сверка GET
    with urllib.request.urlopen(BASE + "/issues?status=open", timeout=30) as r:
        j = json.loads(r.read().decode("utf-8"))
    print("\n=== GET /issues?status=open ===")
    print("  open_total=%s by_status=%r" % (j.get("open_total"), j.get("by_status")))
    left = [i["id"] for i in j.get("issues", [])
            if i["id"] in dict(PATCHES)]
    print("  наши заявки всё ещё открыты: %r" % (left,))
    return 0 if ok_all and not left else 1


if __name__ == "__main__":
    sys.exit(main())
