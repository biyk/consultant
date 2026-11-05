# -*- coding: utf-8 -*-
"""Закрытие трекера: POST новых заявок + PATCH status=fixed с resolution_note.

Не трогает GUI, только HTTP на 127.0.0.1:8000. Приоритет процесса — BELOW_NORMAL
(пользователь жаловался на 12 ядер под 100%).

    venv\\Scripts\\python.exe scripts\\close_issues.py
"""
import ctypes
import json
import urllib.error
import urllib.request

ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(),
                                        0x00004000)  # BELOW_NORMAL_PRIORITY_CLASS

BASE = "http://127.0.0.1:8000"
OUT = r"D:\ConsPlus\logs\close_issues.txt"
_report = []


def w(line):
    _report.append(line)


def call(method, path, body=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"raw": raw[:400]}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": "%s: %s" % (type(e).__name__, e)}


# ---------------------------------------------------------------- новые заявки
# Всё, что вскрыл живой прогон и не починено на корню, идёт отдельной заявкой,
# а не затирается формулировкой «готово».
NEW_ISSUES = [
    {
        "title": "/search: в больших разделах список выдачи читается частично "
                 "(1 строка из 5) либо не читается вовсе — при честном окладе "
                 "truncated/list_not_rendered",
        "endpoint": "/search",
        "severity": "normal",
        "description":
            "Разделы с длинными заголовками строк (Российское законодательство "
            "817 док., Судебная практика 17732 док.) enumerate_titles() перечисляет "
            "лишь частично: page_size=5 → прочитана 1 строка, page_size=3 → 0 строк "
            "за 2 попытки. Ответ теперь честный (truncated=true с note, либо "
            "ok=false empty_reason=list_not_rendered + section_count), но навигация "
            "по-прежнему не даёт полный список — это ограничение UI-Automation "
            "списка К+, а не логика API.",
        "steps": [
            "POST /search {\"query\": \"ключевая ставка\", \"page_size\": 5}",
            "POST /search {\"query\": \"обзор судебной практики верховный суд\", "
            "\"page_size\": 3}",
        ],
        "expected": "docs[] содержит page_size строк либо /search внятно ретраится "
                    "до полного списка",
        "actual": "parsed_count=1 из expected_count=5 (truncated=true); "
                  "parsed_count=0 из 3 при section_count=817 (list_not_rendered)",
        "reporter": "агент (живой прогон logs/live_check.txt, scripts/retry_check.py)",
    },
    {
        "title": "consultant_gui.open_first_doc(): клик «в слепую» по координатам "
                 "(900,300) — при перемещённом/свёрнутом окне открывает не тот "
                 "объект",
        "endpoint": "/doc",
        "severity": "normal",
        "description":
            "Открытие первой строки списка выполнено двойным кликом по фиксированному "
            "экранному прямоугольнику, а не по найденному элементу списка. Если окно "
            "К+ сдвинуто, развёрнуто на другом масштабе или список короче — клик "
            "приходится в пустоту/чужую область; далее export_current_doc() выгружает "
            "то, что открылось, и контроль title_match может это поймать, но сам "
            "метод навигации не надёжен.",
        "steps": [
            "сдвинуть окно КонсультантПлюс / изменить масштаб Windows на 150%",
            "POST /search {\"query\": \"договор\", \"fresh\": 1}",
            "POST /doc {\"index\": 0, \"fresh\": 1}",
        ],
        "expected": "строка списка открывается по элементу UIA (invoke/selection), "
                    "не по экранным координатам",
        "actual": "double-click в (900,300)",
        "reporter": "агент (разбор server/consultant_gui.py при волне 13)",
    },
]

new_ids = {}
for it in NEW_ISSUES:
    st, j = call("POST", "/issues", it)
    iid = j.get("id") or "?"
    new_ids[it["title"][:24]] = iid
    w("NEW  %-12s http=%s  %s" % (iid, st, it["title"][:88]))
    if st != 202:
        w("     !! %s" % json.dumps(j, ensure_ascii=False)[:300])

