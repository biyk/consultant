# -*- coding: utf-8 -*-
"""Зонд по открытым заявкам:
  e7f7bb098cfd — список выдачи читается только перелистыванием читалки, и то
                 частично либо «эхом запроса»;
  e15c0d424393 — open_first_doc бьёт двойным кликом по жёстким координатам
                 (900,300) вместо элемента.

Вопросы и что на них отвечает зонд (с живого окна, фактами):
  Q1. Отдаёт ли К+ строки списка результатов как UIA-элементы (ListItem /
      DataItem / Hyperlink / Text с именем-заголовком)? Если да — перечисление
      становится чтением дерева: без открытия документа, без листания, без
      «эха» поля поиска.
  Q2. Что физически лежит в точках (900,300)/(700,300)/(900,400) на странице
      списка — чем заменить жёсткие координаты (элемент + его rectangle).
  Q3. Какой элемент несёт НАСТОЯЩИЙ заголовок: снимаем имена до/после next_doc
      и смотрим, чьё имя ИЗМЕНИЛОСЬ (имя поля поиска не меняется — именно его
      мы сейчас и путаем с заголовком).
  Q4. Можно ли задать номер документа значением поля «Док. N» (set_value) —
      тогда goto_doc_index из N кликов превращается в один.

Запуск (окно К+ занято, сервер в это время не должен обрабатывать запросы):
    venv\\Scripts\\python.exe -m server.probe_results_uia
    powershell -File scripts\\run_probe.ps1 -Mod server.probe_results_uia
Результат: server/probe_results_uia.txt (+ stdout в logs/probe_run.txt).
"""
import ctypes
import io
import os
import sys
import time
from collections import Counter

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
try:
    ctypes.windll.kernel32.SetPriorityClass(
        ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000)  # BELOW_NORMAL
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)
OUT = os.path.join(HERE, "probe_results_uia.txt")

QUERY = os.environ.get("PROBE_QUERY", "ключевая ставка")
CLICK_POINTS = ((900, 300), (700, 300), (900, 400))
SWEEP_TYPES = ("List", "ListItem", "DataGrid", "DataItem", "Table", "Custom",
               "Hyperlink", "Text", "Edit", "Tree", "TreeItem")

L = []


def log(msg=""):
    L.append(str(msg))
    print(msg, flush=True)


def trunc(s, n=110):
    s = (s or "").replace("\n", "\\n").replace("\r", "")
    return s[:n]


def brief(el):
    i = el.element_info
    try:
        r = i.rectangle
        rs = "(%d,%d,%d,%d) %dx%d" % (r.left, r.top, r.right, r.bottom,
                                      r.width(), r.height())
    except Exception:  # noqa: BLE001
        rs = "?"
    return "[%s] aid=%r cls=%r name=%r %s" % (i.control_type, i.automation_id,
                                              trunc(i.class_name, 26), trunc(i.name), rs)


def sig(el):
    i = el.element_info
    try:
        r = i.rectangle
        return (i.control_type, i.automation_id, i.class_name, r.left, r.top)
    except Exception:  # noqa: BLE001
        return (i.control_type, i.automation_id, i.class_name, None, None)


def snapshot(win, types):
    out = {}
    for t in types:
        try:
            for e in win.descendants(control_type=t):
                out[sig(e)] = (e.element_info.name or "").strip()
        except Exception as exc:  # noqa: BLE001
            log("  ! descendants(%s) упало: %r" % (t, exc))
    return out


def elements_at(win, x, y):
    hits = []
    for e in win.descendants():
        try:
            r = e.rectangle()
        except Exception:  # noqa: BLE001
            continue
        if r.left <= x <= r.right and r.top <= y <= r.bottom:
            hits.append(e)
    hits.sort(key=lambda e: e.rectangle().width() * e.rectangle().height())
    return hits


