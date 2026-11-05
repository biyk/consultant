# -*- coding: utf-8 -*-
"""Flask-сервер «КонсультантПлюс» — REST-обёртка над GUI-автоматизацией.

Контракт (см. todo.md §5): /, /health, /state, /search, /page, /doc, /sub, /open,
/back, /issues (GET/POST/PATCH/GET-by-id). Все GUI-вызовы — под глобальным
gui_lock (один поток), таймаут → HTTP 504 gui_busy. /state не блокируется.
Метрики каждого запроса пишутся в logs/metrics.jsonl.
"""
import io
import json
import os
import re
import threading
import time
import uuid

from flask import Flask, jsonify, request

from . import cache_store, config, rtf_util
from .consultant_gui import ConsultantGUI, GuiError, NotFound
from .logutil import get_logger

LOG = get_logger("app")   # шагам /search нужна запись в logs/server.log

app = Flask(__name__)

# --- единственная GUI-нитка --------------------------------------------------
_gui = ConsultantGUI()
gui_lock = threading.RLock()
state = {
    "busy": {"active": False, "rid": None, "path": None, "since": None, "last": None},
    "session": {"query": None, "category": None, "total": None, "page_size": config.DEFAULT_PAGE_SIZE,
                "page": 1, "docs": [], "categories": [], "openable": False,
                "section_count": None, "from_cache": False},
    "known_categories": list(config.CANONICAL_CATEGORIES),  # накопленные валидные имена (для hints/манифеста)
    "ref_titles": {},  # ref -> title из извлечённых ссылок (разрешает /open {ref})
    "last_live": {},   # выдача последнего ЖИВОГО /search — ловушка протечки старого списка
    "index_observed": {"max": None, "evidence": []},  # auto-detect даты среза базы
    "nav": [],
}


class Busy(Exception):
    pass


def gui_call(path, fn, timeout=None):
    """Взять gui_lock и выполнить fn(); по таймауту — 504 gui_busy."""
    timeout = timeout or config.GUI_LOCK_TIMEOUT
    rid = uuid.uuid4().hex[:12]
    t0 = time.time()
    acquired = gui_lock.acquire(timeout=timeout)
    if not acquired:
        snap = dict(state["busy"])
        raise Busy(snap)
    try:
        state["busy"].update(active=True, rid=rid, path=path, since=t0, last=time.time())
        res = fn()
        state["busy"].update(active=False, rid=None, path=None)
        state["busy"]["last"] = time.time()
        _metric(path, rid, time.time() - t0, 200)
        return res
    except Busy:
        raise
    except (GuiError, NotFound) as e:
        state["busy"].update(active=False, rid=None, path=None)
        _metric(path, rid, time.time() - t0, 502, err=str(e))
        raise
    except Exception as e:  # noqa: BLE001
        state["busy"].update(active=False, rid=None, path=None)
        _metric(path, rid, time.time() - t0, 500, err=str(e))
        raise
    finally:
        gui_lock.release()


# --- метрики -----------------------------------------------------------------
_metrics_path = os.path.join(config.LOGS_DIR, "metrics.jsonl")


