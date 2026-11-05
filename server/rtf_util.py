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


def _ansicpg(raw_head):
    m = re.search(r"ansicpg(\d{3,5})", raw_head or "", re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _rtf_raw(path):
    """Прочитать RTF как текст. Файлы К+ — в ansicpg1251; раньше здесь вторым
    шагом стоял latin-1, который NEVER падает, и добрая часть документов
    возвращалась в mojibake («Äîêóìåíò ïðåäîñòàâëåí …», issue afeb1abcaef3).
    Теперь: кодировка из заголовка RTF → cp1251 с заменами, latin-1 не используется."""
    with io.open(path, "rb") as f:
        blob = f.read()
    if blob.startswith(b"\xef\xbb\xbf"):
        return blob.decode("utf-8", "replace")
    if blob.startswith(b"\xff\xfe") or blob.startswith(b"\xfe\xff"):
        return blob.decode("utf-16", "replace")
    cp = _ansicpg(blob[:400].decode("ascii", "ignore"))
    for enc in ("cp%d" % cp if cp else None, "cp1251", "utf-8"):
        if not enc:
            continue
        try:
            return blob.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return blob.decode("cp1251", "replace")


def rtf_to_clean_text(path=None, raw=None):
    """RTF → plain text с чисткой водяных знаков/служебных строк К+."""
    if raw is None:
        raw = _rtf_raw(path)
    try:
        text = rtf_to_text(raw, errors="replace")
    except Exception:  # noqa: BLE001
        text = raw
    text = _clean(text)
    # Починку mojibake делает вызывающий (app._prep_text) — так один и тот же
    # фикст применяется и к свежему экспорту, и к давно закешированным телам.
    return text


_RE_LATIN1_HIGH = re.compile(r"[\u00c0-\u00ff]")


def fix_mojibake(text):
    """Починить CP1251, прочитанный как Latin-1 («Äîêóìåíò» → «Документ»).

    Возвращает (text, repaired). Применяется и к свежим экспортам, и к уже
    закешированным телам (data/docs/*.txt записаны с браком).
    """
    if not text:
        return text or "", False
    sample = text[:4000]
    hi = len(_RE_LATIN1_HIGH.findall(sample))
    letters = len(re.findall(r"[A-Za-z\u00c0-\u00ff]", sample))
    if hi < 8 or letters == 0 or hi / max(letters, 1) < 0.5:
        return text, False
    try:
        cand = sample.encode("latin-1", "strict").decode("cp1251", "strict")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text, False
    cyr = len(re.findall(r"[\u0410-\u044f\u0401\u0451]", cand))
    if cyr < max(4, int(hi * 0.5)):
        return text, False
    try:
        full = text.encode("latin-1", "replace").decode("cp1251", "replace")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text, False
    return full, True


# Штампы свежести в текстах К+ — источник для auto-detect даты среза базы
# (issues e47ded1737cb, 3f6dd95f968b, 975f6227e620).
_RE_STAMP = re.compile(
    r"(?:ред\.|с\s+изм\.|по\s+состоянию\s+на|Актуально\s+на)"
    r"[^\d\n]{0,20}?(\d{2}[./-]\d{2}[./-]\d{4})", re.IGNORECASE)
_RE_DDMMYYYY = re.compile(r"^\s*(\d{1,2})[.](\d{1,2})[.](\d{4})\s*$")


def extract_freshness_dates(text, limit=5):
    """(iso_max, [доказательства]) по штампам «ред. от …», «с изм. от …»,
    «по состоянию на …», «Актуально на …». Даты позже сегодняшнего игнорируются
    (это «вступает в силу», а не дата среза)."""
    if not text:
        return None, []
    found = []
    for m in _RE_STAMP.finditer(text):
        d = _RE_DDMMYYYY.match(m.group(1))
        if not d:
            continue
        try:
            iso = "%04d-%02d-%02d" % (int(d.group(3)), int(d.group(2)), int(d.group(1)))
            time.strptime(iso, "%Y-%m-%d")
        except (ValueError, TypeError):
            continue
        if iso > time.strftime("%Y-%m-%d"):
            continue
        if iso not in found:
            found.append(iso)
    if not found:
        return None, []
    found.sort()
    return found[-1], found[-limit:]


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