def sweep_page(win, tag, keyword):
    """Полный снимок страницы: histogram + всё именованное по типам."""
    log("\n########## %s ##########" % tag)
    allc = []
    try:
        allc = win.descendants()
    except Exception as exc:  # noqa: BLE001
        log("  ! descendants() упало: %r" % exc)
        return
    ctr = Counter(e.element_info.control_type for e in allc)
    log("  histogram: " + "  ".join("%s=%d" % (k or "?", v)
                                    for k, v in ctr.most_common()))
    log("  всего элементов: %d" % len(allc))

    for t in SWEEP_TYPES:
        els = [e for e in allc if e.element_info.control_type == t]
        named = [e for e in els if (e.element_info.name or "").strip()]
        if not els:
            continue
        log("\n  ### %s: %d (с непустым name: %d)" % (t, len(els), len(named)))
        for e in named[:20]:
            log("    " + brief(e))

    # главное: есть ли где-то имя, похожее на заголовок из выдачи
    kl = (keyword or "").lower()
    lookalikes = [e for e in allc
                  if len((e.element_info.name or "").strip()) > 20
                  and kl and kl in (e.element_info.name or "").lower()]
    log("\n  элементов, чьё name содержит %r: %d" % (keyword, len(lookalikes)))
    for e in lookalikes[:25]:
        log("    " + brief(e))


def phase_buttons(gui, win, keyword):
    """Все Button страницы списка, по вертикали: ищем закономерность строк.
    (первый прогон показал, что строки выдачи — это Button с name=заголовок)"""
    log("\n########## Q1b. ВСЕ кнопки списка (по top) ##########")
    btns = []
    for e in win.descendants(control_type="Button"):
        try:
            r = e.rectangle()
        except Exception:  # noqa: BLE001
            continue
        nm = (e.element_info.name or "").strip()
        btns.append((r.top, r.left, r, nm, e.element_info.automation_id,
                    e.element_info.class_name))
    btns.sort(key=lambda b: (b[0], b[1]))
    log("  кнопок: %d" % len(btns))
    kl = (keyword or "").lower()
    for top, left, r, nm, aid, cls in btns:
        mark = "*" if kl and kl in nm.lower() else " "
        log("  %s top=%-4d left=%-4d w=%-4d h=%-3d aid=%-6r cls=%-14r %r"
            % (mark, top, left, r.width(), r.height(), aid, trunc(cls, 12),
               trunc(nm, 70)))


def phase_list_page(gui, win, keyword):
    """Q1 + Q2 — пока читалка НЕ открыта, мы на странице списка."""
    sweep_page(win, "Q1. СТРАНИЦА СПИСКА (до открытия документа)", keyword)
    phase_buttons(gui, win, keyword)
    log("\n### Q2. что лежит под точками dbl-click на странице списка:")
    log("  rect окна: %s" % (win.rectangle(),))
    for x, y in CLICK_POINTS:
        hits = elements_at(win, x, y)
        log("  точка (%d,%d): %d попаданий" % (x, y, len(hits)))
        for e in hits[:8]:
            log("    " + brief(e))


def phase_reader(gui, win, keyword):
    """Q3 + Q4 — открываем документ, листаем, ищем меняющийся элемент."""
    log("\n########## Q3. читалка: элемент, чьё имя МЕНЯЕТСЯ при next_doc ##########")
    pos = gui._doc_position()
    if pos[0] is None:
        gui.open_first_doc()
        pos = gui._doc_position()
        log("  после dbl-click (900,300) позиция: %r" % (pos,))
    else:
        log("  читалка уже открыта, позиция: %r" % (pos,))
    if gui._doc_position()[0] is None:
        log("  СТОП: читалка не открылась — диф не построить")
        return

    a = snapshot(win, ("Edit", "Text", "Hyperlink", "Custom"))
    if not gui.next_doc():
        log("  ! next_doc не сработал")
        return
    b = snapshot(win, ("Edit", "Text", "Hyperlink", "Custom"))
    changed = [(k, a.get(k, "<нет>"), b.get(k, "<нет>"))
               for k in set(a) | set(b) if a.get(k) != b.get(k)]
    log("  элементов с изменившимся именем: %d из %d" % (len(changed), len(a)))
    for k, x, y in changed[:25]:
        log("    [%s aid=%r cls=%r] %r -> %r" % (k[0], k[1], trunc(k[2], 22),
                                                 trunc(x, 70), trunc(y, 70)))
    log("  сверка с текущим _doc_title(): %r" % trunc(gui._doc_title(), 90))
    log("  позиция после листания: %r" % (gui._doc_position(),))
    # есть ли в списке элементов хоть один, похожий на заголовок этого документа
    phase_reader_title_probe(gui, win)

    log("\n### Q4. прямое задание номера документа (set_value по «Док. N»):")
    tgt = 6
    before = gui._doc_position()
    applied = False
    for e in win.descendants(control_type="Edit"):
        nm = (e.element_info.name or "").replace("\xa0", " ")
        if "Док" not in nm:
            continue
        try:
            e.set_value(str(tgt))
            from pywinauto.keyboard import send_keys
            send_keys("{ENTER}")
            time.sleep(1.2)
            applied = True
            log("  set_value(%d) в Edit %r -> %r" % (tgt, trunc(nm, 44),
                                                      gui._doc_position()))
            break
        except Exception as exc:  # noqa: BLE001
            log("  set_value не удался на Edit %r: %r" % (trunc(nm, 44), exc))
    if not applied:
        log("  set_value неприменим — остаётся листание (или чтение списка из Q1)")
    log("  позиция до/после: %r / %r" % (before, gui._doc_position()))


