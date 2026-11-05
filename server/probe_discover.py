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


def run():
    if os.environ.get("PROBE_MODE", "").lower() == "oglavlenie":
        return main_oglavlenie()
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
