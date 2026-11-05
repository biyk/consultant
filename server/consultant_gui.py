# -*- coding: utf-8 -*-
"""Ядро GUI-автоматизации «КонсультантПлюс» поверх UIA (backend=uia).

Все операции строго последовательны (один GUI-поток); вызывающий код (app.py)
держит их под gui_lock. Окно может быть свёрнуто — перед действиями восстанавливаем.

Важные факты разведки (см. server/probe_*.py):
  * дерево разделов: Tree aid=1016, дети TreeItem "Имя\xa0COUNT";
  * поле поиска: Edit aid=1001 (старт) / aid=1063 (в ComboBox 341 на странице поиска);
  * «Найти»: Button aid=1 или 271; полная выдача: Button name "Все\xa0результаты\xa0поиска";
  * список материалов owner-drawn → заголовки читаем навигацией «Предыдущий/Следующий
    документ» + Edit-заголовок открытого документа (позиция "Док. N", "/total");
  * Ctrl+W → *.rtf в C:\\Temp (ждём новый rtf, *.tmp игнорируем).

Каждый шаг логируется в logs/server.log (см. logutil), чтобы по логу видеть, на
каком этапе возникает ошибка. Тела документов в лог НЕ пишутся — только счётчики
и короткие заголовки.
"""
import re
import time

import win32clipboard
import win32con
import win32gui
from pywinauto import Desktop
from pywinauto.uia_defines import IUIA  # noqa: F401  (прогрев comtypes-обёрток)

from . import config, rtf_util
from .logutil import get_logger

LOG = get_logger("gui")


class GuiError(Exception):
    pass


class NotFound(GuiError):
    pass


# Ярлыки вида «Судебная практика (Искать)» — элемент интерфейса, а не имя раздела
# (issue 5f6bfa0e4a5b): срезаем суффикс, иначе словарь разделов зависит от позиции.
_RE_UI_SUFFIX = re.compile(r"\s*\(\s*Искать\s*\)\s*$", re.IGNORECASE)
_RE_UI_ANYWHERE = re.compile(r"\(\s*Искать\s*\)", re.IGNORECASE)


# --- буфер обмена (кириллица без зависимости от раскладки) -------------------
def _clip_set_text(text):
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
    finally:
        win32clipboard.CloseClipboard()


def _clip_get_text():
    win32clipboard.OpenClipboard()
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        else:
            data = ""
    finally:
        win32clipboard.CloseClipboard()
    return data or ""


# --- low-level окно ----------------------------------------------------------
def _top_hwnds_by_class(cls):
    out = []

    def cb(h, _):
        if win32gui.GetClassName(h) == cls:
            out.append(h)
        return True

    win32gui.EnumWindows(cb, None)
    return out


