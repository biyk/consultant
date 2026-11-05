# -*- coding: utf-8 -*-
"""Разведка функций клиента К+ (только ЧТЕНИЕ, без опасных кликов).

Цель (§13 todo): снять ВСЕ интерактивные контролы окна в трёх состояниях —
Стартовая / Страница выдачи / Читалка документа — и по фактам понять, какие
функции клиента можно обернуть в API (Оглавление, Редакции, Печать/Экспорт,
Обзор изменений, См. также, Сортировка, Профиль, переход по ref-ссылке, …).

Запуск (окно К+ занято → API-запросы в это время НЕ слать):
    powershell -File scripts\\run_probe.ps1 -Mod server.probe_discover -Query ставка -TimeoutSec 240
Результат: server/probe_discover.txt (+ stdout в logs/probe_run.txt).

Безопасность: ничего не нажимаем, кроме штатной навигации (поиск / «Все
результаты» / открытие первой строки), кнопки Печать/Экспорт/модалки НЕ трогаем.
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
OUT = os.path.join(HERE, "probe_discover.txt")

QUERY = os.environ.get("PROBE_QUERY", "ставка")

L = []


def log(msg=""):
    L.append(str(msg))
    print(msg, flush=True)


def trunc(s, n=110):
    s = (s or "").replace("\n", "\\n").replace("\r", "")
    return s[:n]


def _rect(el):
    try:
        r = el.rectangle()
        return "(%d,%d %dx%d)" % (r.left, r.top, r.width(), r.height())
    except Exception:  # noqa: BLE001
        return "?"


def _enabled(el):
    try:
        return "" if el.is_enabled() else " [DISABLED]"
    except Exception:  # noqa: BLE001
        return ""


# Что считаем «интерактивным» — то, чем теоретически можно управлять из API.
INTERACTIVE = ("Button", "MenuItem", "MenuBarItem", "ComboBox", "DropDown",
               "Tab", "TabItem", "CheckBox", "RadioButton", "SplitButton",
               "Hyperlink", "Edit", "List", "ListItem", "Tree", "TreeItem",
               "DataItem", "Thumb")

# Ключевые слова функций-кандидатов (§13.2) — ищем среди кнопок/пунктов.
FEATURE_KEYWORDS = ("Оглавлен", "Содержан", "Редакц", "Печать", "Печат",
                    "Экспорт", "Сохран", "Изменен", "Доп.", "Доп ", "Дополн",
                    "Застав", "См. также", "Ссылк", "Перейти", "Фильтр",
                    "Сортировк", "Профиль", "Иерарх", "Аннот", "Закрыт",
                    "Копиров", "Быстрый поиск", "Все результаты")


def dump_state(gui, tag):
    win = gui.win
    log("\n########## СОСТОЯНИЕ: %s  (окно: %r) ##########" % (tag, gui._state_suffix()))
    try:
        allc = win.descendants()
    except Exception as exc:  # noqa: BLE001
        log("  ! descendants() упало: %r" % exc)
        return []
    ctr = Counter(e.element_info.control_type for e in allc)
    log("  всего элементов: %d" % len(allc))
    log("  histogram: " + "  ".join("%s=%d" % (k or "?", v)
                                    for k, v in ctr.most_common()))
    named_any = []
    for t in INTERACTIVE:
        els = [e for e in allc if e.element_info.control_type == t]
        named = [e for e in els if (e.element_info.name or "").strip()]
        if not named:
            continue
        named_any.extend(named)
        log("\n  ### %s: %d (непустое name: %d)" % (t, len(els), len(named)))

        def key(e):
            try:
                return e.rectangle().top
            except Exception:  # noqa: BLE001
                return 0
        for e in sorted(named, key=key)[:45]:
            i = e.element_info
            log("    aid=%-6r cls=%-16r %r %s%s"
                % (i.automation_id, trunc(i.class_name, 16), trunc(i.name, 66),
                   _rect(e), _enabled(e)))
    return allc


def dump_features(allc):
    """Кнопки/пункты, чьё имя совпадает с функциями-кандидатами из §13.2."""
    log("\n  --- кнопки-фичи (совпадение имени) ---")
    hit = 0
    for e in allc:
        if e.element_info.control_type not in ("Button", "MenuItem",
                                               "MenuBarItem", "Hyperlink"):
            continue
        n = (e.element_info.name or "").strip()
        if not n:
            continue
        if any(k in n for k in FEATURE_KEYWORDS):
            hit += 1
            log("    [%s] aid=%-6r cls=%-16r %r %s%s"
                % (e.element_info.control_type, e.element_info.automation_id,
                   trunc(e.element_info.class_name, 16), trunc(n, 72),
                   _rect(e), _enabled(e)))
    if not hit:
        log("    (нет совпадений)")


def dump_navtree(gui, tag):
    """После клика «Оглавление»: что появилось (дерево структуры / новое окно)."""
    win = gui.win
    log("\n===== %s =====" % tag)
    # отдельные верхнеуровневые окна процесса (модалка оглавления?)
    import win32process
    hwnd = win.handle
    pid = win32process.GetWindowThreadProcessId(hwnd)[1] if hwnd else None
    import win32gui
    tops = []

    def cb(h, _):
        if pid and win32process.GetWindowThreadProcessId(h)[1] == pid \
                and win32gui.IsWindowVisible(h):
            tops.append((h, win32gui.GetClassName(h), win32gui.GetWindowText(h)))
        return True
    win32gui.EnumWindows(cb, None)
    log("  видимые окна процесса (%d):" % len(tops))
    for h, cls, t in tops:
        log("    hwnd=%s cls=%r title=%r" % (h, trunc(cls, 20), trunc(t, 70)))
    allc = win.descendants()
    trees = [e for e in allc if e.element_info.control_type in ("Tree", "List")]
    log("  Tree/List: %d" % len(trees))
    for e in trees:
        log("    [%s] name=%r aid=%r cls=%r %s"
            % (e.element_info.control_type, trunc(e.element_info.name, 50),
               e.element_info.automation_id, trunc(e.element_info.class_name, 16),
               _rect(e)))
    items = [e for e in allc if e.element_info.control_type in
             ("TreeItem", "ListItem", "DataItem")]
    log("  элементов дерева/списка: %d (первые 60, отступ ~ left)" % len(items))

    def key(e):
        try:
            r = e.rectangle()
            return (r.top, r.left)
        except Exception:  # noqa: BLE001
            return (0, 0)
    for e in sorted(items, key=key)[:60]:
        try:
            r = e.rectangle()
            depth = max(0, r.left // 20)
            left = r.left
        except Exception:  # noqa: BLE001
            depth, left = 0, "?"
        log("    %s( L%s ) %r" % ("  " * depth, left,
                                  trunc(e.element_info.name, 70)))


def main_oglavlenie():
    """Открыть крупный документ и снять, что даёт кнопка «Оглавление». """
    from server.consultant_gui import ConsultantGUI
    log("=== зонд ОГЛАВЛЕНИЕ (query=%r) ===" % QUERY)
    gui = ConsultantGUI()
    try:
        gui.connect(timeout=30)
    except Exception as exc:  # noqa: BLE001
        log("СТОП: %r" % exc)
        return 2
    gui.ensure_window()
    gui.close_modal_dialogs()
    gui.close_extra_tabs(keep=1)
    if not gui.do_search(QUERY):
        log("нет результатов"); return 3
    gui.open_all_results(); time.sleep(1.0)
    cats = gui.read_categories()
    leaf = next((c for c in cats if c.get("leaf") and c.get("count")), None)
    if leaf:
        try:
            gui.select_category(leaf["name"]); time.sleep(1.0)
        except Exception as exc:  # noqa: BLE001
            log("select_category: %r" % exc)
    gui.ensure_list_page()
    if not gui.open_first_doc():
        log("читалка не открылась"); return 4
    time.sleep(1.0)
    log("открыт документ: pos=%r title=%r" % (gui._doc_position(), gui._doc_title()))
    try:
        btn = gui._button_by_name("Оглавление")
        log("найден кнопка «Оглавление»: %s  enabled=%s" % (_rect(btn), btn.is_enabled()))
        btn.click_input()
        time.sleep(1.8)
        dump_navtree(gui, "СРАЗУ ПОСЛЕ клика «Оглавление»")
        # дерево оглавления — по auto_id=1597 (не путать с 1016 «выбор ИБ»)
        tree = None
        for e in gui.win.descendants(control_type="Tree"):
            if e.element_info.automation_id == "1597":
                tree = e
                break
        if tree is not None:
            titems = tree.descendants(control_type="TreeItem")
            log("  \u0434\u0435\u0440\u0435\u0432\u043e 1597: TreeItem=%d" % len(titems))
            for e in titems[:10]:
                try:
                    r = e.rectangle(); rl = "L%d T%d" % (r.left, r.top)
                except Exception:  # noqa: BLE001
                    rl = "?"
                lvl = ""
                try:
                    lvl = " lvl=%s" % e.legacy_properties().get("LegacyIAccessible.Level")
                except Exception:  # noqa: BLE001
                    pass
                log("    %s%s %r" % (rl, lvl, trunc(e.element_info.name, 60)))
            # выбор конкретного пункта (5-й по top) -> меняется ли Абз./содержимое?
            if len(titems) >= 6:
                tgt = sorted(titems, key=lambda z: z.rectangle().top)[5]
                before = gui._doc_position()
                nm = tgt.element_info.name
                log("  \u0434\u0432\u043e\u0439\u043d\u044b\u0439 \u043a\u043b\u0438\u043a \u043f\u043e %r" % trunc(nm, 50))
                try:
                    tgt.click_input(double=True)
                    time.sleep(1.6)
                    log("  \u043f\u043e\u0441\u043b\u0435 \u0432\u044b\u0431\u043e\u0440\u0430: pos=%r (\u0431\u044b\u043b\u043e %r)"
                        % (gui._doc_position(), before))
                except Exception as exc:  # noqa: BLE001
                    log("  click \u0443\u043f\u0430\u043b: %r" % exc)
        # закрыть оглавление (обратный клик)
        try:
            gui._button_by_name("Оглавление").click_input()
            time.sleep(0.8)
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        log("клик «Оглавление» не удался: %r" % exc)
    try:
        gui.go_back(); gui.close_extra_tabs(keep=1)
    except Exception:  # noqa: BLE001
        pass
    log("=== конец ===")
    return 0


def _find_tab_button(gui, name):
    """Кнопка-вкладка типа в строке ~top=108 (не спутать с tree-элементами и
    верхней навигацией top=42)."""
    for b in gui.win.descendants(control_type="Button"):
        n = (b.element_info.name or "")
        if n.strip() != name:
            continue
        try:
            if not b.is_visible():
                continue
            r = b.rectangle()
            if 95 <= r.top <= 130:
                return b
        except Exception:  # noqa: BLE001
            continue
    return None


def main_typefilter():
    """Как вкладки типа материала (Все/Законодательство/Суд. практика/Консультации)
    меняют список и total — понять, можно ли обернуть в /search по параметру type."""
    from server.consultant_gui import ConsultantGUI
    log("=== зонд ФИЛЬТРА ПО ТИПУ (query=%r) ===" % QUERY)
    gui = ConsultantGUI()
    try:
        gui.connect(timeout=30)
    except Exception as exc:  # noqa: BLE001
        log("СТОП: %r" % exc); return 2
    gui.ensure_window(); gui.close_modal_dialogs(); gui.close_extra_tabs(keep=1)
    if not gui.do_search(QUERY):
        log("нет результатов"); return 3
    gui.open_all_results(); time.sleep(1.0)
    base_cats = [(c.get("name"), c.get("count")) for c in gui.read_categories()]
    log("исходное дерево разделов: %r" % (base_cats,))
    for tab in ("Все\xa0документы", "Все документы", "Законодательство",
                "Судебная практика", "Консультации"):
        btn = _find_tab_button(gui, tab)
        if btn is None:
            log("\n-- вкладка %r: НЕ найдена --" % tab); continue
        log("\n-- вкладка %r: клик (%d,%d) --" % (tab, btn.rectangle().left,
                                                   btn.rectangle().top))
        try:
            btn.click_input(); time.sleep(1.4)
        except Exception as exc:  # noqa: BLE001
            log("   клик упал: %r" % exc); continue
        log("   state после клика: %r" % gui._state_suffix())
        # изменилось ли левое дерево разделов?
        try:
            cats = [(c.get("name"), c.get("count")) for c in gui.read_categories()]
            log("   разделы после клика: %r (изменилось=%s)" % (cats, cats != base_cats))
        except Exception as exc:  # noqa: BLE001
            log("   read_categories: %r" % exc)
        # объём нового списка — через открытие первой строки (механизм enumerate)
        try:
            gui.ensure_list_page()
            opened = gui.open_first_doc()
            pos = gui._doc_position()
            log("   список: открылся=%s pos(Док/total)=%r title=%r"
                % (opened, pos, trunc(gui._doc_title(), 55)))
            gui.go_back(); time.sleep(0.6)
        except Exception as exc:  # noqa: BLE001
            log("   open_first_doc: %r" % exc)
    try:
        gui.close_extra_tabs(keep=1)
    except Exception:  # noqa: BLE001
        pass
    log("=== конец ===")
    return 0


def _visible_process_windows(gui):
    """[(hwnd, cls, title)] видимых верхнеуровневых окон процесса К+."""
    import win32gui
    import win32process
    hwnd = gui.win.handle
    pid = win32process.GetWindowThreadProcessId(hwnd)[1] if hwnd else None
    out = []

    def cb(h, _):
        if pid and win32process.GetWindowThreadProcessId(h)[1] == pid \
                and win32gui.IsWindowVisible(h):
            out.append((h, win32gui.GetClassName(h), win32gui.GetWindowText(h)))
        return True
    win32gui.EnumWindows(cb, None)
    return out


def _dump_controls(win_wrapper, limit=60):
    """Интерактивные контролы произвольного окна/панели (для диалога реквизитов)."""
    try:
        allc = win_wrapper.descendants()
    except Exception as exc:  # noqa: BLE001
        log("    ! descendants() упало: %r" % exc)
        return
    ctr = Counter(e.element_info.control_type for e in allc)
    log("    всего элементов: %d  |  %s" % (len(allc),
        "  ".join("%s=%d" % (k or "?", v) for k, v in ctr.most_common())))
    inter = [e for e in allc
             if e.element_info.control_type in
             ("Button", "ComboBox", "Edit", "DropDown", "CheckBox",
              "RadioButton", "Tab", "TabItem", "MenuItem", "Hyperlink",
              "Tree", "TreeItem", "List", "ListItem")
             and (e.element_info.name or e.element_info.automation_id)]
    log("    интерактивных (имя/aid): %d (показ %d)" % (len(inter), limit))

    def key(e):
        try:
            r = e.rectangle()
            return (r.top, r.left)
        except Exception:  # noqa: BLE001
            return (0, 0)
    for e in sorted(inter, key=key)[:limit]:
        i = e.element_info
        log("      [%-9s] aid=%-6r cls=%-18r %r %s%s"
            % (i.control_type, i.automation_id, trunc(i.class_name, 18),
               trunc(i.name, 55), _rect(e), _enabled(e)))


def _find_button_substr(gui, substr, top_lo=95, top_hi=200):
    """Видимая кнопка, имя содержит substr, в заданной полосе top (None=любой)."""
    best = None
    for b in gui.win.descendants(control_type="Button"):
        n = (b.element_info.name or "")
        if substr not in n:
            continue
        try:
            if not b.is_visible():
                continue
            r = b.rectangle()
        except Exception:  # noqa: BLE001
            continue
        if top_lo is None or top_lo <= r.top <= top_hi:
            best = best or (b, r, n)
    return best


def main_rekvizity():
    """Зонд «Уточнить по реквизитам» (пункт 3 §13.4): открыть диалог/панель
    уточнения по виду/номеру/дате документа и снять, читаемы ли её контролы UIA.
    Read-only: после снятия — Esc (отмена) и убрать лишние вкладки."""
    from pywinauto import Desktop
    from server.consultant_gui import ConsultantGUI
    log("=== зонд УТОЧНИТЬ ПО РЕКВИЗИТАМ (query=%r) ===" % QUERY)
    gui = ConsultantGUI()
    try:
        gui.connect(timeout=30)
    except Exception as exc:  # noqa: BLE001
        log("СТОП: %r" % exc); return 2
    gui.ensure_window(); gui.close_modal_dialogs(); gui.close_extra_tabs(keep=1)
    if not gui.do_search(QUERY):
        log("нет результатов"); return 3
    gui.open_all_results(); time.sleep(1.0)
    cats = gui.read_categories()
    leaf = next((c for c in cats if c.get("leaf") and c.get("count")), None)
    if leaf:
        try:
            gui.select_category(leaf["name"]); time.sleep(1.0)
        except Exception as exc:  # noqa: BLE001
            log("select_category: %r" % exc)
    gui.ensure_list_page()

    found = _find_button_substr(gui, "Уточнить")
    if not found:
        found = _find_button_substr(gui, "реквизит")
    if not found:
        log("кнопка «Уточнить по реквизитам» НЕ найдена в полосе top 95..200 "
            "— сниму всю страницу")
        _dump_controls(gui.win)
        return 4
    btn, r, n = found
    log("найдена кнопка: %r  %s" % (trunc(n, 70), _rect(btn)))

    before = {(h, c, t) for h, c, t in _visible_process_windows(gui)}
    try:
        btn.click_input(); time.sleep(1.6)
    except Exception as exc:  # noqa: BLE001
        log("клик упал: %r" % exc); return 5

    after = _visible_process_windows(gui)
    new_wins = [w for w in after if tuple(w) not in before]
    log("после клика — новые окна процесса: %d" % len(new_wins))
    for h, c, t in new_wins:
        log("  НОВОЕ окно hwnd=%s cls=%r title=%r" % (h, trunc(c, 24), trunc(t, 60)))

    if new_wins:
        # диалог = отдельное окно: обернуть и снять контролы
        for h, c, t in new_wins:
            log("\n  === контролы окна hwnd=%s (%r) ===" % (h, trunc(t, 50)))
            try:
                dlg = Desktop(backend="uia").window(handle=h).wrapper_object()
                _dump_controls(dlg)
            except Exception as exc:  # noqa: BLE001
                log("    ! не удалось снять окно: %r" % exc)
        # отмена: Esc по каждому новому окну
        for h, c, t in new_wins:
            try:
                Desktop(backend="uia").window(handle=h).wrapper_object().type_keys("{ESC}")
                time.sleep(0.6)
                log("    Esc -> окно hwnd=%s отправлен" % h)
            except Exception as exc:  # noqa: BLE001
                log("    Esc hwnd=%s упал: %r" % (h, exc))
    else:
        # раз новых окон нет — возможно, панель развернулась в самом окне: снять diff
        log("новых окон нет → проверяем, изменилось ли содержимое основного окна")
        _dump_controls(gui.win)
        try:
            gui.win.type_keys("{ESC}"); time.sleep(0.6)
        except Exception:  # noqa: BLE001
            pass

    # убедимся, что диалог закрыт
    still = [w for w in _visible_process_windows(gui) if tuple(w) not in before]
    log("после отмены осталось новых окон: %d" % len(still))
    for h, c, t in still:
        log("  ЗАЛИПЛО окно hwnd=%s cls=%r title=%r" % (h, trunc(c, 24), trunc(t, 60)))
    try:
        gui.close_modal_dialogs(); gui.close_extra_tabs(keep=1)
    except Exception:  # noqa: BLE001
        pass
    log("=== конец ===")
    return 0


def _flyout_listitem(gui, field, known):
    """В открывшемся флайауте (окно из `known`) найти ListItem с именем field."""
    from pywinauto import Desktop
    for h, _c, _t in _visible_process_windows(gui):
        if h in known:
            continue
        try:
            dlg = Desktop(backend="uia").window(handle=h).wrapper_object()
            for li in dlg.descendants(control_type="ListItem"):
                if (li.element_info.name or "").strip() == field:
                    return h, li
        except Exception:  # noqa: BLE001
            continue
    return None, None


def main_rekvizity_field():
    """На уровень глубже: выбрать в флайауте одно поле (rekvizity_field,
    по молчанию 'Номер') и снять, КАКОЙ ввод за ним прячется (Edit/ComboBox/
    список?) — от этого зависит реалистичность /search по реквизиту."""
    from pywinauto import Desktop
    from server.consultant_gui import ConsultantGUI
    field = os.environ.get("PROBE_FIELD", "Номер")
    log("=== зонд РЕКВИЗИТА-ПОЛЯ %r (query=%r) ===" % (field, QUERY))
    gui = ConsultantGUI()
    try:
        gui.connect(timeout=30)
    except Exception as exc:  # noqa: BLE001
        log("СТОП: %r" % exc); return 2
    gui.ensure_window(); gui.close_modal_dialogs(); gui.close_extra_tabs(keep=1)
    if not gui.do_search(QUERY):
        log("нет результатов"); return 3
    gui.open_all_results(); time.sleep(1.0)
    cats = gui.read_categories()
    leaf = next((c for c in cats if c.get("leaf") and c.get("count")), None)
    if leaf:
        try:
            gui.select_category(leaf["name"]); time.sleep(1.0)
        except Exception:  # noqa: BLE001
            pass
    gui.ensure_list_page()
    found = _find_button_substr(gui, "Уточнить") or _find_button_substr(gui, "реквизит")
    if not found:
        log("кнопки «Уточнить» нет"); return 4
    btn, _r, _n = found
    base = {h for h, _c, _t in _visible_process_windows(gui)}
    btn.click_input(); time.sleep(1.4)
    mid = {h for h, _c, _t in _visible_process_windows(gui)}
    flyout_new = mid - base
    log("флайаут открыт, новых окон: %d" % len(flyout_new))

    h, li = _flyout_listitem(gui, field, base)
    if li is None:
        log("поле %r в флайауте НЕ найдено" % field)
        for x in flyout_new:
            try:
                _dump_controls(Desktop(backend="uia").window(handle=x).wrapper_object(), 40)
            except Exception:  # noqa: BLE001
                pass
        for x in flyout_new:
            try:
                Desktop(backend="uia").window(handle=x).wrapper_object().type_keys("{ESC}")
            except Exception:  # noqa: BLE001
                pass
        return 5
    log("клик по ListItem %r (hwnd=%s) %s" % (field, h, _rect(li)))
    li.click_input(); time.sleep(1.6)
    after = {h2 for h2, _c, _t in _visible_process_windows(gui)}
    step2 = after - mid
    log("после выбора поля — ЕЩЁ новых окон: %d" % len(step2))
    for x in step2:
        log("  окно hwnd=%s" % x)
    # снимаем контролы всех активных попапов (2-й уровень + основной флайаут)
    for x in (step2 | flyout_new):
        log("\n  === контролы hwnd=%s ===" % x)
        try:
            _dump_controls(Desktop(backend="uia").window(handle=x).wrapper_object(), 50)
        except Exception as exc:  # noqa: BLE001
            log("    ! %r" % exc)
    log("  state основного окна после выбора поля: %r" % gui._state_suffix())
    # ВАЖНО: может, поле-инпут появился НЕ в попапе, а в самом окне — снять
    # интерактив основного окна (Edit/ComboBox с разумным rect в зоне флайаута).
    log("\n  === контролы ОСНОВНОГО окна после выбора поля ===")
    _dump_controls(gui.win, 80)
    edits = []
    for e in gui.win.descendants():
        ct = e.element_info.control_type
        if ct in ("Edit", "ComboBox", "DropDown"):
            try:
                r = e.rectangle()
                edits.append((ct, trunc(e.element_info.name, 40),
                              e.element_info.automation_id, (r.left, r.top)))
            except Exception:  # noqa: BLE001
                pass
    log("  Edit/ComboBox/DropDown в основном окне: %d" % len(edits))
    for ct, nm, aid, xy in edits[:40]:
        log("    [%s] aid=%r name=%r at=%r" % (ct, aid, nm, xy))
    # закрыться: Esc по попапам (обратно), потом закрыть флайаут
    for x in (step2 | flyout_new):
        try:
            Desktop(backend="uia").window(handle=x).wrapper_object().type_keys("{ESC}")
            time.sleep(0.5)
        except Exception:  # noqa: BLE001
            pass
    still = {h2 for h2, _c, _t in _visible_process_windows(gui)} - base
    log("после отмены осталось новых окон: %d" % len(still))
    try:
        gui.close_modal_dialogs(); gui.close_extra_tabs(keep=1)
    except Exception:  # noqa: BLE001
        pass
    log("=== конец ===")
    return 0


def run():
    mode = os.environ.get("PROBE_MODE", "").lower()
    if mode == "oglavlenie":
        return main_oglavlenie()
    if mode == "typefilter":
        return main_typefilter()
    if mode == "rekvizity":
        return main_rekvizity()
    if mode == "rekvizity_field":
        return main_rekvizity_field()
    from server.consultant_gui import ConsultantGUI
    log("=== разведка функций клиента К+ (query=%r) ===" % QUERY)
    gui = ConsultantGUI()
    try:
        gui.connect(timeout=30)
    except Exception as exc:  # noqa: BLE001
        log("СТОП: окно К+ не найдено: %r" % exc)
        return 2
    gui.ensure_window()
    gui.close_modal_dialogs()
    gui.close_extra_tabs(keep=1)

    dump_state(gui, "1) Стартовая / до поиска")

    if not gui.do_search(QUERY):
        log("  (!) do_search не привёл к результатам — снимаем только стартовую")
    else:
        gui.open_all_results()
        time.sleep(1.0)
        cats = gui.read_categories()
        leaf = next((c for c in cats if c.get("leaf") and c.get("count")), None)
        if leaf:
            try:
                gui.select_category(leaf["name"])
                time.sleep(1.0)
            except Exception as exc:  # noqa: BLE001
                log("  select_category: %r" % exc)
        allc = dump_state(gui, "2) Страница выдачи")
        dump_features(allc)

        gui.ensure_list_page()
        if gui.open_first_doc():
            time.sleep(1.2)
            allc = dump_state(gui, "3) Читалка документа (pos=%r)" % (gui._doc_position(),))
            dump_features(allc)
        else:
            log("\n  (!) читалка не открылась — тулбар документа не снят")

    try:
        gui.go_back()
        gui.close_extra_tabs(keep=1)
    except Exception:  # noqa: BLE001
        pass
    log("\n=== конец разведки ===")
    return 0


if __name__ == "__main__":
    try:
        rc = run()
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