def phase_reader_title_probe(gui, win):
    """Что видит _doc_title() сегодня: список всех Edit-кандидатов."""
    log("\n  кандидаты _doc_title() (Edit, name>=4, top<320, width>300):")
    for e in win.descendants(control_type="Edit"):
        nm = (e.element_info.name or "").strip()
        if len(nm) < 4:
            continue
        try:
            r = e.rectangle()
        except Exception:  # noqa: BLE001
            continue
        mark = "ДА" if (r.top < 320 and r.width() > 300) else "нет"
        log("    [%s top=%d w=%d] %r" % (mark, r.top, r.width(), trunc(nm, 80)))


def right_pane_rows(win, min_len=25, left_min=540):
    """Кандидаты в «строки списка»: именованные элементы правее дерева,
    с длинным именем (заголовок документа), по вертикали."""
    out = []
    for e in win.descendants():
        nm = (e.element_info.name or "").strip()
        if len(nm) < min_len:
            continue
        try:
            r = e.rectangle()
        except Exception:  # noqa: BLE001
            continue
        if r.left < left_min or r.top < 200:
            continue
        out.append((r.top, r.left, i_type(e), nm, r))
    out.sort(key=lambda t: (t[0], t[1]))
    return out


def i_type(el):
    return el.element_info.control_type or "?"


def phase_step(win, gui, tag, limit=18):
    """Компактный снимок страницы на конкретном шаге навигации."""
    log("\n---------- шаг: %s ----------" % tag)
    log("  состояние=%r  позиция читалки=%r" % (gui._state_suffix(),
                                                gui._doc_position()))
    rows = right_pane_rows(win)
    ctr = Counter()
    for _t, _l, ct, _n, _r in rows:
        ctr[ct] += 1
    log("  именованных элементов правее дерева (top>=200): %d  [%s]"
        % (len(rows), "  ".join("%s=%d" % kv for kv in ctr.most_common())))
    for top, left, ct, nm, r in rows[:limit]:
        log("    %-9s top=%-5d left=%-5d w=%-4d %r" % (ct, top, left, r.width(),
                                                       trunc(nm, 76)))
    return rows


