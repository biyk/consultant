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


def _norm_title(s):
    """Свернённое сравнение имён: кавычки/«ёлочки»/NBSP/пробелы не важны.
    Нужно, чтобы опознать «это эхо запроса, а не заголовок документа»."""
    s = (s or "").replace("\u00a0", " ").replace("\u201c", '"').replace("\u201d", '"')
    s = re.sub(r"[\"'\u00ab\u00bb\s]+", " ", s)
    return s.strip().lower()


# Уровень пункта оглавления по началу заголовка (К+: Раздел/Часть → Глава →
# Статья/§/пункт). Совсем не обязательная эвристика: level — подсказка, главный
# смысл — упорядоченный список заголовков структуры.
_TOC_LEVEL_PATTERNS = (
    (re.compile(r"^\s*(\u0440\u0430\u0437\u0434\u0435\u043b|\u0447\u0430\u0441\u0442\u044c|\u043f\u043e\u0434\u0440\u0430\u0437\u0434\u0435\u043b)\b", re.I), 0),
    (re.compile(r"^\s*\u0433\u043b\u0430\u0432\u0430\b", re.I), 1),
    (re.compile(r"^\s*(\u0441\u0442\u0430\u0442\u044c\u044f|\u00a7|\u043f\u0443\u043d\u043a\u0442|\u0441\u0442\.\s|\u043f\.\s)|^\s*\d+\.\d+", re.I), 2),
)


def _toc_level(title):
    for rx, lvl in _TOC_LEVEL_PATTERNS:
        if rx.search(title or ""):
            return lvl
    return 1


def parse_toc_entries(items):
    """Из строк дерева оглавления [(name, left), …] (в визуальном порядке сверху
    вниз) — чистый список [{title, level}]. Только ЧИСТАЯ функция (без GUI): её
    можно тестировать офлайн. Пустые/пробельные имена отбрасываются, nbsp
    сворачивается в обычный пробел, порядок сохраняется."""
    out = []
    for name, _left in items:
        t = (name or "").replace("\u00a0", " ")
        t = re.sub(r"\s+", " ", t).strip()
        if not t:
            continue
        out.append({"title": t, "level": _toc_level(t)})
    return out


# --- привязка пунктов оглавления к кускам текста (ЧИСТЫЕ, без GUI) -----------
# Офлайн-разведка (§13.4 п.5): на реальном КоАП ВСЕ пункты /toc встречаются в
# экспортированном тексте /doc (38/38), поэтому подраздел можно достать резкой
# текста по заголовкам — детерминированно и без рискованной навигации по дереву
# (клик по пункту оглавления ломает читалку / открывает UIA-невидимые модалки).
_RE_TOC_LABEL = re.compile(
    r"\b(\u0440\u0430\u0437\u0434\u0435\u043b|\u0433\u043b\u0430\u0432\u0430|"
    r"\u0441\u0442\u0430\u0442\u044c\u044f|\u0447\u0430\u0441\u0442\u044c|"
    r"\u043f\u0430\u0440\u0430\u0433\u0440\u0430\u0444|\u043f\u0443\u043d\u043a\u0442)"
    r"\.?\s+", re.I)


def _norm_ws(s):
    """Нормализация для матчинга заголовков: nbsp→пробел, схлоп пробелов, lower."""
    s = (s or "").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", s).strip().lower()


def _iter_line_offsets(text):
    """[(start_offset, line), …] по text (line без переноса строк)."""
    out, pos = [], 0
    for ln in text.splitlines(keepends=True):
        body = ln.rstrip("\r\n")
        out.append((pos, body))
        pos += len(ln)
    return out


def _prefix_bounded(longer, shorter):
    """`longer` начинается с `shorter`, и сразу за префиксом — НЕ цифра.
    Нужно, чтобы «глава 1» не матчилось на «глава 11.» (юридически разные
    разделы; ложный анкоринг хуже честного пропуски)."""
    if not shorter or not longer.startswith(shorter):
        return False
    if len(longer) == len(shorter):
        return True
    nxt = longer[len(shorter)]
    return not nxt.isdigit()


def _has_number_token(s):
    """В строке есть номерной токен: арабская цифра или римская цифра
    (I/II/III/IV/V/… с границей слова). Нужно для reverse-префикса,
    чтобы случайная фраза «см. главу» не привязывалась к «Глава 12. ...».
    Регистронезависимо: вход уже пройдёт через _norm_*, где lowercase."""
    if not s:
        return False
    if any(c.isdigit() for c in s):
        return True
    return bool(re.search(r"(?:^|\s)(?=[IVXLCDM]{1,8}(?:\s|$|\.|,))", s, re.I))