PARTIAL = new_ids.get(NEW_ISSUES[0]["title"][:24], "?")
BLIND = new_ids.get(NEW_ISSUES[1]["title"][:24], "?")

# ------------------------------------------------------------ notes к 22 заявкам
NOTES = {
    # --- трекер / служебное ---
    "03a15aee3896":
        "PATCH /issues/<id>: description вошёл в _ISSUE_MUTABLE (правится), "
        "неизвестное поле -> 400 unknown_field со списком allowed вместо молчаливого "
        "200 «ничего не сделал». PATCH /issues без id -> 405 с JSON id_required + "
        "allowed_fields. Ключ note развязан: пишется в resolution_note и в "
        "history{from,to,note,ts}. Манифест GET / перечисляет поля. Проверено "
        "тестами TestIssues и живым закрытием этого трекера (22 PATCH-а этим "
        "эндпоинтом).",

    "3f6dd95f968b":
        "Операторское значение задано в run_server.bat: "
        "SET CONSULTANT_INDEX_AS_OF=2026-07-03. /health отдаёт "
        "index_as_of=2026-07-03, index_as_of_source='env CONSULTANT_INDEX_AS_OF', "
        "index_as_of_confidence='operator', index_incomplete=false. Auto-detect по "
        "штампам «ред. от / с изм. от» оставлен как fallback, когда env нет. "
        "Первопричина «env не применялся» разобрана в e47ded1737cb.",

    "975f6227e620":
        "Учёт факта: вывод больше не строится на «пусто = не обновлено». Приоритет "
        "источника: env (confidence=operator) -> auto-detect по штампам дат из "
        "заголовков/текстов (confidence=observed, доказательства в "
        "state['index_observed'].evidence) -> unknown c "
        "index_as_of_source='not set'. Срез базы зафиксирован оператором как "
        "2026-07-03; обе даты видны в /health (index_as_of и last_update).",

    "e47ded1737cb":
        "РЕГРЕССИЯ закрыта с первопричиной. index_as_of был 'unknown' не из-за кода "
        "приложения, а из-за run_server.bat: файл был UTF-8 с LF и кириллическими "
        "REM; при CHCP 65001 cmd.exe ведёт позицию батника в БАЙТАХ, из-за чего "
        "следующие команды пропускались и резались посреди строки (в прогоне "
        "было видно 'D:\\ConsPlus>OSTCONSULTANT_PORT/' — SET не выполнялся). Батник "
        "переписан ASCII-only + CRLF, запрет задокументирован в его комментариях; "
        "проверка воспроизведена scripts/probe_chcp.ps1, нормализация — "
        "scripts/fix_bat_eol.ps1. Дополнительно: при перезапуске нужно снимать "
        "cmd.exe-оболочку ДО python.exe, иначе Resurrector поднимает процесс со "
        "старым блоком окружения. Живой /health: index_as_of=2026-07-03, "
        "source='env CONSULTANT_INDEX_AS_OF'.",

    # --- /search ---
    "3c1c7cd864d7":
        "total больше не «число найденного» из ниоткуда: берётся только из позиции "
        "читалки «Док. N / total» текущего списка, источник подписан "
        "total_source (doc_position|section_count|tree|unavailable). Если значение "
        "не прочитано — total=null, а pages=null (_pages возвращает None, а не 0: "
        "«0 страниц» больше не похоже на «нет результатов»). Доедание предыдущего "
        "запроса снято — сессия обновляется только подтверждённой выдачей. Живой "
        "прогон: total=38, total_source=doc_position.",

    "41fd983ff936":
        "Ложная пустая выдача снята на уровне классификации и попыток: дерево "
        "перечитывается до 3 раз, список перечисляется 2 попытки (между ними "
        "close_modal_dialogs + open_all_results + select_category). Ключевая "
        "подмена «не смог прочитать = не нашёл» убрана: пустое дерево даёт "
        "empty_reason='tree_not_read' (раньше — no_matches), ok=false, "
        "retryable=true, total=null и note «это НЕ «нет документов в базе»»; "
        "непустой раздел с нечитанными строками — 'list_not_rendered' с "
        "section_count. Тесты: test_no_matches_reason, test_list_not_rendered, "
        "test_retry_recovers_when_list_renders_second_time.",

    "2cc486c55387":
        "Подмена раздела больше не тихая: selection_rule='requested_category' "
        "ставится только при совпадении нормализованных запрошенного и выбранного "
        "имён, иначе 'approximate' + note «запрошен раздел X, выбран близкий по "
        "имени Y — результат относится к Y»; без category выбирается детерминированно "
        "первый лист ('first_leaf_in_tree_order'). Ответ содержит requested_category, "
        "selected_category, section_count, filter_applied. Там же убран ложный "
        "no_matches при нечитанном дереве (tree_not_read).",

    "dbb0182949e2":
        "Первый проход после смены состояния GUI больше не отдаёт мгновенный 400: "
        "перед тем как признать unknown_category, дерево перечитывается до 3 раз с "
        "open_all_results() и паузами, а GuiError из GUI не превращается в "
        "«неизвестная категория». 400 теперь содержит retryable=true, categories[] "
        "со свежим списком, tree_reads=3, requested_category и hint взять имя из "
        "categories. Экспоненциального «повтори и получишь 200» больше нет.",

    "5f6bfa0e4a5b":
        "Словарь разделов перестал зависеть от удачи/позиции окна: он перечитывается "
        "в начале каждого /search (до 3 раз) и возвращается в categories[] и "
        "sections[] каждого ответа, а не только в удачные минуты прогона. Манифест "
        "объясняет categories_scope: словарь = текущий уровень дерева К+, "
        "неизвестное имя -> 400 unknown_category со свежим categories[]. "
        "known_categories — только fallback-подсказка, не источник истины.",

    "4ad19b1f37b8":
        "Эхо отфильтровывается на любой длине запроса: _is_echo() сравнивает "
        "нормализованные строки (снятие пунктуации/кавычек/nbsp) и отбрасывает "
        "обрезанное по ширину колонки эхо при длине запроса >=20 символов, «Поиск:» "
        "префиксы и пустые заголовки. Закономерность «длиннее ~5 слов» больше не "
        "работает: на 2-словных запросах выдача либо с реальными заголовками, либо "
        "честный list_not_rendered с ok=false — эхо в docs[] не проходит "
        "(test_echo_titles_filtered).",

    "5607db8a1c12":
        "РЕГРЕССИЯ снята тем же механизмом, что и 4ad19b1f37b8: docs[] собирается "
        "через _row_from_titles(), где каждая строка проверяется _is_echo(); при "
        "полном отбрасывании выдача НЕ помечается успешной — empty_reason="
        "'list_not_rendered', ok=false, retryable=true. Живой прогон "
        "logs/retry_check.txt: «обзор практики» даёт 3 настоящих заголовка, "
        "«обзор судебной практики верховный суд» — ok=false вместо эха.",

    "60f43642e86e":
        "docs[].ref заполняется для каждой строки: _doc_row(abs_i, title) выдаёт "
        "'pos:<abs>', где abs — абсолютный номер документа в списке. ref принимается "
        "обратно в /doc, /sub и /open (включая uri=...ref=), поэтому прямой доступ "
        "из выдачи теперь есть чем строить. Живой прогон: ref='pos:3'.",

    "bb9515a15b8e":
        "Протечка прошлого списка закрыта тремя заслонами: (1) соответствие страницы "
        "запросу — _page_matches_query() по заголовку окна «Поиск: ...»; (2) "
        "rows_identical (все строки одинаковы) и stale_suspect (при ДРУГОМ запросе "
        "получен посимвольно тот же набор заголовков) -> empty_reason="
        "'list_not_rendered', docs=[], dropped_rows, stale_suspect=true; (3) кэш-хит "
        "помечается cached/_age и прогоняется через _hydrate_session(), поэтому "
        "ответ из кэша не оставляет сессию от прежнего запроса. Деградация не "
        "кэшируется. Живой прогон шаг 5 (анти-протечка) — PASS.",

    "d3c7ffb4f418":
        "РЕГРЕССИЯ (было df488837e3fc) устранена тем же stale-детектором, что и "
        "bb9515a15b8e: новый /search без category обязан сойтись по заголовку "
        "страницы с ЭТОМ запросом, иначе строки отбрасываются с stale_suspect=true и "
        "ok=false; сессия перезаписывается только подтверждённой выдачей "
        "(_hydrate_session вызывается на живом ответе, кэш-хит — с from_cache=true).",

    # --- /doc, /sub, /open ---
    "38b7c8795a8a":
        "Семантика адреса строки задокументирована (манифест, doc_index_semantics) и "
        "выводится из выдачи: index — 0-based и равен docs[].index того же ответа, "
        "row — 1-based алиас, ref — 'pos:<abs>'. _resolve_row() принимает любое из "
        "трёх; при промахе — 400 index_out_of_range с parsed_count, index_base=0 и "
        "valid_range; ref из чужого списка — 400 ref_not_in_current_list. Ответ "
        "повторяет matched_index/matched_title/abs/ref и requested (эхо входных "
        "полей). Тест test_row_1_based_alias_and_ref.",

    "aa213ed6f361":
        "Когда адресуемой выдачи нет, /doc и /sub отвечают 400 no_openable_list "
        "(parsed_count=0, retryable=true, hint «сделай POST /search, можно fresh=1»), "
        "а если GUI ушёл со страницы результатов — 400 list_not_active. Успешный "
        "/search больше не оставляет GUI на «Стартовой» с живыми docs[]: сессию "
        "гидрирует только подтверждённая выдача, а /open после чтения гасит "
        "session['openable']. Живой прогон шаг 8: HTTP 400, а не 400 "
        "index_out_of_range.",

    "afeb1abcaef3":
        "Mojibake устранён в источнике и на границе: rtf_util читает RTF по его "
        "ansicpg (для К+ — cp1251) и больше не делает latin-1 fallback; "
        "дополнительно _prep_text() -> rtf_util.fix_mojibake() починяет «Äîêóìåíò "
        "ïðåäîñòàâëåí ÊîíñóëüòàíòÏëþñ», если кривые байты пришли из кэша. Ответы "
        "/doc, /sub, /open несут content_charset='utf-8' и mojibake_repaired. Живой "
        "прогон шага 3: repair не понадобился (repaired=false), следов mojibake нет.",

    "f3aa36f9a116":
        "ДЕГРАДИРОВАННАЯ выдача больше не маскируется под 200: /doc делает до 3 "
        "попыток goto_doc_index + export, при теле короче DOC_MIN_CONTENT "
        "kind='unavailable', ok=false, retryable=true (test_unavailable_honest_not_"
        "masked); при несовпадении заголовка открытого документа со строкой выдачи "
        "title_match='no' -> ok=false и сообщение «content не использовать как "
        "цитату». Одно и то же чужое тело для index=0..3 невозможно: адрес строки "
        "однозначен (abs/ref), а контроль заголовков (_titles_correspond по словам и "
        "наборам цифр — ст. 190 против ст. 333 даёт 'no') отсеивает подмену.",

    "c1dbfe0f2947":
        "/sub приводит ответ к контракту /doc: текст лежит в content (плюс "
        "алиас text для обратной совместимости), есть content_len, "
        "content_charset, mojibake_repaired, links[] и entries[]. entries "
        "заполняется для kind='collection' (>=5 ссылок); когда ссылок нет, "
        "ok=true сопровождается hint «для текста конкретного пункта используй "
        "/open {href} из entries» и пустым списком как честным фактом, а не "
        "обещанием манифеста. Тесты test_sub_schema_matches_doc, "
        "test_sub_not_masked_empty, test_sub_collection_entries_href.",

    # --- /open ---
    "7ff67e4db6f7":
        "Полнотекстовый фолбэк «откроем что-нибудь похожее» убран. /open по title: "
        "страница результатов обязана открыться и соответствовать запросу "
        "(иначе 502 results_page_not_opened), candidate ранжируются _score_title() "
        "по покрытию СЛОВ ЗАПРОСА, при score < 0.6 — 404 doc_not_found c "
        "exact_match=false, candidates[] (title/score/ref) и БЕЗ content. Живой "
        "прогон шаг 6: HTTP 404 на выдуманный заголовок, чужое тело не выдано.",

    "d0f56f25fda9":
        "Флаг соответствия добавлен и работает: в ответе есть exact_match, "
        "requested_title, opened_title, match_score, candidates[], а _read_doc() "
        "считает title_match; при title_match='no' или kind='unavailable' ответ "
        "ok=false, retryable=true с message 'doc_unavailable/doc_title_mismatch — "
        "повтори /search затем /open'. Молчаливого открытия другого документа нет: "
        "нет кандидата >=0.6 -> 404 doc_not_found (see 7ff67e4db6f7).",

    # --- /back, /state ---
    "2075ba12d5ca":
        "/back перестал растить стек: каждый вызов УМЕНЬШАЕТ state['nav'] "
        "(pop()), отдельный счётчик back_events; ответ содержит depth, state, "
        "search_page, session_openable, session_query и note о необходимости "
        "повторного /search. current в /state больше не залипает: если GUI ушёл со "
        "страницы выдачи, current=null и session_valid=false. «Поиск» без фильтра "
        "достижим по depth. Живой прогон шаг 7: depth=1, session_openable=false; "
        "шаг 8: /doc -> 400 no_openable_list.",
}