def main_steps():
    """Пошаговая навигация к СПИСКУ РАЗДЕЛА и снимок после каждого шага:
    где физически появляется список документов (и появляется ли)."""
    from server.consultant_gui import ConsultantGUI
    gui = ConsultantGUI()
    if not gui.connect(timeout=30):
        log("СТОП: окно К+ не найдено")
        return 2
    win = gui.win
    log("=== пошаговый зонд навигации (query=%r) ===" % QUERY)
    log("rect окна: %s" % (win.rectangle(),))
    gui.close_modal_dialogs()
    gui.close_extra_tabs(keep=1)
    phase_step(win, gui, "S0 исходное состояние")

    gui.do_search(QUERY)
    phase_step(win, gui, "S1 после «Найти» (страница быстрой выдачи)")

    gui.wait_tree(timeout=40)
    cats = gui.read_categories()
    log("  разделов: %d -> %r" % (len(cats), [(c["name"], c.get("count"))
                                              for c in cats[:6]]))
    leaf = next((c for c in cats if c.get("leaf") and c.get("count")), None)
    if leaf is None:
        log("  СТОП: дерево не прочитано")
        return 2

    try:
        gui.open_all_results()
    except Exception as exc:  # noqa: BLE001
        log("  open_all_results исключение: %r" % exc)
    time.sleep(1.0)
    phase_step(win, gui, "S2 после «Все результаты поиска»")

    items = gui.tree_items()
    target = None
    for it, nm in items:
        if leaf["name"].lower()[:12] in nm.lower():
            target = it
            break
    log("  TreeItem для %r: %s" % (leaf["name"], "найден" if target else "НЕТ"))

    if target is not None:
        target.click_input()
        time.sleep(2.0)
        phase_step(win, gui, "S3 одинарный клик по TreeItem раздела")
        try:
            target.double_click_input()
        except Exception as exc:  # noqa: BLE001
            log("  double_click_input не удался: %r" % exc)
        time.sleep(2.5)
        phase_step(win, gui, "S4 двойной клик по TreeItem раздела")
        try:
            from pywinauto.keyboard import send_keys
            send_keys("{ENTER}")
            time.sleep(2.0)
            phase_step(win, gui, "S5 Enter по выделенному TreeItem")
        except Exception as exc:  # noqa: BLE001
            log("  Enter не прошёл: %r" % exc)

    log("\n=== конец пошагового зонда ===")
    return 0


def dump_tabs(gui, tag):
    log("\n  [%s] вкладки: %r  состояние=%r  позиция=%r"
        % (tag, gui.tabs(), gui._state_suffix(), gui._doc_position()))


def main_tabs():
    """Гипотеза: «Все результаты поиска» открывает ОТДЕЛЬНУЮ вкладку, а
    close_extra_tabs(keep=1) её закрывает — и мы остаёмся на старанице с
    блоком «Последние открытые документы» (его заголовки и отдаются как
    «выдача»). Проверяем: навигация БЕЗ закрытия вкладок + снимок каждой.
    """
    from server.consultant_gui import ConsultantGUI
    gui = ConsultantGUI()
    if not gui.connect(timeout=30):
        log("СТОП: окно К+ не найдено")
        return 2
    win = gui.win
    log("=== зонд вкладок (query=%r) ===" % QUERY)
    gui.close_modal_dialogs()          # вкладки НЕ трогаем!
    dump_tabs(gui, "T0 исходно")
    phase_step(win, gui, "T0 исходная страница")

    gui.do_search(QUERY)
    dump_tabs(gui, "T1 после «Найти»")
    phase_step(win, gui, "T1 страница быстрой выдачи")

    gui.open_all_results()
    time.sleep(1.5)
    dump_tabs(gui, "T2 после «Все результаты поиска»")
    phase_step(win, gui, "T2 после «Все результаты поиска»")

    gui.wait_tree(timeout=40)
    cats = gui.read_categories()
    log("  разделов: %d -> %r" % (len(cats), [(c["name"], c.get("count"))
                                              for c in cats[:6]]))
    leaf = next((c for c in cats if c.get("leaf") and c.get("count")), None)
    if leaf:
        gui.select_category(leaf["name"])
        time.sleep(2.0)
        log("  выбран раздел %r count=%s" % (leaf["name"], leaf.get("count")))
        dump_tabs(gui, "T3 после выбора раздела")
        phase_step(win, gui, "T3 список выбранного раздела?")

    # походим по каждой вкладке и посмотрим, где лежит список
    items = gui._tab_items()
    log("\n  TabItem элементов: %d" % len(items))
    for n, it in enumerate(items):
        try:
            it.click_input()
        except Exception as exc:  # noqa: BLE001
            log("  вкладка %d: клик не удался %r" % (n, exc))
            continue
        time.sleep(1.5)
        dump_tabs(gui, "T4.%d вкладка %r" % (n, (it.element_info.name or "")[:30]))
        phase_step(win, gui, "T4.%d содержимое вкладки %r"
                   % (n, trunc(it.element_info.name, 30)))

    if leaf:
        log("\n  === dbl-click (900,300) на текущей вкладке и сверка объёма ===")
        log("  section_count=%s" % leaf.get("count"))
        gui.open_first_doc()
        cur, total = gui._doc_position()
        log("  читалка: cur=%s total=%s  (раздел говорил %s)"
            % (cur, total, leaf.get("count")))
        log("  совпадает объём: %s" % (total == leaf.get("count"),))
        log("  первый заголовок: %r" % trunc(gui._doc_title(), 90))
    log("\n=== конец зонда вкладок ===")
    return 0