def _norm_line(s):
    """Норма строки текста заголовка: убрать висячую точку-маркер конца.
    «Глава 1. Задачи.» и «Глава 1. Задачи» должны сравниваться одинаково."""
    s = _norm_ws(s)
    return s.rstrip(".")


def slice_sections(text, toc):
    """Привязать упорядоченные пункты оглавления к диапазонам символов текста.

    ЧИСТАЯ функция — тестируется офлайн. Каждый заголовок ищется НА НАЧАЛЕ
    СТРОКИ и монотонно: следующий ищем не раньше конца предыдущего найденного.
    Поэтому случайное упоминание вида «…см. главу 1…» внутри чужого тела
    заголовком не считается. Возвращает список по порядку toc:
    {title, level, start, end, found}; для найденных end — start следующего
    найденного (или len(text)). start/end — индексы среза text[start:end].

    Матчинг двусторонний с границей числа (см. _prefix_bounded): в К+ заголовок
    в теле документа бывает КОРОЧЕ, чем в оглавлении (разрыв строки UIA, «…»
    в конце строки toc), и наоборот. На реальном КоАПе 30/38 заголовков toc
    длиннее своих строк в тексте («Глава 1. Задачи и принципы законодательства
    об административных правонарушениях» vs «Глава 1. ЗАДАЧИ И ПРИНЦИПЫ
    ЗАКОНОДАТЕЛЬСТВА»), поэтому reverse-префикс критичен. Требование
    номерного токена (_has_number_token) в короткой стороне не даёт ложных
    якорей для строк вида «см. также главу» / «приложение»."""
    if not text or not toc:
        return []
    lines = _iter_line_offsets(text)
    nlines = [_norm_line(ln) for _, ln in lines]
    nlines_strip = [_norm_ws(_RE_TOC_LABEL.sub("", nl)) for nl in nlines]
    ptr, spans = 0, []
    for e in toc:
        title = e.get("title") or ""
        key = _norm_line(title)
        key_strip = _norm_ws(_RE_TOC_LABEL.sub("", key))
        found_at = None
        if key:
            # pass 1: строгий префикс — строка текста длиннее заголовка toc
            #           (в toc усечённая форма, в тексте полная)
            # pass 2: reverse-префикс — заголовок toc длиннее строки текста
            #           (обычный случай К+: toc даёт полный long-name)
            # Оба — с границей числа и требованием номерного токена в
            # короткой стороне.
            for li in range(ptr, len(lines)):
                nl = nlines[li]
                if not nl:
                    continue
                if nl == key:
                    found_at = li; break
                if _prefix_bounded(nl, key):
                    found_at = li; break
                if _prefix_bounded(key, nl) and _has_number_token(nl):
                    found_at = li; break
            # pass 3: снятие служебного слова («глава/ст.») с обеих сторон
            if found_at is None and key_strip:
                for li in range(ptr, len(lines)):
                    nl = nlines_strip[li]
                    if not nl:
                        continue
                    if nl == key_strip:
                        found_at = li; break
                    if _prefix_bounded(nl, key_strip):
                        found_at = li; break
                    if _prefix_bounded(key_strip, nl) and _has_number_token(nl):
                        found_at = li; break
        if found_at is None:
            spans.append({"title": title, "level": e.get("level"),
                          "start": None, "end": None, "found": False})
        else:
            spans.append({"title": title, "level": e.get("level"),
                          "start": lines[found_at][0], "end": None, "found": True})
            ptr = found_at + 1
    found_idx = [i for i, s in enumerate(spans) if s["found"]]
    for j, i in enumerate(found_idx):
        nxt = found_idx[j + 1] if j + 1 < len(found_idx) else None
        spans[i]["end"] = spans[nxt]["start"] if nxt is not None else len(text)
    return spans