# Отдельная пометка для заявок, где остаточное ограничение GUI перенесено в новые
CARRY = {
    "41fd983ff936": PARTIAL,
    "5607db8a1c12": PARTIAL,
    "4ad19b1f37b8": PARTIAL,
    "3c1c7cd864d7": PARTIAL,
    "aa213ed6f361": BLIND,
    "f3aa36f9a116": BLIND,
    "d0f56f25fda9": BLIND,
}

w("")
w("=== PATCH 22 status=fixed ===")
ok_count = 0
for iid, note in NOTES.items():
    if not note:
        continue
    full = note if iid not in CARRY else (
        note + " | ОСТАТОЧНОЕ ограничение GUI перенесено в новую заявку " +
        CARRY[iid] + " (не считаем закрытым навигацию, которую не починили)")
    st, j = call("PATCH", "/issues/" + iid, {"status": "fixed", "note": full})
    good = j.get("ok") and (j.get("issue") or {}).get("status") == "fixed"
    ok_count += 1 if good else 0
    w("%-14s http=%s fixed=%-5s %s" % (iid, st, str(good),
                                       (j.get("issue") or {}).get("title", "")[:60]
                                       if good else json.dumps(j, ensure_ascii=False)[:200]))

w("")
w("закрыто: %d/%d" % (ok_count, len([v for v in NOTES.values() if v])))

st, j = call("GET", "/issues?status=open&limit=200")
items = j.get("issues") or []
w("")
w("=== осталось открытым: %s ===" % j.get("count"))
for r in items:
    w("  %s | %-6s | %-10s | %s" % (r.get("id"), r.get("severity"),
                                    r.get("endpoint"), (r.get("title") or "")[:70]))

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(_report) + "\n")
print("\n".join(_report[-40:]))