def main_volume():
    """Главный вопрос заявки e7f7bb098cfd: КАК получить в читалке список ИМЕННО
    выбранного раздела (total == count из дерева), а не общий список выдачи.
    Перебираем стратегии навигации × точки клика и после каждой читаем
    «Док.N/total» — ищем совпадение с объёмом раздела."""
    from server.consultant_gui import ConsultantGUI
    gui = ConsultantGUI()
    if not gui.connect(timeout=30):
        log("СТОП: окно К+ не найдено")
        return 2
    win = gui.win
    log("=== зонд объёма списка (query=%r) ===" % QUERY)
    gui.close_modal_dialogs()
    gui.close_extra_tabs(keep=1)
    if not gui.do_search(QUERY):
        log("СТОП: поиск не открылся")
        return 2
    gui.open_all_results()
    gui.wait_tree(timeout=40)
    cats = gui.read_categories()
    log("разделов: %d -> %r" % (len(cats), [(c["name"], c.get("count"))
                                            for c in cats[:6]]))
    leaf = next((c for c in cats if c.get("leaf") and c.get("count")), None)
    if leaf is None:
        log("СТОП: дерево не прочитано")
        return 2
    want = leaf["count"]
    log("цель: total=%s раздела %r" % (want, leaf["name"]))
    pane = gui.list_pane_rect()
    log("list_pane_rect() = %s" % (pane,))

    strategies = (
        ("A: клик по TreeItem", lambda it: it.click_input()),
        ("B: TreeItem + Enter", lambda it: (it.click_input(), _enter())),
        ("C: двойной клик по TreeItem", lambda it: it.double_click_input()),
    )
    points = [(900, 300)]
    if pane is not None:
        points += [(pane.left + 300, pane.top + 25), (pane.left + 300, pane.top + 62)]
    hit = None
    for tag, act in strategies:
        try:
            items = gui.tree_items()
            it = next((i for i, nm in items
                       if leaf["name"].lower()[:12] in nm.lower()), None)
            if it is None:
                log("  %s: TreeItem не найден — пропускаем" % tag)
                continue
            act(it)
            time.sleep(2.0)
        except Exception as exc:  # noqa: BLE001
            log("  %s: навигация не удалась %r" % (tag, exc))
            continue
        for (px, py) in points:
            if gui._doc_position()[0] is not None:
                gui.ensure_list_page()
            try:
                win.click_input(coords=(px, py), double=True)
            except Exception as exc:  # noqa: BLE001
                log("  %s клик (%d,%d) не прошёл: %r" % (tag, px, py, exc))
                continue
            time.sleep(2.0)
            cur, total = gui._doc_position()
            title = gui._doc_title(_flatq(QUERY))
            log("  %-26s клик (%4d,%4d) -> pos=%s/%s  совпало=%s  title=%r"
                % (tag, px, py, cur, total, total == want, trunc(title, 60)))
            if total == want and cur is not None:
                hit = (tag, px, py)
                break
        if hit:
            break

    if hit is None:
        log("\nИТОГ: ни одна стратегия не дала список раздела (%s) — "
            "дальше только честный отказ list_scope_mismatch" % want)
    else:
        log("\nИТОГ: список раздела открыт: %s, точка %s" % (hit[0], hit[1:]))
        gui.goto_doc_index(1)
        for i in range(3):
            log("  #%s pos=%s title=%r" % (i + 1, gui._doc_position(),
                                          trunc(gui._doc_title(_flatq(QUERY)), 90)))
            gui.next_doc()
            time.sleep(0.8)
    try:
        gui.go_back()
        gui.close_extra_tabs(keep=1)
    except Exception:  # noqa: BLE001
        pass
    log("=== конец зонда объёма ===")
    return 0