def pick_section(text, toc, want):
    """Текст ОДНОГО раздела по названию/номеру want (например «Глава 4» или
    «ст. 12.1»). ЧИСТАЯ. Совпадение ранжируется: точное равенство нормы >
    заголовок НАЧИНАЕТСЯ с want на границе слова/числа > то же со снятием
    служебных слов («глава/ст.»). Граница обязательна: «Глава 1» НЕ должно
    матчиться на «Глава 11» (нумерация статей/глав — юридически разные
    разделы, неверная выдача хуже честного отказа). Возвращает {title, level,
    start, end, text, text_len} или None, если раздел не найден (тогда calling
    код честно перечислит доступные заголовки, а не выдумает текст)."""
    spans = [s for s in slice_sections(text, toc) if s["found"]]
    w = _norm_ws(want)
    if not spans or not w:
        return None
    ws = _norm_ws(_RE_TOC_LABEL.sub("", w))

    def _pick(pred):
        for s in spans:
            if pred(_norm_ws(s["title"])):
                return s
        return None

    def _prefix_boundary(t, pfx):
        # t начинается с pfx, и дальше — НЕ цифра (граница номера/слова)
        return t.startswith(pfx) and (len(t) == len(pfx) or not t[len(pfx)].isdigit())

    matched = _pick(lambda t: t == w)
    if matched is None:
        matched = _pick(lambda t: _prefix_boundary(t, w))
    if matched is None and ws:
        matched = _pick(lambda t: _prefix_boundary(
            _norm_ws(_RE_TOC_LABEL.sub("", t)), ws))
    if matched is None:
        return None
    body = text[matched["start"]:matched["end"]].rstrip("\r\n")
    return {"title": matched["title"], "level": matched["level"],
            "start": matched["start"], "end": matched["end"],
            "text": body, "text_len": len(body)}


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
    def _doc_title(self, query_flat=None):
        """Заголовок открытого документа. query_flat — нормализованный текст
        текущего запроса; поля поиска ОБЯЗАТЕЛЬНО отбрасываются: иначе, когда
        читалка пуста, вместо заголовка возвращается сам запрос («эхо»), и
        выдача превращается в N одинаковых строк (зонд: 'обзор судебной
        практики верховный суд' ×3)."""
        bad = ("Сортировка", "Профиль", "Результаты", "Наиболее", "См. также", "©",
               "Быстрый поиск", "Уточнить")
        search_aids = (config.AID_SEARCH_EDIT, config.AID_SEARCH_EDIT2)
        cands = []
        for e in self._descendants(control_type="Edit"):
            nm = (e.element_info.name or "").strip()
            if not nm or len(nm) < 4:
                continue
            if any(b in nm for b in bad):
                continue
            if (e.element_info.automation_id or "") in search_aids:
                continue                      # поле поиска, не заголовок
            flat = _norm_title(nm)
            # Отбрасываем только ВЕРБАТИМ-эхо запроса (чип/поле = сам запрос).
            # Раньше гасился ЛЮБОЙ заголовок, СОДЕРЖАЩИЙ запрос — но реальные
            # документы попадают в выдачу именно потому, что в их названии есть
            # слова поиска
            # (зонд main_titles: при запросе «ставка» заголовок на top=179
            # «Справочная информация: "Ключевая ставка и процентная ставка…"»
            # терялся как «эхо», и _doc_title возвращал полосу раздела
            # «Российское законодательство (Версия Проф)» на top=191).
            if query_flat and flat and flat == query_flat:
                continue                      # чип/поле = сам запрос, не заголовок
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
        """(N, total) счётчика «Док. N» / «/total» — позиция в СПИСКЕ выдачи.

        В нижней строке состояния ДВА парных счётчика:
            «Док. 3» «/1588»   — документ и объём списка раздела
            «Абз. 2668» «/10061» — абзац и объём всего результата поиска
        Раньше total брался из ПОСЛЕДНЕГО совпадения «/число», то есть в него
        попадало число АБЗАЦЕВ (10061 вместо 1588): сверка «объём открытого
        списка == объём раздела» была обречена, а /search отдавал чужие числа
        (issues e7f7bb098cfd, e15c0d424393). Теперь пару ищем геометрически:
        ближайший «/N» ПРАВЕЕ счётчика «Док.» (у «Абз.» свой left — левее
        него мы не переходим)."""
        edits = []
        for e in self._descendants(control_type="Edit"):
            nm = (e.element_info.name or "").replace("\u00a0", " ").strip()
            if not nm:
                continue
            try:
                left = e.rectangle().left
            except Exception:  # noqa: BLE001
                left = None
            edits.append((left, nm))

        n, doc_left, doc_pos = None, None, None
        for pos, (left, nm) in enumerate(edits):
            m = re.search(r"Док\.?\s*(\d+)", nm)
            if m:
                n = int(m.group(1))
                doc_left, doc_pos = left, pos
                break
        total = None
        # 1) по геометрии: ближайший «/N» правее «Док.»
        if doc_left is not None:
            cands = [(l, nm) for (l, nm) in edits
                     if l is not None and l > doc_left and
                     re.fullmatch(r"/\s*[\d\s]+", nm)]
            cands.sort(key=lambda t: t[0])
            if cands:
                total = int(re.sub(r"\D", "", cands[0][1]))
        # 2) запасной вариант: порядок обхода элементов как список
        if total is None and doc_pos is not None:
            for _left, nm in edits[doc_pos + 1:]:
                if re.search(r"Абз\.?\s*\d+", nm):
                    break                     # дальше счётчик абзацев — не сюда
                m2 = re.search(r"/\s*([\d\s]+)$", nm)
                if m2 and re.sub(r"\D", "", m2.group(1)):
                    total = int(re.sub(r"\D", "", m2.group(1)))
                    break
        # 3) «Док.» вообще не прочитался — прежний общий поиск total
        if doc_pos is None:
            for _left, nm in edits:
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

    def list_pane_rect(self):
        """Прямоугольник области СПИСКА выдачи. Сам список — owner-drawn Pane
        (class Afx:..., aid 59648) без UIA-детей, строк через UIA не прочитать
        (проверено зондом), поэтому хотя бы кликать надо по НЕЙ, а не по
        жёстким координатам окна: на странице быстрой выдачи (900,300) попадает
        в полосу «Наиболее соответствуют запросу», и двойной клик не открывает
        НИЧЕГО (issue e15c0d424393). Берём самый «глубокий» (с наибольшим top)
        крупный контейнер правее шапки — это внутренняя область контента."""
        best = None
        for t in ("Pane", "Window"):
            for e in self._descendants(control_type=t):
                i = e.element_info
                if i.class_name in ("MDIClient",) or (i.name or ""):
                    continue          # не рабочая область и не именованные окна
                try:
                    r = e.rectangle()
                except Exception:  # noqa: BLE001
                    continue
                if r.width() < 700 or r.height() < 350 or r.top < 230:
                    continue
                key = (r.top, r.width() * r.height())
                if best is None or key > best[0]:
                    best = (key, r)
        return best[1] if best else None

    def ensure_list_page(self, max_back=2):
        """Уйти из читалки на страницу списка. Если 'Док.N' читается — открыт
        документ (легко — из СТАРОЙ вкладки), и клик по списку тогда ничего не
        меняет: enumerate начал бы листать чужой список и выдал бы его за выдачу
        (именно так шаг 2 живой проверки отдавал 31 документ вместо 1588)."""
        n = 0
        while self._doc_position()[0] is not None and n < max_back:
            LOG.info("ensure_list_page: открыт документ %s — жму «Назад»",
                     self._doc_position())
            try:
                self.go_back()
            except Exception as exc:  # noqa: BLE001
                LOG.warning("ensure_list_page: «Назад» не прошёл: %r", exc)
                break
            n += 1
        return self._doc_position()[0] is None

    def open_first_doc(self, x=900, y=300, row_step=37, tries=4):
        """Открыть первый документ списка ДВОЙНЫМ КЛИКОМ с ПРОВЕРКОЙ.
        Возвращает True только если клик реально открыл (другой) список:
        сверяем 'Док.N/total' до и после. Раньше это был один клик вслепую
        по (900,300), после которого перечисление молча листало любой
        ранее открытый документ (issues e15c0d424393, e7f7bb098cfd).

        Порядок точек — по живой проверке (зонды main_grid/main_titles): на этой
        сборке К+ первая строка результата лежит в полосе «Наиболее соответствуют
        запросу» (~y=300 при x=900), а pane-область списка начинается НИЖЕ
        (top≈339), и клики по её отступам открывают НЕ тот подсписок. Поэтому
        доказанная точка идёт ПЕРВОЙ, а pane-точки — запасными для других
        раскладок/DPI. Надёжность не в порядке, а в проверке: True лишь если
        'Док.N' реально изменился, иначе честно возвращаем False."""
        self.ensure_window()
        self.ensure_list_page()
        before = self._doc_position()
        pane = self.list_pane_rect()
        points = [(x, y)]              # доказанная первая строка — первой попыткой
        if pane is not None:
            LOG.info("open_first_doc: область списка %s", pane)
            for k in range(tries):
                p = (pane.left + 300, pane.top + 25 + row_step * k)
                if p not in points:
                    points.append(p)   # запасные точки — для других раскладок
        for (px, py) in points:
            LOG.info("open_first_doc: dbl-click (%s,%s)", px, py)
            try:
                self.win.click_input(coords=(px, py), double=True)
            except Exception as exc:  # noqa: BLE001
                LOG.warning("open_first_doc: клик не прошёл: %r", exc)
            time.sleep(1.5)
            cur = self._doc_position()
            if cur[0] is not None and cur != before:
                LOG.info("open_first_doc: pos=%s/%s (до клика было %s/%s)",
                         cur[0], cur[1], before[0], before[1])
                return True
            time.sleep(0.5)
        LOG.warning("open_first_doc: ни одна точка не открыла список "
                    "(до=%s после=%s) — на странице списка нас, скорее всего, "
                    "нет", before, self._doc_position())
        return False

    def enumerate_titles(self, start_abs, count, query_flat=None, expect_total=None):
        """Вернуть [(abs_index, title)] для документов выдачи [start_abs, start_abs+count).
        query_flat — нормализованный запрос: нужен, чтобы не выдать эхо поля
        поиска за заголовок документа.
        expect_total — сколько документов должен содержать список (count выбранного
        раздела): если читалка показывает ДРУГОЙ объём, мы листаем не тот список
        (старая вкладка/карточка), и заголовки не отдаём (issue e7f7bb098cfd)."""
        LOG.info("enumerate_titles start_abs=%s count=%s expect_total=%s",
                 start_abs, count, expect_total)
        res = []
        cur0, _t0 = self._doc_position()
        if cur0 is None:
            # читалка не открыта (мы на странице списка) — открыть первый документ
            LOG.info("enumerate_titles: читалка не открыта — открываю первый документ")
            if not self.open_first_doc():
                LOG.warning("enumerate_titles: открытие строки списка не состоялось — "
                            "заголовки не читаем (иначе отдадим чужой список)")
                return []
        got = self.goto_doc_index(start_abs)
        cur, total = self._doc_position()
        LOG.info("enumerate_titles: goto=%s cur=%s total=%s", got, cur, total)
        if cur is None:
            # Позицию 'Док.N' прочитать не удалось → читалка НЕ на этом списке.
            # Собирать заголовки в этом случае — значит выдать список предыдущего
            # запроса (issues bb9515a15b8e, f3aa36f9a116) — честно возвращаем пусто.
            LOG.warning("enumerate_titles: позиция 'Док.N' не читается — отдаём пустой список")
            return []
        if expect_total and total and total != expect_total:
            LOG.warning("enumerate_titles: объём списка %s не совпадает с разделом %s — "
                        "это не список запроса, отдаём пусто", total, expect_total)
            return []
        for i in range(count):
            title = self._doc_title(query_flat)
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

    def read_toc(self):
        """Оглавление (структура) открытого документа.

        Клик по кнопке «Оглавление» открывает UIA-дерево aid=1597
        ('Оглавление документа КонсультантПлюс'), дети TreeItem — полная
        иерархия (Раздел/Глава/Статья). В отличие от owner-drawn списка выдачи,
        это дерево читается через UIA. Возвращает упорядоченный список
        [{title, level}]; [] если оглавления нет (кнопка недоступна/не найдена
        или документ не структурирован). В конце закрывает панель, чтобы оставить
        клиент опрятным.
        """
        self.ensure_window()
        try:
            btn = self._button_by_name(config.BTN_TOC)
        except NotFound:
            LOG.info("read_toc: кнопки «Оглавление» нет — не читалка/нет структуры")
            return []
        try:
            if not btn.is_enabled():
                LOG.info("read_toc: «Оглавление» недоступна — структура не показана")
                return []
        except Exception:  # noqa: BLE001
            pass
        try:
            btn.click_input()
        except Exception as exc:  # noqa: BLE001
            LOG.info("read_toc: клик «Оглавление» не удался: %r", exc)
            return []
        # ждать появления дерева оглавления (aid=1597)
        tree = None
        deadline = time.time() + 3.0
        while time.time() < deadline:
            for e in self._descendants(control_type="Tree"):
                if e.element_info.automation_id == config.AID_TOC_TREE:
                    tree = e
                    break
            if tree is not None:
                break
            time.sleep(config.POLL)
        entries = []
        if tree is not None:
            rows = []
            for it in tree.descendants(control_type="TreeItem"):
                try:
                    nm = it.element_info.name or ""
                    r = it.rectangle()
                    rows.append((nm, r.top, r.left))
                except Exception:  # noqa: BLE001
                    continue
            rows.sort(key=lambda z: z[1])            # сверху вниз по top
            entries = parse_toc_entries([(nm, left) for nm, _top, left in rows])
        # закрыть панель оглавления (обратный клик) — клиент остаётся чистым
        try:
            self._button_by_name(config.BTN_TOC).click_input()
            time.sleep(0.4)
        except Exception:  # noqa: BLE001
            pass
        LOG.info("read_toc: %d пунктов структуры", len(entries))
        return entries

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