class ConsultantGUI:
    def __init__(self):
        self._desktop = Desktop(backend="uia")
        self.win = None  # UIAWrapper главного окна

    # -- подключение / запуск --
    def connect(self, timeout=30):
        LOG.info("connect: жду окно class=%s", config.MAIN_WIN_CLASS)
        deadline = time.time() + timeout
        while time.time() < deadline:
            hwnds = _top_hwnds_by_class(config.MAIN_WIN_CLASS)
            if hwnds:
                try:
                    self.win = self._desktop.window(
                        class_name=config.MAIN_WIN_CLASS).wrapper_object()
                    LOG.info("connect: окно найдено, title=%r", self.title())
                    return self.win
                except Exception as exc:  # noqa: BLE001
                    LOG.debug("connect: перепоиск окна (%s)", exc)
            time.sleep(config.POLL)
        LOG.error("connect: окно НЕ найдено за %ss", timeout)
        raise NotFound("Окно ConsultantPlusMainWnd не найдено.")

    def close_modal_dialogs(self):
        """Закрыть мусорные модалки (#32770) процесса К+ ('Добавить в Избранное',
        'Найти' и т.п.), которые перехватывают фокус и ломают чтение дерева."""
        import win32process

        hwnd = self.win.handle if self.win is not None else None
        pid = win32process.GetWindowThreadProcessId(hwnd)[1] if hwnd else None
        found = []

        def cb(h, _):
            if win32gui.GetClassName(h) != "#32770":
                return True
            if not win32gui.IsWindowVisible(h):
                return True
            if pid is not None and win32process.GetWindowThreadProcessId(h)[1] != pid:
                return True
            found.append((h, win32gui.GetWindowText(h)))
            return True

        win32gui.EnumWindows(cb, None)
        for h, t in found:
            LOG.info("close_modal_dialogs: закрываю модалку %r", t)
            win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
        if found:
            time.sleep(0.5)
        return len(found)

    def ensure_window(self):
        if self.win is None:
            self.connect()
        hwnd = self.win.handle
        if win32gui.IsIconic(hwnd):
            LOG.debug("ensure_window: восстанавливаю свёрнутое окно hwnd=%s", hwnd)
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception as exc:  # noqa: BLE001
            LOG.debug("ensure_window: SetForegroundWindow не удалось: %s", exc)
        time.sleep(0.3)
        self.close_modal_dialogs()

    # -- общие локаторы --
    def _descendants(self, **kw):
        return self.win.descendants(**kw)

    def _button_by_name(self, needle, exact=False):
        for b in self._descendants(control_type="Button"):
            n = (b.element_info.name or "")
            if (n == needle) if exact else (needle in n):
                if b.is_visible():
                    return b
        raise NotFound(f"Кнопка не найдена: {needle!r}")

    def _edit_by_aid(self, aid):
        try:
            e = self.win.child_window(control_type="Edit", auto_id=aid).wrapper_object()
            if e.is_visible():
                return e
        except Exception:  # noqa: BLE001
            pass
        for e in self._descendants(control_type="Edit"):
            if e.element_info.automation_id == aid:
                return e
        raise NotFound(f"Edit aid={aid}")

    def _search_edit(self):
        for aid in (config.AID_SEARCH_EDIT2, config.AID_SEARCH_EDIT):
            try:
                return self._edit_by_aid(aid)
            except NotFound:
                continue
        # fallback: любой видимый Edit шириной > 600 в верхней части
        cands = [e for e in self._descendants(control_type="Edit")
                 if e.is_visible() and self._w(e) > 600 and e.rectangle().top < 400]
        if cands:
            LOG.info("_search_edit: сработал fallback по широкому Edit")
            return max(cands, key=self._w)
        raise NotFound("Поле поиска не найдено.")

    @staticmethod
    def _w(el):
        r = el.rectangle()
        return r.right - r.left

    # -- состояние/навигация --
    def title(self):
        try:
            return self.win.window_text() or ""
        except Exception:  # noqa: BLE001
            return ""

    def _state_suffix(self):
        t = self.title()
        m = re.search(r"\[(.+)\]\s*$", t)
        return m.group(1) if m else t

    # -- ввод текста через буфер (для кириллицы) --
    def set_search_text(self, text):
        edit = self._search_edit()
        r = edit.rectangle()
        LOG.info("search_edit aid=%s class=%s rect=(%s,%s,%s,%s)",
                 edit.element_info.automation_id, edit.element_info.class_name,
                 r.left, r.top, r.right, r.bottom)
        edit.click_input()
        time.sleep(0.2)
        entered = False
        # 1) надёжнее всего — ValuePattern.set_edit_text (для стандартного Edit)
        try:
            edit.set_edit_text("")
            edit.set_edit_text(text)
            entered = True
            LOG.info("set_edit_text: использован ValuePattern")
        except Exception as exc:  # noqa: BLE001
            LOG.debug("set_edit_text не сработал (%s) →clipboard", exc)
        # 2) фолбэк — вставка из буфера (кириллица без раскладки)
        if not entered:
            edit.click_input()
            time.sleep(0.2)
            edit.type_keys("^a{BACKSPACE}", pause=0.03, with_spaces=True)
            _clip_set_text(text)
            edit.type_keys("^v", pause=0.05)
            LOG.info("set_edit_text: использована вставка из буфера")
        time.sleep(0.25)
        try:
            got = (edit.window_text() or "")[:40]
        except Exception:  # noqa: BLE001
            got = "?"
        LOG.info("typed=%r readback=%r", text[:40], got)
        if not got:
            LOG.warning("readback пуст — текст мог НЕ попасть в поле (проверить фокус/метод ввода)")
        return edit

    def reset_for_search(self):
        """Чистый старт поиска: закрыть модалки/лишние вкладки и увести окно на
        страницу «Быстрый поиск» (поле aid=1063). После открытого документа иначе
        set_search_text попадает не в поле поиска → протечка состояния между запросами."""
        self.ensure_window()
        self.close_extra_tabs(keep=1)
        try:
            self._button_by_name("Быстрый поиск").click_input()
            time.sleep(0.8)
            LOG.info("reset_for_search: страница быстрого поиска открыта")
        except NotFound:
            LOG.info("reset_for_search: «Быстрый поиск» не найден — остаёмся как есть")

    def do_search(self, query):
        """Ввести запрос и нажать «Найти». Вернуть после появления результатов."""
        LOG.info("do_search query=%r", query[:60])
        self.reset_for_search()
        self.set_search_text(query)
        clicked = None
        for aid in (config.AID_BTN_FIND, config.AID_BTN_FIND_START):
            try:
                btn = self.win.child_window(control_type="Button",
                                            auto_id=aid).wrapper_object()
                if btn.is_visible():
                    btn.click_input()
                    clicked = "aid=" + aid
                    break
            except Exception:  # noqa: BLE001
                continue
        if not clicked:
            try:
                self._button_by_name(config.BTN_FIND_LABEL, exact=True).click_input()
                clicked = "name=Найти"
            except NotFound:
                pass
        if not clicked:
            self.win.type_keys("{ENTER}", pause=0.05)
            clicked = "ENTER"
        LOG.info("find_clicked=%s", clicked)
        ok = self.wait_results(query)
        LOG.info("wait_results=%s state=%r", ok, self._state_suffix())
        return ok

    def wait_results(self, query, timeout=None):
        """Ждать перехода на страницу результатов (заголовок «Поиск: …»).

        Дерево разделов здесь НЕ дожидаемся — оно появляется только после
        клика «Все результаты поиска» (см. wait_tree).
        """
        timeout = timeout or config.WAIT_RESULTS_TIMEOUT
        deadline = time.time() + timeout
        while time.time() < deadline:
            suf = self._state_suffix()
            if "Поиск:" in suf or (query[:6] and query[:6].lower() in suf.lower()):
                LOG.debug("wait_results: страница результатов (%r)", suf)
                return True
            time.sleep(config.POLL)
        LOG.warning("wait_results: таймаут %ss, состояние=%r", timeout, self._state_suffix())
        return "Поиск:" in self._state_suffix()

    def wait_tree(self, timeout=None):
        """Ждать, пока появится дерево разделов (Tree aid=1016) с хотя бы 1 ребёнком."""
        timeout = timeout or config.WAIT_TREE_TIMEOUT
        deadline = time.time() + timeout
        while time.time() < deadline:
            t = self._tree()
            if t is not None:
                try:
                    if len(t.children()) > 0:
                        LOG.debug("wait_tree: дерево готово, детей=%d", len(t.children()))
                        return t
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(config.POLL)
        LOG.warning("wait_tree: таймаут %ss — дерево разделов не появилось", timeout)
        return self._tree()

    # -- дерево разделов --
    def _tree(self):
        """Видимое дерево разделов (обычно aid=1016). child_window хрупок —
        сканируем descendants и берём первый видимый Tree."""
        for t in self._descendants(control_type="Tree"):
            try:
                if t.is_visible():
                    return t
            except Exception:  # noqa: BLE001
                continue
        return None

    def tree_items(self):
        tree = self._tree()
        if tree is None:
            LOG.warning("tree_items: Tree aid=%s НЕ найден/невидим", config.AID_TREE)
            return []
        out = []
        for it in tree.children():
            name = (it.element_info.name or "").replace("\xa0", " ")
            if name:
                out.append((it, name))
        LOG.info("tree_items: %d шт: %r", len(out), [n for _, n in out][:12])
        return out

    def read_categories(self):
        cats = []
        seen = {}
        for _, name in self.tree_items():
            name = name.replace("\u00a0", " ")
            name = re.sub(r"\s+", " ", _RE_UI_ANYWHERE.sub(" ", _RE_UI_SUFFIX.sub("", name))).strip()
            if not name:
                continue
            m = re.match(r"^(.*?)[\s\u00a0]+(\u2265?\s*[\d\s]+)$", name)
            if m:
                label = m.group(1).strip()
                raw = m.group(2).strip()
                digits = re.sub(r"\D", "", raw)
                count = int(digits) if digits and "\u2265" not in raw else (int(digits) if digits else None)
                rec = {"name": label, "count": count,
                       "raw_count": raw, "leaf": True}
            else:
                rec = {"name": name, "count": None,
                       "raw_count": "", "leaf": False}
            prev = seen.get(rec["name"])
            if prev is None:
                seen[rec["name"]] = rec
                cats.append(rec)
            elif (rec["count"] or 0) > (prev["count"] or 0):
                prev["count"] = rec["count"]
                prev["raw_count"] = rec["raw_count"]
                prev["leaf"] = prev["leaf"] or rec["leaf"]
        LOG.info("read_categories: %d разделов", len(cats))
        return cats

    def select_category(self, name):
        """Клик по TreeItem с подходящим именем; НЕ жмём Enter (чтоб не открыть doc)."""
        target = None
        nl = (name or "").lower().strip()
        for it, nm in self.tree_items():
            if nl and (nl in nm.lower() or nm.lower().startswith(nl)):
                target = it
                break
        if target is None:
            LOG.error("select_category: не найден TreeItem для %r", name)
            raise NotFound(f"Раздел не найден: {name!r}")
        target.click_input()
        LOG.info("select_category: выбран %r", name)
        time.sleep(0.6)
        return True

    def open_all_results(self, wait_button=None):
        """Клик по «Все результаты поиска» (ждём появления кнопки)."""
        wait_button = wait_button or 8.0
        deadline = time.time() + wait_button
        btn = None
        while time.time() < deadline:
            try:
                btn = self._button_by_name("Все\xa0результаты\xa0поиска")
                break
            except NotFound:
                if self._tree() is not None:
                    LOG.info("open_all_results: кнопка не нужна — дерево уже открыто")
                    return True
                time.sleep(config.POLL)
        if btn is None:
            has = self._tree() is not None
            LOG.warning("open_all_results: кнопка «Все результаты» не дождались; tree=%s", has)
            return has
        btn.click_input()
        LOG.info("open_all_results: клик по «Все результаты поиска» выполнен")
        time.sleep(1.5)
        return True

    def page_info(self):
        """Снимок текущей страницы: состояние окна + позиция читалки. Нужен, чтобы
        честными данными отвечать, живём ли мы на списке THIS запроса
        (issues aa213ed6f361, bb9515a15b8e)."""
        cur, total = (None, None)
        try:
            cur, total = self._doc_position()
        except Exception:  # noqa: BLE001
            pass
        return {"state": self._state_suffix(), "doc_index": cur, "doc_total": total}

    # -- область открытого документа (для заголовков и позиции) --
    def _doc_title(self):
        bad = ("Сортировка", "Профиль", "Результаты", "Наиболее", "См. также", "©",
               "Быстрый поиск", "Уточнить")
        cands = []
        for e in self._descendants(control_type="Edit"):
            nm = (e.element_info.name or "").strip()
            if not nm or len(nm) < 4:
                continue
            if any(b in nm for b in bad):
                continue
            r = e.rectangle()
            if r.top < 320 and (r.right - r.left) > 300:
                cands.append((r.top, -self._w(e), nm))
        if cands:
            cands.sort()
            return cands[0][2]
        t = self._state_suffix()
        if t.startswith("Поиск:") or t.startswith("Стартовая"):
            return ""
        return t

    def _doc_position(self):
        """(N, total) из Edits 'Док. N' и '/total'; иначе (None, None)."""
        n = total = None
        for e in self._descendants(control_type="Edit"):
            nm = (e.element_info.name or "").replace("\xa0", " ")
            m = re.search(r"Док\.?\s*(\d+)", nm)
            if m:
                n = int(m.group(1))
            m2 = re.search(r"/\s*([\d\s]+)$", nm.strip())
            if m2 and re.sub(r"\D", "", m2.group(1)):
                total = int(re.sub(r"\D", "", m2.group(1)))
        return n, total

    def _nav_button(self, needle):
        try:
            return self._button_by_name(needle)
        except NotFound:
            return None

    def next_doc(self):
        b = self._nav_button(config.BTN_NEXT_DOC)
        if b is None:
            LOG.warning("next_doc: кнопка «%s» не найдена", config.BTN_NEXT_DOC)
            return False
        b.click_input()
        time.sleep(0.8)
        return True

    def prev_doc(self):
        b = self._nav_button(config.BTN_PREV_DOC)
        if b is None:
            LOG.warning("prev_doc: кнопка «%s» не найдена", config.BTN_PREV_DOC)
            return False
        b.click_input()
        time.sleep(0.8)
        return True

    def goto_doc_index(self, target_abs):
        """Листанием Prev/Next дойти до абсолютного индекса (1-based) в выдаче."""
        cur, _ = self._doc_position()
        LOG.debug("goto_doc_index: старт cur=%s target=%s", cur, target_abs)
        if cur is None:
            return False
        guard = 0
        while cur != target_abs and guard < 500:
            ok = self.next_doc() if cur < target_abs else self.prev_doc()
            if not ok:
                return False
            new, _ = self._doc_position()
            if new is None or new == cur:
                break
            cur = new
            guard += 1
        LOG.debug("goto_doc_index: итог cur=%s достигнут=%s", cur, cur == target_abs)
        return cur == target_abs

    def ensure_doc_open(self, target_abs):
        """Гарантировать, что читалка открыта и активен документ target_abs.
        Если позиции 'Док.N' нет (мы на странице списка) — открыть первый документ,
        затем дойти до target листанием. Возвращает финальную cur (или None)."""
        cur, _ = self._doc_position()
        if cur is None:
            LOG.info("ensure_doc_open: читалка закрыта — открываю первый документ")
            self.open_first_doc()
            cur, _ = self._doc_position()
        if cur is not None and cur != target_abs:
            self.goto_doc_index(target_abs)
            cur, _ = self._doc_position()
        return cur

    def open_first_doc(self, x=900, y=300):
        """Открыть первый документ списка двойным кликом (перевод в читалку).
        Без этого enumerate/next_doc не работают: на странице списка нет 'Док.N'."""
        self.ensure_window()
        LOG.info("open_first_doc: dbl-click (%s,%s)", x, y)
        self.win.click_input(coords=(x, y), double=True)
        time.sleep(2.5)
        cur, total = self._doc_position()
        LOG.info("open_first_doc: pos=%s/%s", cur, total)
        return cur is not None

    def enumerate_titles(self, start_abs, count):
        """Вернуть [(abs_index, title)] для документов выдачи [start_abs, start_abs+count)."""
        LOG.info("enumerate_titles start_abs=%s count=%s", start_abs, count)
        res = []
        cur0, _t0 = self._doc_position()
        if cur0 is None:
            # читалка не открыта (мы на странице списка) — открыть первый документ
            LOG.info("enumerate_titles: читалка не открыта — открываю первый документ")
            self.open_first_doc()
        got = self.goto_doc_index(start_abs)
        cur, total = self._doc_position()
        LOG.info("enumerate_titles: goto=%s cur=%s total=%s", got, cur, total)
        if cur is None:
            # Позицию 'Док.N' прочитать не удалось → читалка НЕ на этом списке.
            # Собирать заголовки в этом случае — значит выдать список предыдущего
            # запроса (issues bb9515a15b8e, f3aa36f9a116) — честно возвращаем пусто.
            LOG.warning("enumerate_titles: позиция 'Док.N' не читается — отдаём пустой список")
            return []
        for i in range(count):
            title = self._doc_title()
            idx = cur if cur is not None else start_abs + i
            res.append((idx, title))
            LOG.debug("  doc idx=%s titlelen=%s head=%r", idx, len(title), title[:50])
            if i < count - 1:
                if not self.next_doc():
                    LOG.warning("  next_doc() failed on i=%s", i)
                    break
                nxt, _ = self._doc_position()
                if nxt is None or nxt == cur:
                    LOG.warning("  позиция всталась на i=%s (cur=%s) — обрыв навигации", i, cur)
                    break
                cur = nxt
        LOG.info("enumerate_titles: собрано %d заголовков", len(res))
        return res

    # -- экспорт текста открытого документа --
    def _close_wordpad(self):
        """Закрыть окна WordPad (class WordPadClass) от Ctrl+W. Документ уже в
        C:\Temp — WordPad не нужен. WM_CLOSE может блокироваться модалкой
        безопасности, поэтому добиваем процесс."""
        import subprocess

        hwnds = []

        def cb(h, _):
            if win32gui.GetClassName(h) == "WordPadClass":
                hwnds.append(h)
            return True

        win32gui.EnumWindows(cb, None)
        for h in hwnds:
            try:
                win32gui.PostMessage(h, win32con.WM_CLOSE, 0, 0)
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.8)
        # остались? (модалка блокирует закрытие) — убиваем процесс
        still = []
        win32gui.EnumWindows(lambda h, _: still.append(h)
                             if win32gui.GetClassName(h) == "WordPadClass" else None, None)
        if still:
            LOG.info("_close_wordpad: %d окон не закрылись (модалка) — taskkill wordpad", len(still))
            try:
                subprocess.run(["taskkill", "/IM", "wordpad.exe", "/F"],
                               capture_output=True, timeout=10)
            except Exception as exc:  # noqa: BLE001
                LOG.warning("_close_wordpad: taskkill не удался: %s", exc)
            time.sleep(0.4)
            return len(still)
        if hwnds:
            LOG.info("_close_wordpad: закрыто окон WordPad: %d", len(hwnds))
        return len(hwnds)

    def export_current_doc(self, key):
        """Экспорт в Word → K+ пишет export_*.RTF в C:\Temp и открывает WordPad.
        Ждём файл, закрываем WordPad, возвращаем (title, text)."""
        self.ensure_window()
        before = rtf_util.snapshot_rtf()
        LOG.info("export_current_doc: snapshot rtf до экспорта: %d", len(before))
        try:
            self._button_by_name("Экспорт в Word").click_input()
            LOG.info("export_current_doc: клик по кнопке «Экспорт в Word»")
        except NotFound:
            from pywinauto.keyboard import send_keys
            send_keys("^w")
            LOG.info("export_current_doc: отправлен Ctrl+W (global)")
        path = rtf_util.wait_new_rtf(before)
        # WordPad больше не нужен — закрываем НЕЗАВИСИМО от результата чтения файла
        self._close_wordpad()
        if not path:
            LOG.error("export_current_doc: RTF не появился за таймаут")
            raise GuiError("RTF не появился после экспорта в Word (таймаут).")
        LOG.info("export_current_doc: получен RTF=%s", path)
        rtf_util.ingest(path, key)
        text = rtf_util.rtf_to_clean_text(path=path)
        links = rtf_util.extract_links(path)
        LOG.info("export_current_doc: текст %d симв., links %d", len(text), len(links))
        title = self._doc_title() or self._state_suffix()
        return title, text, links

    # -- навигация по стеку --
    def go_back(self):
        self.ensure_window()
        b = self._nav_button(config.BTN_BACK)
        if b is None:
            LOG.info("go_back: кнопка «Назад» не найдена — Alt+Left")
            self.win.type_keys("%{LEFT}", pause=0.05)
            return True
        b.click_input()
        LOG.info("go_back: клик по «Назад»")
        time.sleep(1.0)
        return True

    # -- гигиена: закрытие лишних вкладок (не плодить сущности, см. todo §11) --
    def _tab_items(self):
        """TabItem реальной панели вкладок. Берём Tab-контрол с максимумом TabItem
        (child_window+auto_id на странице результатов ненадёжен)."""
        best = []
        for t in self._descendants(control_type="Tab"):
            items = [ti for ti in t.children()
                     if ti.element_info.control_type == "TabItem"]
            if len(items) > len(best):
                best = items
        return best

    def tabs(self):
        return [(ti.element_info.name or "") for ti in self._tab_items()]

    def close_extra_tabs(self, keep=1, max_iters=40):
        """Закрыть все вкладки, кроме первых `keep`. Возвращает финальное число вкладок."""
        self.ensure_window()
        iters = 0
        tabs = self._tab_items()
        LOG.info("close_extra_tabs: было %d вкладок (keep=%s)", len(tabs), keep)
        while len(tabs) > keep and iters < max_iters:
            iters += 1
            victim = tabs[-1]
            try:
                victim.click_input()
                time.sleep(0.3)
            except Exception:  # noqa: BLE001
                pass
            before = len(tabs)
            try:
                self.win.type_keys("^{F4}", pause=0.1)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.6)
            tabs = self._tab_items()
            if len(tabs) >= before:
                closed = False
                try:
                    for btn in victim.children(control_type="Button"):
                        if (btn.element_info.name or "") == "Закрыть":
                            btn.click_input()
                            closed = True
                            break
                except Exception:  # noqa: BLE001
                    pass
                if closed:
                    time.sleep(0.6)
                    tabs = self._tab_items()
                else:
                    LOG.warning("close_extra_tabs: не удалось закрыть вкладку — стоп")
                    break
        LOG.info("close_extra_tabs: стало %d вкладок", len(tabs))
        return len(tabs)

    def get_state(self):
        tabs = []
        try:
            tabbar = self.win.child_window(control_type="Tab",
                                           auto_id=config.AID_TABBAR).wrapper_object()
            for ti in tabbar.children():
                if ti.element_info.control_type == "TabItem":
                    tabs.append(ti.element_info.name)
        except Exception:  # noqa: BLE001
            pass
        cur, total = (None, None)
        try:
            cur, total = self._doc_position()
        except Exception:  # noqa: BLE001
            pass
        return {
            "title": self.title(),
            "state": self._state_suffix(),
            "tabs": [t for t in tabs if t],
            "doc_index": cur,
            "doc_total": total,
        }