def _enter():
    from pywinauto.keyboard import send_keys
    send_keys("{ENTER}")


def _flatq(q):
    """Нормализация запроса как в app._flat — чтобы проверять «эхо»."""
    import re
    s = (q or "").replace("\u00a0", " ").lower()
    s = re.sub(r"[\u00ab\u00bb\"'`()\u002e,;:!?$#\-–—_/\\]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def main_grid():
    """Геометрия строк: после выбора раздела в дереве водим dbl-click по
    вертикали и смотрим, в какой точке открывается список И объём этого
    списка. Цель — найти строку списка РАЗДЕЛА (total == section_count),
    а не общего списка выдачи (1868 при разделе 1588)."""
    from server.consultant_gui import ConsultantGUI
    gui = ConsultantGUI()
    if not gui.connect(timeout=30):
        log("СТОП: окно К+ не найдено")
        return 2
    win = gui.win
    log("=== зонд геометрии строк (query=%r) ===" % QUERY)
    gui.close_modal_dialogs()
    gui.close_extra_tabs(keep=1)
    if not gui.do_search(QUERY):
        log("СТОП: поиск не открылся")
        return 2
    gui.open_all_results()
    gui.wait_tree(timeout=40)
    cats = gui.read_categories()
    leaf = next((c for c in cats if c.get("leaf") and c.get("count")), None)
    if leaf is None:
        log("СТОП: дерево не прочитано")
        return 2
    want = leaf["count"]
    pane = gui.list_pane_rect()
    log("раздел %r count=%s; pane=%s" % (leaf["name"], want, pane))

    def sweep(tag, ylist, x=900):
        log("\n  --- %s (x=%s) ---" % (tag, x))
        found = []
        for y in ylist:
            if gui._doc_position()[0] is not None:
                gui.ensure_list_page()
            try:
                win.click_input(coords=(x, y), double=True)
            except Exception as exc:  # noqa: BLE001
                log("    y=%s клик не прошёл %r" % (y, exc))
                continue
            time.sleep(1.8)
            cur, total = gui._doc_position()
            ttl = trunc(gui._doc_title(_flatq(QUERY)), 55)
            mark = "<== СОВПАЛО" if total == want else ""
            log("    y=%-4d pos=%s/%-6s title=%r %s" % (y, cur, total, ttl, mark))
            if cur is not None:
                found.append((y, cur, total))
            if total == want:
                return found, y
        return found, None

    ys = list(range(280, 620, 40))     # шаг 40px: строки списка ~19-37px, не пропустим
    hit_y = None
    f1, hit_y = sweep("1) общее дерево (без выбора раздела)", ys)
    if hit_y is None:
        try:
            gui.select_category(leaf["name"])
            time.sleep(1.5)
        except Exception as exc:  # noqa: BLE001
            log("  select_category: %r" % exc)
        f2, hit_y = sweep("2) после выбора раздела", ys)
    if hit_y is not None:
        log("\n  список раздела достигнут на y=%s — читаем 3 заголовка" % hit_y)
        gui.goto_doc_index(1)
        for _ in range(3):
            log("    pos=%s title=%r" % (gui._doc_position(),
                                         trunc(gui._doc_title(_flatq(QUERY)), 90)))
            gui.next_doc()
            time.sleep(0.8)
    else:
        log("\nИТОГ: ни на одном y (280..600, шаг 20) список раздела не открыт")
    try:
        gui.go_back()
        gui.close_extra_tabs(keep=1)
    except Exception:  # noqa: BLE001
        pass
    log("=== конец зонда геометрии ===")
    return 0


def main_title():
    """Какой ЭЛЕМЕНТ несёт настоящий заголовок открытого документа.
    Геометрический эвристика _doc_title() (верхний Edit шире 300px) на странице
    выдачи берёт заголовки ПОЛОС («Российское законодательство…», «КонсультантПлюс:
    Новости для бухгалтера») — не заголовок документа. Ищем элемент, чьё имя
    МЕНЯЕТСЯ при next_doc, и печатаем его aid/class/rect: на него и пересядем."""
    from server.consultant_gui import ConsultantGUI
    gui = ConsultantGUI()
    if not gui.connect(timeout=30):
        log("СТОП: окно К+ не найдено")
        return 2
    win = gui.win
    log("=== зонд элемента заголовка (query=%r) ===" % QUERY)
    gui.close_modal_dialogs()
    gui.close_extra_tabs(keep=1)
    if not gui.do_search(QUERY):
        log("СТОП: поиск не открылся")
        return 2
    gui.open_all_results()
    time.sleep(1.0)
    qflat = _flatq(QUERY)

    for y in (600, 300):
        log("\n########## полоса y=%s ##########" % y)
        if gui._doc_position()[0] is not None:
            gui.ensure_list_page()
        win.click_input(coords=(900, y), double=True)
        time.sleep(2.0)
        cur, total = gui._doc_position()
        log("  pos=%s/%s  _doc_title()=%r" % (cur, total,
                                             trunc(gui._doc_title(qflat), 70)))
        if cur is None:
            log("  не открылось — пропускаем")
            continue
        log("  все Edit (name, aid, cls, rect):")
        for e in win.descendants(control_type="Edit"):
            nm = (e.element_info.name or "").strip()
            if not nm:
                continue
            i = e.element_info
            r = e.rectangle()
            log("    top=%-5d w=%-5d aid=%-6r cls=%-16r %r"
                % (r.top, r.width(), i.automation_id, trunc(i.class_name, 14),
                   trunc(nm, 60)))
        before = snapshot(win, ("Edit",))
        if gui.next_doc():
            time.sleep(1.5)
            after = snapshot(win, ("Edit",))
            log("  изменилось при next_doc:")
            for k in sorted(set(before) | set(after)):
                if before.get(k) != after.get(k):
                    log("    [%s aid=%r cls=%r top=%s] %r -> %r"
                        % (k[0], k[1], trunc(k[2], 14), k[4],
                           trunc(before.get(k), 50), trunc(after.get(k), 50)))
            log("  pos после next_doc: %r" % (gui._doc_position(),))
        gui.go_back()
        time.sleep(1.0)
    log("=== конец зонда элемента заголовка ===")
    return 0


def main_titles():
    """Почему _doc_title() на 2-м документе вернул полосу «Российское
    законодательство (Версия Проф)», а не заголовок? Проходим так же, как
    /search: открыть 1-ю строку (рабочая точка 900,300) и для каждого из
    первых N документов напечатать (pos, что вернул _doc_title) и ВСЕ Edit
    зоны заголовка (top<320 и ширина>300) с их top — видно, какой элемент
    реально несёт заголовок и пустеет ли полоса 179 в момент чтения."""
    from server.consultant_gui import ConsultantGUI
    gui = ConsultantGUI()
    if not gui.connect(timeout=30):
        log("СТОП: окно К+ не найдено")
        return 2
    win = gui.win
    log("=== зонд заголовков по документам (query=%r) ===" % QUERY)
    gui.close_modal_dialogs()
    gui.close_extra_tabs(keep=1)
    if not gui.do_search(QUERY):
        log("СТОП: поиск не открылся")
        return 2
    gui.open_all_results()
    gui.wait_tree(timeout=40)
    cats = gui.read_categories()
    leaf = next((c for c in cats if c.get("leaf") and c.get("count")), None)
    if leaf is None:
        log("СТОП: дерево не прочитано")
        return 2
    try:
        gui.select_category(leaf["name"])
        time.sleep(1.2)
    except Exception as exc:  # noqa: BLE001
        log("  select_category: %r" % exc)
    qflat = _flatq(QUERY)
    log("раздел %r count=%s" % (leaf["name"], leaf.get("count")))

    gui.ensure_list_page()
    win.click_input(coords=(900, 300), double=True)     # доказанная рабочая точка
    time.sleep(2.0)
    cur, total = gui._doc_position()
    log("после открытия: pos=%s/%s" % (cur, total))
    if cur is None:
        log("СТОП: читалка не открылась")
        return 2
    for i in range(6):
        title = gui._doc_title(qflat)
        cur, total = gui._doc_position()
        log("\n--- док #%d pos=%s/%s  _doc_title=%r" % (i + 1, cur, total,
                                                        trunc(title, 80)))
        log("    зона заголовка (top<320, w>300):")
        rows = []
        for e in win.descendants(control_type="Edit"):
            nm = (e.element_info.name or "").strip()
            if not nm:
                continue
            r = e.rectangle()
            if r.top < 320 and r.width() > 300:
                rows.append((r.top, r.width(), nm))
        rows.sort()
        for top, w, nm in rows:
            log("      top=%-5d w=%-5d %r" % (top, w, trunc(nm, 72)))
        if not gui.next_doc():
            log("    next_doc не сработал — стоп")
            break
        time.sleep(1.0)
    try:
        gui.go_back()
        gui.close_extra_tabs(keep=1)
    except Exception:  # noqa: BLE001
        pass
    log("=== конец зонда заголовков ===")
    return 0


def main():
    from server.consultant_gui import ConsultantGUI

    log("=== зонд: страница списка / читалка (query=%r) ===" % QUERY)
    gui = ConsultantGUI()
    if not gui.connect(timeout=30):
        log("СТОП: окно К+ не найдено")
        return 2
    log("окно: %r  rect=%s" % (gui._state_suffix(), gui.win.rectangle()))
    gui.close_modal_dialogs()
    gui.close_extra_tabs(keep=1)

    # --- приводим окно на страницу списка этого запроса (как это делает /search) ---
    ok = False
    for _ in range(2):
        ok = bool(gui.do_search(QUERY))
        st = gui._state_suffix()
        if ok and QUERY.lower()[:12] in st.lower():
            break
    log("do_search ok=%s состояние=%r" % (ok, gui._state_suffix()))
    gui.open_all_results()
    time.sleep(0.8)
    cats = gui.read_categories()
    for _ in range(2):
        if cats:
            break
        gui.open_all_results()
        time.sleep(0.8)
        cats = gui.read_categories()
    log("разделов прочитано: %d -> %r" % (len(cats),
                                          [(c["name"], c.get("count")) for c in cats[:6]]))
    leaf = next((c for c in cats if c.get("leaf") and c.get("count")), None)
    if leaf is None:
        log("СТОП: нет ни одного прочитанного раздела — дальше идти некуда")
        return 2
    gui.select_category(leaf["name"])
    time.sleep(1.2)
    log("выбран раздел %r count=%s; состояние=%r; позиция читалки=%r"
        % (leaf["name"], leaf.get("count"), gui._state_suffix(),
           gui._doc_position()))

    phase_list_page(gui, gui.win, QUERY.split()[0])
    if os.environ.get("PROBE_SKIP_READER") == "1":
        log("\n(читалку не трогали: PROBE_SKIP_READER=1)")
    else:
        phase_reader(gui, gui.win, QUERY.split()[0])

    try:
        gui.go_back()
        gui.close_extra_tabs(keep=1)
    except Exception:  # noqa: BLE001
        pass
    log("\n=== конец зонда ===")
    return 0


if __name__ == "__main__":
    try:
        mode = os.environ.get("PROBE_MODE", "")
        if mode == "steps":
            rc = main_steps()
        elif mode == "tabs":
            rc = main_tabs()
        elif mode == "volume":
            rc = main_volume()
        elif mode == "grid":
            rc = main_grid()
        elif mode == "title":
            rc = main_title()
        elif mode == "titles":
            rc = main_titles()
        else:
            rc = main()
    except Exception as exc:  # noqa: BLE001
        import traceback
        log("ИСКЛЮЧЕНИЕ: %r" % exc)
        log(traceback.format_exc())
        rc = 3
    finally:
        with io.open(OUT, "w", encoding="utf-8") as f:
            f.write("\n".join(L))
        print("[записан %s]" % OUT)
    sys.exit(rc)
