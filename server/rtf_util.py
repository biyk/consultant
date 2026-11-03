# -*- coding: utf-8 -*-
"""Работа с RTF-экспортом К+: «Экспорт в Word» кладёт export_*.RTF в C:\\Temp.

Во время записи появляется *.tmp нулевого размера — игнорируем, ждём именно
новый *.rtf. Файл в кодировке cp1251 (ansicpg1251). Даём RTF→plain-text
(striprtf) с чисткой водяных знаков К+, а также извлечение заголовка (\\info\\title),
гиперссылок consultantplus://offline/ref=... и 32-риковых ID документов.
"""
import glob
import io
import os
import re
import shutil
import time

from striprtf.striprtf import rtf_to_text

from . import config


def snapshot_rtf(directory=None):
    """{path: mtime} для всех *.rtf в каталоге (обычно C:\\Temp)."""
    directory = directory or config.RTF_EXPORT_DIR
    out = {}
    for p in glob.glob(os.path.join(directory, "*.rtf")):
        try:
            out[p] = os.path.getmtime(p)
        except OSError:
            pass
    return out


def wait_new_rtf(before, timeout=None, poll=None):
    """Вернуть путь свежего (или обновлённого) *.rtf; None по таймауту."""
    timeout = timeout if timeout is not None else config.WAIT_RTF_TIMEOUT
    poll = poll or config.POLL
    deadline = time.time() + timeout
    while time.time() < deadline:
        now = snapshot_rtf()
        fresh = [
            p for p, mt in now.items()
            if p not in before or mt > before.get(p, 0)
        ]
        # выбираем самый свежий ненулевой
        ready = [p for p in fresh if os.path.isfile(p) and os.path.getsize(p) > 0]
        if ready:
            ready.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            cand = ready[0]
            # дождаться завершения записи (размер стабилен)
            if _size_stable(cand):
                return cand
        time.sleep(poll)
    return None


def _size_stable(path, tries=3, gap=0.5):
    last = -1
    for _ in range(tries):
        try:
            sz = os.path.getsize(path)
        except OSError:
            return False
        if sz == last and sz > 0:
            return True
        last = sz
        time.sleep(gap)
    return last > 0


def ingest(rtf_path, key):
    """Скопировать RTF в data/rtf_inbox/<key>.rtf (чтобы не хранить в C:\\Temp)."""
    dst = os.path.join(config.RTF_INBOX, f"{key}.rtf")
    try:
        shutil.copy2(rtf_path, dst)
    except OSError:
        pass
    return dst


def _rtf_raw(path):
    """Прочитать RTF как текст: cp1251-first (файлы К+ в ansicpg1251)."""
    for enc in ("cp1251", "utf-8", "latin-1"):
        try:
            with io.open(path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, OSError):
            continue
    with io.open(path, "rb") as f:
        return f.read().decode("cp1251", "replace")


def rtf_to_clean_text(path=None, raw=None):
    """RTF → plain text с чисткой водяных знаков/служебных строк К+."""
    if raw is None:
        raw = _rtf_raw(path)
    try:
        text = rtf_to_text(raw, errors="replace")
    except Exception:  # noqa: BLE001
        text = raw
    return _clean(text)


_RE_INFO_TITLE = re.compile(r"\\info\s*\{\\title\s*(.+?)\}", re.DOTALL)
_RE_TITLE = re.compile(r"\\title\s*([^\\}]+)")
# consultantplus://offline/ref=<HEX> — ID документа/ссылки
_RE_REF = re.compile(r"consultantplus://offline/ref=([0-9A-Za-z]+)", re.IGNORECASE)
# отдельные 32-риковых hex-токена — кандидаты на канонический ID документа
_RE_DOCID = re.compile(r"\b[0-9A-Fa-f]{32}\b")


def extract_info_title(path):
    """Заголовок из \\info{\\title ...} (или любого \\title). Пустая строка если нет."""
    raw = _rtf_raw(path)
    m = _RE_INFO_TITLE.search(raw) or _RE_TITLE.search(raw)
    if not m:
        return ""
    t = m.group(1)
    t = re.sub(r"\\[a-z]+-?\d*\s?", "", t)  # снять rtf-управляющие последовательности
    t = t.replace("{", "").replace("}", "").strip()
    return t


def extract_refs(path):
    """Список consultantplus://offline/ref=<ID> (внутренние ссылки/ID)."""
    raw = _rtf_raw(path)
    return _RE_REF.findall(raw)


def extract_doc_ids(path):
    """Уникальные 32-риковых hex-токена — кандидаты на ID самого документа."""
    raw = _rtf_raw(path)
    seen = []
    for t in _RE_DOCID.findall(raw):
        u = t.upper()
        if u not in seen:
            seen.append(u)
    return seen


def extract_links(path):
    """Внутренние ссылки consultantplus://offline/ref=ID с видимым заголовком (fldrslt).
    Возвращает уникальный по ref список {"ref", "title"} — переходы на другие
    документы (для /open по ref и entries[] коллекций)."""
    raw = _rtf_raw(path)
    out, seen = [], set()
    for m in _RE_REF.finditer(raw):
        rid = m.group(1)
        if rid in seen:
            continue
        seen.add(rid)
        tail = raw[m.end():m.end() + 800]
        fm = re.search(r"\\fldrslt\s*(.*?)\}\}", tail, re.DOTALL)
        title = ""
        if fm:
            seg = fm.group(1)
            try:
                title = rtf_to_text(seg, errors="replace").strip()
            except Exception:  # noqa: BLE001
                title = re.sub(r"\\[a-z]+-?\d*\s?", "", seg)
                title = title.replace("{", "").replace("}", "").strip()
        out.append({"ref": rid, "title": title, "label": title,
                    "href": "consultantplus://offline/ref=" + rid})
    return out


_WATERMARK = re.compile(
    r"КонсультантПлюс|consultant\.ru|ООО\s*«НПО\s*«Технология|" +
    r"Ваша\s*версия|Неофициальная\s*версия|Скачано\s*с\s*сайта",
    re.IGNORECASE,
)


def _clean(text):
    if not text:
        return ""
    lines = []
    for ln in text.splitlines():
        s = ln.rstrip()
        if _WATERMARK.search(s):
            continue
        lines.append(s)
    # схлопнуть 3+ пустых строк
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()