def _metric(path, rid, dur, code, err=None, **extra):
    rec = {"ts": round(time.time(), 3), "path": path, "rid": rid,
           "dur_s": round(dur, 2), "code": code}
    if err:
        rec["err"] = err[:200]
    rec.update(extra)
    try:
        with io.open(_metrics_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


# --- гарантируем подключение к GUI --------------------------------------------
def _ensure_gui():
    try:
        _gui.connect(timeout=5)
    except NotFound:
        import subprocess
        if os.path.isfile(config.CONSULTANT_EXE):
            subprocess.Popen([config.CONSULTANT_EXE])
        _gui.connect(timeout=config.WAIT_RESULTS_TIMEOUT)
    _gui.ensure_window()


def _body():
    return request.get_json(force=True, silent=True) or {}


# --- маршруты ----------------------------------------------------------------
@app.get("/")
def manifest():
    idx = _index_info()
    return jsonify({
        "service": "ConsultantPlus GUI REST",
        "endpoints": {
            "GET /health": "{ok, gui, index_as_of...}",
            "GET /state": "{busy, current, depth, nav, tabs, session}",
            "POST /search": "{query, page_size, category?, page?, fresh?} -> выдача",
            "POST /page": "{page} -> docs[] страницы",
            "POST /doc": "{index | ref} -> {kind,title,content,entries,links,matched_*}",
            "POST /sub": "{index | ref} -> подборка (content + entries[] с href)",
            "POST /open": "{title} | {ref} | {uri} -> прямой доступ (404, если точного совпадения нет)",
            "POST /back": "-> вверх по стеку",
            "GET/POST/PATCH /issues": "трекер заявок; GET /issues?status=open|closed|<status>"
                                     " (open = все не финальные); PATCH /issues/<id> "
                                     "принимает status, note и поля заявки (title, "
                                     "description, endpoint, severity, steps, expected, "
                                     "actual, reporter); неизвестное поле -> 400 "
                                     "unknown_field",
            "GET /metrics": "сводка метрик",
        },
        "categories": state["known_categories"],
        "categories_scope": "словарь разделов = текущий уровень дерева К+; перед "
                            "поиском дерево перечитывается до 3 раз, неизвестное "
                            "имя -> 400 unknown_category со свежим categories[]",
        "link_fields": ["ref", "title", "label", "href"],
        "doc_index_semantics": {
            "base": 0,
            "rule": "index в /doc и /sub = docs[].index той же выдачи (0-based, "
                    "не порядковый номер строки); row = 1-based alias",
            "ref": "docs[].ref вида 'pos:<abs>' — адрес той же строки, "
                   "передавай его вместо index и он не съедет",
        },
        "open_semantics": {
            "exact": "title сопоставляется строго; при отсутствии совпадения "
                     "404 doc_not_found + candidates[], чужой документ не отдаётся",
            "fields": ["exact_match", "requested_title", "opened_title"],
        },
        "notes": {
            "scope": config.SCOPE_SINGLE_SECTION,
            "single_session": True,
            "sequential": True,
            "gui_lock_timeout_s": config.GUI_LOCK_TIMEOUT,
            "doc_text": "Экспорт в Word -> *.rtf в C:\\Temp",
            "selection_rule": ["requested_category", "approximate",
                               "first_leaf_in_tree_order"],
            "empty_reason": ["no_matches", "list_not_rendered", "tree_not_read",
                             "section_not_selected", "results_page_not_opened",
                             "list_scope_mismatch"],
            "empty_reason_semantics": "no_matches = подтверждённое «ничего не найдено» "
                                      "(раздел прочитан, count=0). Остальные — "
                                      "техническая неспособность прочитать GUI, они "
                                      "НИКОГДА не означают отсутствие документов; "
                                      "list_scope_mismatch = открыт список другого "
                                      "раздела/вкладки (объём не совпадает с "
                                      "section_count), строки не отдаются",
            "ok_semantics": "ok=false + retryable=true означает технический сбой "
                            "навигации (выдача НЕ отдавалась как успешная); "
                            "ok=true при total=0 и empty_reason=no_matches — это "
                            "честный пустой результат",
            "total_semantics": "total берётся только из позиции читалки «Док. N/total» "
                               "текущего списка; если она не читается — total=null и "
                               "total_source='unavailable'",
            "cached": "кэш-хит помечается cached=true и _age; сессия при этом "
                      "восстанавливается из кэша, /doc не врёт",
            **idx,
        },
    })


@app.get("/health")
def health():
    idx = _index_info()
    # GUI опрашиваем ТОЛЬКО когда он свободен. Раньше /health лез в окно прямо
    # во время навигации /search: два потока одновременно дёргали pywinauto и
    # Win32-модификации (гонка, из-за которой /health порою врал или подвешивал
    # запрос). ok=true при этом означает лишь «клиент К+ найден».
    gui = {"window": None, "tabs": [], "probed": False}
    if state["busy"]["active"]:
        gui["note"] = ("GUI занят запросом %r — окно не опрашивалось" %
                       state["busy"]["path"])
        # раз окно занято нашим же потоком — клиент заведомо открыт
        hwnds_ok = True
    else:
        def read():
            found = bool(_gui.connect(timeout=3))
            return found, {"window": _gui._state_suffix(),
                           "tabs": _gui.get_state().get("tabs", []),
                           "probed": True}
        try:
            # лок берём накоротке: /health опрашивают надзиратели (Resurrector),
            # он не имеет права ставить в очередь /search
            hwnds_ok, gui = gui_call("/health", read, timeout=2)
        except Busy:
            gui = {"window": None, "tabs": [], "probed": False,
                   "note": "gui_busy — окно ушло в другой запрос, повтори /health"}
            hwnds_ok = False
        except Exception:  # noqa: BLE001
            gui["note"] = "GUI не отвечает"
            hwnds_ok = False
    s = state["session"]
    return jsonify({"ok": bool(hwnds_ok), "gui": gui,
                    "index_incomplete": not bool(config.INDEX_AS_OF),
                    "last_update": config.INDEX_AS_OF or (idx.get("index_as_of") if idx["index_as_of"] != "unknown" else None),
                    "session": {"query": s["query"], "docs_count": len(s["docs"]),
                                 "openable": s.get("openable"), "from_cache": s.get("from_cache")},
                    "sections": [{"name": c["name"], "count": c.get("count")}
                                 for c in s["categories"] if c.get("leaf")],
                    **idx})


@app.get("/state")
def get_state():
    # не берём gui_lock: читаем последний снимок + пытаемся лёгкий опрос окна
    sess = state["session"]
    gui_state = None
    out = {"busy": state["busy"], "depth": len(state["nav"]), "nav_events": len(state["nav"]),
           "tabs": [], "session": {
               "query": sess["query"], "category": sess["category"],
               "total": sess["total"], "page": sess["page"],
               "page_size": sess["page_size"], "docs_count": len(sess["docs"]),
               "openable": sess.get("openable"), "from_cache": sess.get("from_cache"),
           }}
    if not state["busy"]["active"]:
        try:
            g = _gui.get_state()
            out.update(g)
            gui_state = g.get("state")
        except Exception:  # noqa: BLE001
            pass
    # current больше не «залипает»: если GUI ушёл со страницы поиска, сессия
    # считается недействительной и current отдаётся как null (issue 2075ba12d5ca)
    on_search = bool(gui_state) and bool(_RE_PAGE_QUERY.search(_norm(gui_state)))
    if gui_state is None:
        out["current"] = sess["query"]
        out["session_valid"] = bool(sess.get("openable"))
    else:
        cur_ok = bool(sess["query"]) and (on_search or _page_matches_query(gui_state, sess["query"] or ""))
        out["current"] = sess["query"] if cur_ok else None
        out["session_valid"] = cur_ok and bool(sess.get("openable"))
        out["gui_state"] = gui_state
        out["search_page"] = on_search
    return jsonify(out)


def _pages(total, page_size):
    """Число страниц. None = общее число документов неизвестно (не читается
    «Док.N/total») — не подменяем его нулём, иначе «0 страниц» выглядит как
    «нет результатов» (issue 3c1c7cd864d7)."""
    if total is None:
        return None
    if total <= 0:
        return 0
    return (total + page_size - 1) // page_size


def _norm(s):
    """Нормализация имени раздела: nbsp→пробел, нижний регистр, схлопнуть пробелы."""
    s = (s or "").replace("\u00a0", " ").strip().lower()
    return re.sub(r"\s+", " ", s)


_RE_PUNCT = re.compile(r"[\"«»„'`()\[\]{}.,;:!?\-–—_/\\]+")


def _flat(s):
    """Нормализация для сравнения заголовков: снять кавычки и пунктуацию."""
    s = _norm(s or "")
    s = _RE_PUNCT.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(s):
    """Значимые слова (длиннее 2 букв) — для оценки похожести заголовков."""
    return {w for w in _flat(s).split() if len(w) > 2}


_RE_DIGITS = re.compile(r"\d+")


def _digit_set(s):
    return set(_RE_DIGITS.findall(s or ""))


def _is_echo(title, qflat):
    """Псевдострока = эхо строки запроса (issues cf37d556dbd5, 5607db8a1c12,
    4ad19b1f37b8). Список мог не отрисоваться — такую строку в выдачу не берём."""
    if not title:
        return True
    if title.startswith("Поиск:"):
        return True
    tn = _flat(title)
    if not tn:
        return True
    if tn == qflat:
        return True
    # длинный запрос: эхо может быть обрезано заголовком колонки
    if len(qflat) >= 20 and (qflat.startswith(tn) or tn.startswith(qflat)):
        return True
    return False


def _titles_correspond(a, b):
    """'yes' / 'no' / 'unknown' — тот ли это документ (контроль подмены в /doc)."""
    fa, fb = _flat(a), _flat(b)
    if not fa or not fb:
        return "unknown"
    if fa == fb or fa in fb or fb in fa:
        return "yes"
    da, db = _digit_set(fa), _digit_set(fb)
    if da and db and da != db:
        # номера статей/дат не пересекаются → заведомо разные акты
        # (ст. 190 vs ст. 333, N 22 vs N 39)
        return "no"
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return "unknown"
    ratio = len(ta & tb) / float(min(len(ta), len(tb)))
    return "yes" if ratio >= 0.5 else "no"


_RE_PAGE_QUERY = re.compile(r"^поиск[:\s]+(.*)$", re.IGNORECASE | re.DOTALL)


def _page_matches_query(gui_state, query):
    """OK-но только если страница результатов принадлежит ЭТОМУ запросу
    (issues bb9515a15b8e, d3c7ffb4f418, aa213ed6f361)."""
    if not gui_state:
        return False
    m = _RE_PAGE_QUERY.search(_norm(gui_state))
    if not m:
        return False
    body = _flat(m.group(1))
    qflat = _flat(query)
    if not body or not qflat:
        return False
    if body == qflat or body in qflat or qflat.startswith(body):
        return True
    tq, tb = _tokens(body), _tokens(query)
    if tq and tb:
        return len(tq & tb) / float(min(len(tq), len(tb))) >= 0.6
    return False


def _respond(payload):
    """jsonify + служебный _status (чтобы честный HTTP-код не мешал JSON)."""
    payload = dict(payload)
    status = payload.pop("_status", 200)
    return jsonify(payload), status


def _doc_row(abs_i, title):
    """Строка выдачи: index (0-based, см. /doc), abs, ref для прямого доступа."""
    return {"index": None, "abs": abs_i,
            "ref": ("pos:%s" % abs_i) if abs_i else None, "title": title}


def _row_from_titles(titles, qflat):
    """[(abs,title)] → docs[] с отбрасыванием эха запроса."""
    docs = []
    for ab, tt in titles:
        if _is_echo(tt, qflat):
            continue  # отбросить эхо запроса / нечитаемый заголовок (issue cf37)
        row = _doc_row(ab, tt)
        row["index"] = len(docs)
        docs.append(row)
    return docs


def _hydrate_session(payload, from_cache=False):
    """Восстановить state["session"] из ВЫДАННОГО ответа (живого или кэша).

    Раньше кэш-хит возвращался молча, и сессия оставалась от предыдущего
    запроса → /doc и /sub открывали чужой документ (issues d3c7ffb4f418,
    bb9515a15b8e, f3aa36f9a116, step 4 из 2075ba12d5ca).
    """
    docs = payload.get("docs") or []
    state["session"].update(
        query=payload.get("query"), category=payload.get("selected_category"),
        total=payload.get("total"), page=payload.get("page") or 1,
        page_size=payload.get("page_size") or state["session"]["page_size"],
        docs=docs, categories=payload.get("categories") or [],
        # объём выбранного раздела — по нему /page сверяет, что листает именно
        # список этого запроса, а не старую вкладку (issue e7f7bb098cfd)
        section_count=payload.get("section_count"),
        openable=bool(payload.get("ok")) and bool(docs),
        from_cache=bool(from_cache))
    return docs


# --- mojibake / кодировка ----------------------------------------------------
def _prep_text(text):
    """CP1251-как-Latin-1 чиним на границе API (issue afeb1abcaef3)."""
    text, repaired = rtf_util.fix_mojibake(text or "")
    return text, repaired


# --- auto-detect даты среза базы ---------------------------------------------
def _load_index_observed():
    p = config.INDEX_OBSERVED_STORE
    if os.path.isfile(p):
        try:
            with io.open(p, encoding="utf-8") as f:
                obj = json.load(f)
            state["index_observed"].update(obj or {})
        except (OSError, ValueError):
            pass
    return state["index_observed"]


def _observe_freshness(text, title=None):
    """Запомнить самые свежие штампы дат из прочитанного документа."""
    if not text or not config.INDEX_AS_OF_AUTO:
        return
    mx, evid = rtf_util.extract_freshness_dates(text)
    if not mx:
        return
    obs = state["index_observed"]
    changed = False
    if (obs.get("max") or "") < mx:
        obs["max"] = mx
        changed = True
    ev = obs.setdefault("evidence", [])
    for d in evid:
        if not any(e.get("date") == d for e in ev):
            ev.append({"date": d, "title": (title or "")[:120]})
            changed = True
    ev.sort(key=lambda e: e["date"], reverse=True)
    del ev[12:]
    if changed:
        try:
            with io.open(config.INDEX_OBSERVED_STORE, "w", encoding="utf-8") as f:
                json.dump(obs, f, ensure_ascii=False, indent=1)
        except OSError:
            pass


def _index_info():
    """Честный источник даты среза: env → observed → unknown (issues e47ded1737cb,
    3f6dd95f968b, 975f6227e620)."""
    if config.INDEX_AS_OF:
        return {"index_as_of": config.INDEX_AS_OF,
                "index_as_of_source": "env CONSULTANT_INDEX_AS_OF",
                "index_as_of_confidence": "operator"}
    obs = state.get("index_observed") or {}
    if config.INDEX_AS_OF_AUTO and obs.get("max"):
        return {"index_as_of": obs["max"],
                "index_as_of_source": "observed: штампы «ред. от / с изм. от / "
                                      "по состоянию на» в прочитанных документах",
                "index_as_of_confidence": "observed (нижняя граница среза)",
                "index_as_of_evidence": obs.get("evidence") or []}
    return {"index_as_of": "unknown",
            "index_as_of_source": "not set",
            "index_as_of_note": "задай env CONSULTANT_INDEX_AS_OF=ГГГГ-ММ-ДД "
                                "или дай серверу прочить хоть один документ (auto-detect)"}


def _match_category(cats, requested):
    """Выбор раздела по имени. Только точное совпадение или префикс в обе стороны
    (по словам) — свободное подстроковое совпадение молча подменяло раздел:
    «Региональное законодательство» выбивалось в «Законодательство» (issue 2cc4).
    Возвращает dict-категорию или None."""
    rl = _norm(requested)
    if not rl:
        return None
    for c in cats:  # 1) точное совпадение
        if _norm(c["name"]) == rl:
            return c
    cands = [c for c in cats
             if _norm(c["name"]).startswith(rl) or rl.startswith(_norm(c["name"]))]
    if cands:  # 2) самый длинный (самый специфичный) префикс
        cands.sort(key=lambda c: len(_norm(c["name"])), reverse=True)
        return cands[0]
    return None


_load_index_observed()   # auto-detect даты среза переживает рестарт сервера


def _link_out(l):
    """Нормальный вид ссылки для ответа: {ref,title,label,href}."""
    return {"ref": l.get("ref"), "title": l.get("title"),
            "label": l.get("label", l.get("title")),
            "href": l.get("href") or ("consultantplus://offline/ref=" + str(l.get("ref")))}


def _remember_refs(links):
    for l in links or []:
        r = l.get("ref")
        t = l.get("title") or l.get("label")
        if r and t and r not in state["ref_titles"]:
            state["ref_titles"][r] = t


_RE_YEAR = re.compile(r"(?:19|20)\d{2}")


def _beyond_index_note(query):
    """Если в запросе упоминается год позже среза индекса — честная заметка (issue 04a1)."""
    if not config.INDEX_AS_OF:
        return None
    m = _RE_YEAR.search(query or "")
    if not m:
        return None
    try:
        idx_year = int(config.INDEX_AS_OF[:4])
        q_year = int(m.group(0))
    except (ValueError, TypeError):
        return None
    if q_year > idx_year or (q_year == idx_year and False):
        return ("запрос упоминает %d, а срез индекса — %s; пустая выдача может означать "
                "«ещё не обновлено», а не «не существует»" % (q_year, config.INDEX_AS_OF))
    return None


@app.post("/search")
def search():
    b = _body()
    query = (b.get("query") or "").strip()
    if not query:
        return jsonify({"ok": False, "error": "empty_query"}), 400
    page_size = max(1, min(int(b.get("page_size") or config.DEFAULT_PAGE_SIZE), config.MAX_PAGE_SIZE))
    page = max(1, int(b.get("page") or 1))
    category = b.get("category")
    fresh = bool(b.get("fresh"))

    ckey = cache_store.search_key(query, category, page, page_size)
    if not fresh:
        hit = cache_store.get_search(ckey)
        if hit:
            # кэш-хит обязан НЕ оставлять сессию от предыдущего запроса: иначе
            # /doc и /sub открывают чужой документ (issue d3c7ffb4f418)
            hit["cached"] = True
            if hit.get("_age") is not None:
                hit["_age"] = round(hit["_age"], 3)
            docs = _hydrate_session(hit, from_cache=True)
            hit["session_openable"] = bool(docs)
            return _respond(hit)

    def work():
        _ensure_gui()
        prev_live = dict(state["last_live"] or {})
        # сброс сессии: при любой ошибке ниже docs останутся пустыми → /doc честно отдаст 400
        state["session"].update(query=None, category=None, total=None, page=page,
                                page_size=page_size, docs=[], openable=False,
                                section_count=None, from_cache=False)
        # 1) навигация на СТРАНИЦУ РЕЗУЛЬТАТОВ ЭТОГО запроса (с одним повтором).
        #    Без этой проверки live-/search отдавал список предыдущего запроса
        #    (issues bb9515a15b8e, aa213ed6f361, 41fd983ff936).
        page_ok = False
        gui_state = None
        for _try in range(2):
            page_ok = bool(_gui.do_search(query))
            gui_state = (_gui.page_info() or {}).get("state")
            if page_ok and _page_matches_query(gui_state, query):
                break
        if not (page_ok and _page_matches_query(gui_state, query)):
            return {"ok": False, "query": query, "error": "results_page_not_opened",
                    "empty_reason": "results_page_not_opened", "retryable": True,
                    "gui_state": gui_state, "total": None, "total_source": "unavailable",
                    "pages": None, "docs": [], "parsed_count": 0, "expected_count": None,
                    "empty_list": True,
                    "note": "GUI не перешёл на страницу результатов этого запроса; "
                            "выдача предыдущего запроса не подставляется", **_index_info()}

        _gui.open_all_results()
        cats = _gui.read_categories()
        # ретрай: если дерево не отрисовалось (модалки/тайминг) — открыть/прочитать ещё раз
        tries = 0
        while not cats and tries < 2:
            _gui.open_all_results()
            cats = _gui.read_categories()
            tries += 1
        state["session"]["categories"] = cats
        # накопить известные валидные имена (для hints в 400 и манифеста)
        for c in cats:
            if c["name"] and c["name"] not in state["known_categories"]:
                state["known_categories"].append(c["name"])
        # 2) выбрать раздел: дерево перечитываем до 3 раз, прежде чем признать
        #    unknown_category — первый проход после смены состояния GUI часто
        #    видит неполный словарь (issues dbb0182949e2, 5f6bfa0e4a5b)
        sel = None
        sel_count = None
        sel_approx = False
        selection_rule = None
        sel_note = None
        if category:
            chosen = None
            for _attempt in range(3):
                chosen = _match_category(cats, category)
                if chosen:
                    break
                _gui.open_all_results()
                time.sleep(0.5)
                cats = _gui.read_categories() or cats
                state["session"]["categories"] = cats
            if not chosen:
                names = ([c["name"] for c in cats if c["name"]] or
                         state["known_categories"])
                return {"ok": False, "error": "unknown_category", "retryable": True,
                        "query": query, "requested_category": category,
                        "categories": names, "tree_reads": 3, "docs": [],
                        "hint": "имени нет в текущем уровне дерева (перечитано 3 раза); "
                                "возьми точное имя из categories",
                        "_status": 400, **_index_info()}
            _gui.select_category(chosen["name"])
            sel = chosen["name"]
            sel_count = chosen.get("count")
            sel_approx = "\u2265" in (chosen.get("raw_count") or "")
            if _norm(sel) == _norm(category):
                selection_rule = "requested_category"
            else:
                # тихая подмена раздела недопустима: честно сигнализируем
                selection_rule = "approximate"
                sel_note = ("запрошен раздел %r, выбран близкий по имени %r — "
                            "результат относится к %r" % (category, sel, sel))
        else:
            leaves = [c for c in cats if c["leaf"]]
            if leaves:
                chosen = leaves[0]  # детерминированно: первый лист в порядке дерева
                _gui.select_category(chosen["name"])
                sel = chosen["name"]
                sel_count = chosen.get("count")
                sel_approx = "\u2265" in (chosen.get("raw_count") or "")
            selection_rule = "first_leaf_in_tree_order"

        # 3) перечислить строки списка
        start_abs = (page - 1) * page_size + 1
        docs = []
        total = None
        total_source = "unavailable"
        empty_reason = None
        enum_attempts = 0
        if not cats:
            # Дерево НЕ прочиталось (модалка/тайминг) — это НЕ «нет результатов».
            # Раньше здесь стоял no_matches, и пустое дерево выдавалось как
            # честный «ничего не найдено» (issues 2cc486c55387, dbb0182949e2).
            empty_reason = "tree_not_read"
        elif sel is None:
            empty_reason = "section_not_selected"
        elif sel_count == 0:
            empty_reason = "no_matches"
        else:
            qflat = _flat(query)
            for enum_attempts in (1, 2):
                if enum_attempts == 2:
                    # вторая попытка только при заведомо непустом разделе:
                    # сбрасываем модалки и пересобираем список
                    LOG.info("enumerate: пустой список при section_count=%s — "
                             "вторая попытка", sel_count)
                    try:
                        _gui.close_modal_dialogs()
                    except Exception:  # noqa: BLE001
                        pass
                    _gui.open_all_results()
                    time.sleep(0.5)
                    _gui.select_category(sel)
                    time.sleep(0.5)
                titles = _gui.enumerate_titles(start_abs, page_size, qflat,
                                                expect_total=(None if sel_approx
                                                              else sel_count))
                docs = _row_from_titles(titles, qflat)
                _, pos_total = _gui._doc_position()
                if pos_total:
                    total, total_source = pos_total, "doc_position"
                if docs:
                    break
            if not docs:
                empty_reason = "list_not_rendered"

        # 3.5) сверка ОБЪЁМА списка. Читалка показывает «Док.N/total» того окна,
        # которое открыто по факту. Если открытие строки не состоялось, она
        # продолжает листать СПИСОК ИЗ СТАРОЙ ВКЛАДКИ, и /search отдавал чужие
        # заголовки как выдачу запроса (в live-прогоне: total=31 при разделе
        # в 1588 документов). Ложный успех для юридической цитаты хуже
        # честного отказа (issues e7f7bb098cfd, e15c0d424393).
        scope_mismatch = None
        if total and sel_count:
            bad = (total != sel_count) if not sel_approx else (total < sel_count)
            if bad:
                scope_mismatch = {"opened_list_total": total,
                                  "section_count": sel_count, "section": sel}
        if scope_mismatch and empty_reason in (None, "list_not_rendered"):
            # «не то, что листаем» важнее и точнее, чем «не отрендерилось»
            empty_reason = "list_scope_mismatch"

        rows_identical = len(docs) > 1 and len({d["title"] for d in docs}) == 1
        # детектор протечки: для ДРУГОГО запроса получился посимвольно тот же
        # набор заголовков → список не перерисовался (issue bb9515a15b8e)
        stale_suspect = False
        if docs and prev_live.get("titles") and _norm(prev_live.get("query") or "") != _norm(query):
            if [d["title"] for d in docs] == list(prev_live["titles"]):
                stale_suspect = True
        if empty_reason is None:
            if rows_identical or stale_suspect or not docs:
                empty_reason = "list_not_rendered"
        if empty_reason == "no_matches":
            total, total_source = 0, "section_count" if sel_count == 0 else "tree"

        ok = empty_reason is None or empty_reason == "no_matches"

        dropped = len(docs) if (stale_suspect or rows_identical) else 0
        if not ok:
            docs_out = []      # не отдаём подозрительные/пустые строки как выдачу
        else:
            docs_out = docs
        expected = min(page_size, max(0, total - start_abs + 1)) if total else 0
        sections = [{"name": c["name"], "count": c.get("count")} for c in cats if c["leaf"]]
        note = sel_note or _beyond_index_note(query)
        if empty_reason == "tree_not_read":
            note = ("дерево разделов не прочиталось (%s попыток перечислить) — "
                    "это НЕ «нет документов в базе», повтори запрос" % (tries + 1))
        elif empty_reason == "list_not_rendered" and sel_count:
            note = ((note + "; " if note else "") +
                    "в разделе %r найдено %s документов, но строки списка не "
                    "прочитаны за %s попытки — это НЕ «нет результатов» "
                    "(повтори /search)" % (sel, sel_count, enum_attempts))
        elif empty_reason == "list_scope_mismatch":
            note = ((note + "; " if note else "") +
                    "открытый список содержит %s документов, а в разделе %r их %s — "
                    "мы листаем НЕ список этого запроса (старая вкладка/карточка), "
                    "поэтому строки не отданы; это НЕ «нет результатов», "
                    "повтори /search" % (scope_mismatch["opened_list_total"],
                                          sel, sel_count))
        # частичное чтение списка — не выдаём его как полный
        truncated = bool(ok and docs_out and expected and len(docs_out) < expected)
        if truncated:
            note = ((note + "; " if note else "") +
                    "список прочитан частично: %s строк(и) из %s — навигация "
                    "оборвалась, за полный список это не считай" % (len(docs_out),
                                                                    expected))
        idx_info = _index_info()
        resp = {
            "ok": ok, "query": query,
            "total": total if ok or empty_reason == "no_matches" else None,
            "total_source": total_source,
            "pages": _pages(total, page_size) if ok else 0,
            "page": page, "page_size": page_size,
            "docs": docs_out, "categories": cats, "sections": sections,
            "selected_category": sel, "requested_category": category,
            "selection_rule": selection_rule, "section_count": sel_count,
            "scope": config.SCOPE_SINGLE_SECTION, "truncated": truncated,
            "parsed_count": len(docs_out), "expected_count": expected,
            "filter_applied": bool(category and sel),
            "empty_reason": empty_reason,   # no_matches отдаём и при ok=true
            "empty_list": not ok,
            "retryable": not ok,
            "error": None if ok else (empty_reason or "list_not_rendered"),
            "rows_identical": rows_identical, "stale_suspect": stale_suspect,
            "scope_mismatch": scope_mismatch,
            "dropped_rows": dropped, "enum_attempts": enum_attempts,
            "openable": bool(docs_out),
            "index_as_of": idx_info["index_as_of"],
            "index_as_of_source": idx_info["index_as_of_source"],
            "note": note,
        }
        # обновить сессию только подтверждённой выдачей
        _hydrate_session(resp)
        state["session"]["openable"] = ok and bool(docs)
        if ok:
            state["last_live"] = {"query": query, "total": total,
                                   "titles": [d["title"] for d in docs],
                                   "ts": round(time.time(), 3)}
            # шаг вперёд по навигации — его и разворачивает /back
            state["nav"].append({"t": round(time.time(), 3), "path": "/search",
                                  "query": query, "state": gui_state})
        return resp

    try:
        resp = gui_call("/search", work)
    except Busy as e:
        return jsonify({"ok": False, "error": "gui_busy", "busy": e.args[0]}), 504
    except NotFound:
        names = ([c["name"] for c in state["session"]["categories"]] or
                 state["known_categories"])
        return jsonify({"ok": False, "error": "unknown_category",
                        "requested_category": category,
                        "categories": names,
                        "hint": "возьми точное имя из categories"}), 400
    except GuiError as e:
        return jsonify({"ok": False, "error": "gui_error", "detail": str(e),
                        "retryable": True}), 502

    _observe_freshness("\n".join(d["title"] or "" for d in resp.get("docs", [])),
                       resp.get("query"))
    if resp.get("ok") and resp.get("docs"):
        # деградацию не кэшируем: иначе «список не отрендерен» висел бы вечно
        cache_store.put_search(ckey, resp)
    return _respond(resp)


def _resolve_row(b, sess, endpoint="/doc"):
    """Разобрать адрес строки выдачи: index (0-based) | row (1-based) |
    ref ('pos:<abs>' из docs[]). Возвращает (idx, None) либо (None, (json, code))."""
    docs = sess.get("docs") or []
    if not docs:
        return None, ({"ok": False, "error": "no_openable_list", "parsed_count": 0,
                       "retryable": True, "endpoint": endpoint,
                       "hint": "нет активной выдачи: сделай POST /search (можно fresh=1). "
                               "После /back или перезапуска сервера список в GUI "
                               "не восстанавливается сам"}, 400)
    if not sess.get("openable", True):
        return None, ({"ok": False, "error": "list_not_active", "parsed_count": len(docs),
                       "retryable": True, "endpoint": endpoint, "query": sess.get("query"),
                       "hint": "GUI ушёл со страницы выдачи (например /back) — "
                               "повтори POST /search, иначе откроется чужой список"}, 400)
    ref = b.get("ref")
    if ref and b.get("index") is None and b.get("row") is None:
        m = re.match(r"^pos:(\d+)$", str(ref).strip())
        if m:
            want_abs = int(m.group(1))
            for d in docs:
                if d.get("abs") == want_abs:
                    return d["index"], None
            return None, ({"ok": False, "error": "ref_not_in_current_list", "ref": ref,
                           "parsed_count": len(docs), "retryable": True,
                           "hint": "этой строки нет в текущей выдаче — повтори /search"}, 400)
    if b.get("row") is not None:
        idx = int(b["row"]) - 1
        given = {"row": int(b["row"]), "index": idx}
    elif b.get("index") is not None:
        idx = int(b["index"])
        given = {"index": idx}
    else:
        idx = 0
        given = {"index": 0}
    if not (0 <= idx < len(docs)):
        return None, ({"ok": False, "error": "index_out_of_range",
                       "parsed_count": len(docs), "index_base": 0,
                       "valid_range": [0, len(docs) - 1],
                       "hint": "index = docs[].index той же выдачи (0-based); "
                               "для 1-based есть row"}, 400)
    return idx, None


@app.post("/page")
def page():
    b = _body()
    p = max(1, int(b.get("page") or 1))
    sess = state["session"]
    if not sess["query"]:
        return jsonify({"ok": False, "error": "no_active_search",
                        "retryable": True,
                        "hint": "сначала POST /search"}), 400

    def work():
        _ensure_gui()
        ps = sess["page_size"]
        qflat = _flat(sess["query"] or "")
        titles = _gui.enumerate_titles((p - 1) * ps + 1, ps, qflat)
        docs = _row_from_titles(titles, qflat)
        _, pos_total = _gui._doc_position()
        sec_count = sess.get("section_count")
        if pos_total and sec_count and pos_total != sec_count:
            # листаем НЕ тот список (объём читалки не совпадает с разделом) —
            # строки не отдаём (issue e7f7bb098cfd)
            return {"ok": False, "error": "list_scope_mismatch",
                    "empty_reason": "list_scope_mismatch", "page": p,
                    "docs": [], "total": None, "retryable": True,
                    "parsed_count": 0, "scope_mismatch": {
                        "opened_list_total": pos_total,
                        "section_count": sec_count,
                        "section": sess.get("category")},
                    "note": "страница %s открыла список в %s документов при "
                            "разделе в %s — это не выдача запроса %r"
                            % (p, pos_total, sec_count, sess["query"])}
        if not docs:
            # сессию НЕ затираем: прежняя выдача остаётся адресуемой
            return {"ok": False, "error": "list_not_rendered", "page": p,
                    "docs": [], "total": sess["total"], "retryable": True,
                    "parsed_count": 0,
                    "note": "страница %s не отрендерена — сессия осталась от "
                            "предыдущей страницы" % p}
        sess.update(page=p, docs=docs, openable=True, from_cache=False)
        if pos_total:
            sess["total"] = pos_total
        return {"ok": True, "page": p, "docs": docs, "total": sess["total"],
                "total_source": "doc_position", "pages": _pages(sess["total"], ps),
                "page_size": ps, "query": sess["query"],
                "parsed_count": len(docs), "index_base": 0}

    try:
        return jsonify(gui_call("/page", work))
    except Busy as e:
        return jsonify({"ok": False, "error": "gui_busy", "busy": e.args[0]}), 504
    except GuiError as e:
        return jsonify({"ok": False, "error": "gui_error", "detail": str(e),
                        "retryable": True}), 502


@app.post("/doc")
def doc():
    b = _body()
    sess = state["session"]
    idx, err = _resolve_row(b, sess, "/doc")
    if err:
        return jsonify(err[0]), err[1]
    docs = sess["docs"]
    row = docs[idx]
    title = row.get("title") or ""
    dkey = cache_store.doc_key(title)
    base = {"matched_index": idx, "matched_title": title, "index_base": 0,
            "requested": {k: b[k] for k in ("page", "index", "row", "ref") if k in b},
            "abs": row.get("abs"), "ref": row.get("ref")}
    if not b.get("fresh"):
        hit = cache_store.get_doc(dkey)
        if hit:
            hit["cached"] = True
            if hit.get("_age") is not None:
                hit["_age"] = round(hit["_age"], 3)
            content, repaired = _prep_text(hit.get("content") or "")
            hit["content"] = content
            hit["content_len"] = len(content)
            hit.update(base)
            hit.setdefault("title", title)
            hit["title_match"] = _titles_correspond(title, hit.get("title") or title)
            hit["content_charset"] = "utf-8"
            hit["mojibake_repaired"] = repaired
            return _respond(hit)

    def work():
        _ensure_gui()
        abs_i = row["abs"]
        _gui.ensure_doc_open(abs_i)
        t, text, links = None, "", []
        for _attempt in range(3):
            _gui.goto_doc_index(abs_i)
            t, text, links = _gui.export_current_doc(dkey)
            if text and len(text) > config.DOC_MIN_CONTENT:
                break
            time.sleep(0.6)
        _remember_refs(links)
        text, repaired = _prep_text(text)
        _observe_freshness(text, t or title)
        match = _titles_correspond(title, t or "")
        if not text or len(text) <= config.DOC_MIN_CONTENT:
            kind = "unavailable"
        elif len(links) >= 5:
            kind = "collection"
        else:
            kind = "document"
        out_links = [_link_out(l) for l in links]
        entries = (out_links if kind == "collection" else [])
        resp = dict(base)
        resp.update({
            "ok": kind != "unavailable" and match != "no",
            "kind": kind, "title": t or title, "opened_title": t or "",
            "content": text, "content_len": len(text or ""),
            "content_charset": "utf-8", "mojibake_repaired": repaired,
            "entries": entries, "links": out_links,
            "title_match": match,
            "retryable": kind == "unavailable" or match == "no",
            "message": ("doc_unavailable: экспорт пуст/обрезан — повтори /doc"
                        if kind == "unavailable" else
                        ("doc_title_mismatch: открылся документ, не совпадающий со "
                         "строкой выдачи — content не использовать как цитату, "
                         "повтори /search и /doc" if match == "no" else None)),
        })
        if resp["ok"]:
            cache_store.put_doc(dkey, {k: resp[k] for k in
                                       ("kind", "title", "message", "matched_title")}, text)
        return resp

    try:
        return _respond(gui_call("/doc", work))
    except Busy as e:
        return jsonify({"ok": False, "error": "gui_busy", "busy": e.args[0]}), 504
    except GuiError as e:
        return jsonify({"ok": False, "kind": "unavailable", "title": title,
                        "error": "doc_unavailable", "retryable": True,
                        "message": str(e), **base}), 200


def _read_doc(abs_i, key, want_title):
    """Открыть строку списка, выгрузить RTF, проверить соответствие заголовка.
    общий для /open и /sub."""
    _gui.ensure_doc_open(abs_i)
    t, text, links = None, "", []
    for _attempt in range(3):
        _gui.goto_doc_index(abs_i)
        t, text, links = _gui.export_current_doc(key)
        if text and len(text) > config.DOC_MIN_CONTENT:
            break
        time.sleep(0.6)
    _remember_refs(links)
    text, repaired = _prep_text(text)
    _observe_freshness(text, t or want_title)
    match = _titles_correspond(want_title, t or "")
    if not text or len(text) <= config.DOC_MIN_CONTENT:
        kind = "unavailable"
    elif len(links) >= 5:
        kind = "collection"
    else:
        kind = "document"
    out_links = [_link_out(l) for l in links]
    return {"kind": kind, "title": t or want_title, "opened_title": t or "",
            "content": text, "content_len": len(text or ""),
            "content_charset": "utf-8", "mojibake_repaired": repaired,
            "entries": out_links, "links": out_links, "title_match": match}


def _score_title(candidate, qflat):
    """Похожесть строки выдачи на запрошенный заголовок: покрытие СЛОВ ЗАПРОСА.
    Короткая «документ»-строка не должна засчитываться как совпадение длинного
    запроса (issues d0f56f25fda9, 7ff67e4db6f7)."""
    ft = _flat(candidate)
    if not ft or not qflat:
        return 0.0
    if ft == qflat:
        return 1.0
    if ft.startswith(qflat) or qflat.startswith(ft):
        return 0.9
    if qflat in ft:
        return 0.8
    if ft in qflat:
        return 0.65
    tc, tq = _tokens(candidate), {w for w in qflat.split() if len(w) > 2}
    if not tc or not tq:
        return 0.0
    return len(tc & tq) / float(len(tq))


@app.post("/open")
def open_():
    b = _body()
    title = b.get("title")
    ref = b.get("ref")
    uri = b.get("uri")
    if not title and uri and "ref=" in uri:
        ref = uri.split("ref=")[-1].strip()
    positional = bool(ref) and str(ref).startswith("pos:")
    # ref из выдачи ('pos:<abs>') — открыть эту же строку текущего списка
    if positional and not title:
        sess = state["session"]
        idx, err = _resolve_row(b, sess, "/open")
        if err:
            return jsonify(err[0]), err[1]
        row = sess["docs"][idx]

        def work_pos():
            _ensure_gui()
            out = _read_doc(row["abs"], cache_store.doc_key(row["title"]), row["title"])
            ok = out["kind"] != "unavailable" and out["title_match"] != "no"
            state["session"]["openable"] = False   # читалка увела с списка
            return {"ok": ok, **out, "requested_title": row["title"],
                    "resolved_from_ref": row["ref"], "matched_abs": row["abs"],
                    "matched_index": idx, "index_base": 0,
                    "exact_match": out["title_match"] == "yes",
                    "retryable": not ok,
                    "message": (None if ok else "doc_unavailable/doc_title_mismatch — "
                                                "повтори /search затем /open"),
                    "note": "после /open выдача больше не адресуема: для /doc нужен "
                            "повторный /search"}

        try:
            return _respond(gui_call("/open", work_pos))
        except Busy as e:
            return jsonify({"ok": False, "error": "gui_busy", "busy": e.args[0]}), 504
        except GuiError as e:
            return jsonify({"ok": False, "error": "gui_error", "detail": str(e),
                            "retryable": True}), 502

    # разрешить ref → title из накопленной карты (refs, которые мы сами отдавали в links[])
    if not title and ref:
        title = state["ref_titles"].get(ref)
    if not title:
        return jsonify({"ok": False, "error": "title_or_resolvable_ref_required",
                        "detail": "передай {title} или {ref}/{uri}, ранее полученный из links[] "
                                  "(ref вида 'pos:<abs>' — из docs[]); неизвестный ref "
                                  "через GUI не открывается"}), 400

    def work():
        _ensure_gui()
        qflat = _flat(title)
        # навигация на страницу результатов этого заголовка (с повтором)
        page_ok = False
        gui_state = None
        for _try in range(2):
            page_ok = bool(_gui.do_search(title))
            gui_state = (_gui.page_info() or {}).get("state")
            if page_ok and _page_matches_query(gui_state, title):
                break
        if not (page_ok and _page_matches_query(gui_state, title)):
            return {"ok": False, "error": "results_page_not_opened", "retryable": True,
                    "requested_title": title, "gui_state": gui_state,
                    "_status": 502,
                    "note": "страница результатов не открылась — чужой документ "
                            "не выдаём"}
        _gui.open_all_results()
        cats = _gui.read_categories()
        leaves = [c for c in cats if c["leaf"] and c.get("count")]
        leaves.sort(key=lambda c: c["count"] or 0, reverse=True)
        expect_total = None
        if leaves:
            _gui.select_category(leaves[0]["name"])
            # /open обязан брать строки ИЗ СПИСКА этого запроса: если читалка
            # показывает другой объём, candidates/документ могли прийти из
            # старой вкладки (issue e7f7bb098cfd)
            if "\u2265" not in (leaves[0].get("raw_count") or ""):
                expect_total = leaves[0].get("count")
        titles = _gui.enumerate_titles(1, max(config.DEFAULT_PAGE_SIZE, 10), qflat,
                                       expect_total=expect_total)
        scored = sorted((( _score_title(tt, qflat), ab, tt) for ab, tt in titles if tt),
                        key=lambda x: x[0], reverse=True)
        candidates = [{"title": tt, "score": round(sc, 3), "ref": "pos:%s" % ab}
                      for sc, ab, tt in scored[:5]]
        if not scored or scored[0][0] < 0.6:
            # никакого «откроем первую попавшуюся» (issues d0f56f25fda9, 7ff67e4db6f7)
            return {"ok": False, "error": "doc_not_found", "requested_title": title,
                    "exact_match": False, "candidates": candidates, "retryable": False,
                    "_status": 404,
                    "note": "точного совпадения заголовка в выдаче нет"}
        sc, pick, got_title = scored[0]
        out = _read_doc(pick, cache_store.doc_key(title), got_title)
        ok = out["kind"] != "unavailable" and out["title_match"] != "no"
        state["session"]["openable"] = False
        return {"ok": ok, **out, "requested_title": title,
                "exact_match": _flat(got_title) == qflat,
                "match_score": round(sc, 3), "candidates": candidates,
                "matched_abs": pick, "resolved_from_ref": bool(ref and b.get("title") is None),
                "retryable": not ok,
                "message": (None if ok else "doc_unavailable/doc_title_mismatch"),
                "note": "после /open выдача больше не адресуема: для /doc нужен "
                        "повторный /search"}

    try:
        return _respond(gui_call("/open", work))
    except Busy as e:
        return jsonify({"ok": False, "error": "gui_busy", "busy": e.args[0]}), 504
    except GuiError as e:
        return jsonify({"ok": False, "error": "gui_error", "detail": str(e)}), 502


@app.post("/sub")
def sub():
    b = _body()
    sess = state["session"]
    idx, err = _resolve_row(b, sess, "/sub")
    if err:
        return jsonify(err[0]), err[1]
    docs = sess["docs"]
    row = docs[idx]

    def work():
        _ensure_gui()
        out = _read_doc(row["abs"], cache_store.doc_key(row["title"]), row["title"])
        ok = out["kind"] != "unavailable" and out["title_match"] != "no"
        text = out["content"]
        return {"ok": ok, "kind": out["kind"], "title": out["title"],
                "opened_title": out["opened_title"],
                "content": text,                 # схема как у /doc (issue c1dbfe0f2947)
                "text": text,                    # алиас обратной совместимости
                "content_len": out["content_len"],
                "content_charset": "utf-8", "mojibake_repaired": out["mojibake_repaired"],
                "entries": out["entries"], "links": out["links"],
                "matched_index": idx, "matched_title": row["title"], "index_base": 0,
                "abs": row["abs"], "ref": row["ref"], "title_match": out["title_match"],
                "retryable": not ok,
                "hint": ("для текста конкретного пункта используй /open {href} из entries"
                         if out["entries"] else None),
                "message": (None if ok else "sub_unavailable/sub_title_mismatch — "
                                            "повтори /search затем /sub")}

    try:
        return _respond(gui_call("/sub", work))
    except Busy as e:
        return jsonify({"ok": False, "error": "gui_busy", "busy": e.args[0]}), 504
    except GuiError as e:
        return jsonify({"ok": False, "kind": "unavailable", "error": "doc_unavailable",
                        "retryable": True, "message": str(e)}), 200


@app.post("/back")
def back():
    def work():
        _ensure_gui()
        _gui.go_back()
        # стек разворачиваем, а не растим: /back УМЕНЬШАЕТ глубину
        # (issue 2075ba12d5ca: 12 нажатий поднимали depth с 54 до 66)
        if state["nav"]:
            state["nav"].pop()
        else:
            state.setdefault("back_events", 0)
            state["back_events"] += 1
        st = _gui._state_suffix()
        sess = state["session"]
        on_search = bool(_RE_PAGE_QUERY.search(_norm(st)))
        same_query = _page_matches_query(st, sess.get("query") or "")
        if sess.get("docs"):
            sess["openable"] = bool(on_search or same_query)
        return {"ok": True, "state": st, "search_page": on_search,
                "depth": len(state["nav"]), "nav_events": len(state["nav"]),
                "back_events": state.get("back_events", 0),
                "session_openable": bool(sess.get("openable")),
                "session_query": sess.get("query") if sess.get("openable") else None,
                "note": (None if (on_search or same_query) else
                         "GUI не на странице выдачи: /doc, /sub и /page теперь "
                         "требуют повторного /search")}

    try:
        return jsonify(gui_call("/back", work))
    except Busy as e:
        return jsonify({"ok": False, "error": "gui_busy", "busy": e.args[0]}), 504


# --- трекер заявок -----------------------------------------------------------
_ISSUE_STATUSES = {"new", "triaged", "in_progress", "fixed", "wontfix", "duplicate"}
# Статусов «open»/«closed» в модели нет, но /issues?status=open — естественный
# запрос (так и клиенты, и сами репортёры искали «что не закрыто») и раньше
# молча возвращал пустой список. Разворачиваем их в группы.
_ISSUE_FINAL = {"fixed", "wontfix", "duplicate"}
_ISSUE_QUERY_ALIASES = {"open": "open", "unresolved": "open",
                        "closed": "closed", "done": "closed"}


def _issue_path(iid):
    return os.path.join(config.ISSUES_DIR, iid + ".json")


@app.post("/issues")
def issues_post():
    b = _body()
    if not b.get("title"):
        return jsonify({"ok": False, "error": "title_required"}), 400
    iid = uuid.uuid4().hex[:12]
    rec = {
        "id": iid, "title": b.get("title"), "description": b.get("description"),
        "endpoint": b.get("endpoint"), "severity": b.get("severity", "medium"),
        "steps": b.get("steps"), "expected": b.get("expected"), "actual": b.get("actual"),
        "reporter": b.get("reporter"), "status": "new", "resolution_note": None,
        "created": round(time.time(), 3), "history": [],
    }
    with io.open(_issue_path(iid), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    try:
        with io.open(os.path.join(config.LOGS_DIR, "issues.log"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass
    _metric("/issues", iid, 0.0, 202)
    return jsonify({"ok": True, "id": iid, "status": "new"}), 202


@app.get("/issues")
def issues_get():
    limit = int(request.args.get("limit", 200))
    status = request.args.get("status")
    group = _ISSUE_QUERY_ALIASES.get(status) if status else None
    if status and not group and status not in _ISSUE_STATUSES:
        # раньше любой левый status молча давал пустой список — по нему судили,
        # что «открытых нет»; теперь 400 со списком допустимых значений
        return jsonify({"ok": False, "error": "bad_status", "status": status,
                        "allowed": sorted(_ISSUE_STATUSES | set(_ISSUE_QUERY_ALIASES))}), 400
    items = []
    all_count = 0
    by_status = {}
    for fn in os.listdir(config.ISSUES_DIR):
        if not fn.endswith(".json"):
            continue
        try:
            with io.open(os.path.join(config.ISSUES_DIR, fn), encoding="utf-8") as f:
                r = json.load(f)
        except (OSError, ValueError):
            continue
        all_count += 1
        st = r.get("status") or "new"
        by_status[st] = by_status.get(st, 0) + 1
        if group == "open" and st in _ISSUE_FINAL:
            continue
        if group == "closed" and st not in _ISSUE_FINAL:
            continue
        if group is None and status and st != status:
            continue
        items.append(r)
    items.sort(key=lambda r: r.get("created", 0), reverse=True)
    return jsonify({"ok": True, "count": len(items[:limit]), "total": all_count,
                    "filter": status, "by_status": by_status,
                    "open_total": sum(v for k, v in by_status.items()
                                      if k not in _ISSUE_FINAL),
                    "patch_fields": sorted(_ISSUE_MUTABLE | {"note"}),
                    "statuses": sorted(_ISSUE_STATUSES),
                    "issues": items[:limit]})


@app.get("/issues/<iid>")
def issue_one(iid):
    p = _issue_path(iid)
    if not os.path.isfile(p):
        return jsonify({"ok": False, "error": "not_found"}), 404
    with io.open(p, encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/issues", methods=["PATCH"])
def issue_patch_collection():
    # раньше Flask отдавал HTML-405; заявка 03a15aee3896 просит внятный JSON
    return jsonify({"ok": False, "error": "id_required",
                    "detail": "PATCH принимается только по /issues/<id>",
                    "allowed_fields": sorted(_ISSUE_MUTABLE | {"note"})}), 405


_ISSUE_MUTABLE = {"title", "description", "endpoint", "severity",
                  "steps", "expected", "actual", "reporter", "status"}


@app.patch("/issues/<iid>")
def issue_patch(iid):
    p = _issue_path(iid)
    if not os.path.isfile(p):
        return jsonify({"ok": False, "error": "not_found"}), 404
    b = _body()
    unknown = sorted(set(b) - _ISSUE_MUTABLE - {"note"})
    if unknown:
        # молчаливое «ничего не сделал» теряло правку клиента (issue 03a15aee3896)
        return jsonify({"ok": False, "error": "unknown_field", "fields": unknown,
                        "allowed": sorted(_ISSUE_MUTABLE | {"note"})}), 400
    with io.open(p, encoding="utf-8") as f:
        r = json.load(f)
    st = b.get("status")
    if st and st not in _ISSUE_STATUSES:
        return jsonify({"ok": False, "error": "bad_status", "allowed": sorted(_ISSUE_STATUSES)}), 400
    if st:
        r["history"].append({"from": r.get("status"), "to": st,
                             "note": b.get("note"), "ts": round(time.time(), 3)})
        r["status"] = st
    if b.get("note"):
        r["resolution_note"] = b["note"]
    edited = []
    for k in ("title", "description", "endpoint", "severity", "steps",
              "expected", "actual", "reporter"):
        if k in b:
            r[k] = b[k]
            edited.append(k)
    if edited:
        r["edited"] = r.get("edited", []) + [{"fields": edited,
                                              "ts": round(time.time(), 3)}]
    with io.open(p, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    return jsonify({"ok": True, "edited_fields": edited, "issue": r})


# --- метрики: сводка ---------------------------------------------------------
@app.get("/metrics")
def metrics():
    if not os.path.isfile(_metrics_path):
        return jsonify({"ok": True, "count": 0, "by_path": {}})
    rows = []
    with io.open(_metrics_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    by = {}
    for r in rows:
        d = by.setdefault(r["path"], {"n": 0, "err": 0, "dur_sum": 0.0})
        d["n"] += 1
        d["dur_sum"] += r.get("dur_s", 0)
        if r.get("code", 200) >= 400:
            d["err"] += 1
    summary = {k: {"n": v["n"], "errors": v["err"],
                   "avg_s": round(v["dur_sum"] / max(v["n"], 1), 2)} for k, v in by.items()}
    return jsonify({"ok": True, "count": len(rows), "by_path": summary})


# --- CORS --------------------------------------------------------------------
@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PATCH,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


def main():
    # при старте попробуем подключиться к GUI (не блокируя запуск при его отсутствии)
    try:
        _gui.connect(timeout=5)
    except Exception:  # noqa: BLE001
        print("[warn] ConsultantPlusMainWnd ещё не открыт — поднимется при первом запросе.")
    app.run(host=config.HOST, port=config.PORT, threaded=True)


if __name__ == "__main__":
    main()
