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

from . import cache_store, config
from .consultant_gui import ConsultantGUI, GuiError, NotFound

app = Flask(__name__)

# --- единственная GUI-нитка --------------------------------------------------
_gui = ConsultantGUI()
gui_lock = threading.RLock()
state = {
    "busy": {"active": False, "rid": None, "path": None, "since": None, "last": None},
    "session": {"query": None, "category": None, "total": 0, "page_size": config.DEFAULT_PAGE_SIZE,
                "page": 1, "docs": [], "categories": []},
    "known_categories": list(config.CANONICAL_CATEGORIES),  # накопленные валидные имена (для hints/манифеста)
    "ref_titles": {},  # ref -> title из извлечённых ссылок (разрешает /open {ref})
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
    return jsonify({
        "service": "ConsultantPlus GUI REST",
        "endpoints": {
            "GET /health": "{ok}",
            "GET /state": "{busy, current, depth, nav, tabs}",
            "POST /search": "{query, page_size, category?, page?} -> выдача",
            "POST /page": "{page} -> docs[] страницы",
            "POST /doc": "{page, index} -> {kind,title,content?,entries?,links?}",
            "POST /sub": "{index} -> текст/структура подборки (entries[] с href)",
            "POST /open": "{title} | {ref} | {uri} -> прямой доступ (ref из links[]/href)",
            "POST /back": "-> вверх по стеку",
            "GET/POST/PATCH /issues": "трекер заявок",
            "GET /metrics": "сводка метрик",
        },
        "categories": state["known_categories"],
        "link_fields": ["ref", "title", "label", "href"],
        "notes": {
            "scope": config.SCOPE_SINGLE_SECTION,
            "single_session": True,
            "sequential": True,
            "gui_lock_timeout_s": config.GUI_LOCK_TIMEOUT,
            "doc_text": "Экспорт в Word -> *.rtf в C:\\Temp",
            "selection_rule": "без category — первый лист в порядке дерева; с category — точное/подстрочное имя из categories",
            "index_as_of": config.INDEX_AS_OF or "unknown",
            "empty_reason": ["no_matches", "list_not_rendered"],
        },
    })


@app.get("/health")
def health():
    try:
        hwnds_ok = _gui.connect(timeout=3)
        return jsonify({"ok": bool(hwnds_ok), "state": _gui._state_suffix(),
                        "index_as_of": config.INDEX_AS_OF or "unknown",
                        "index_as_of_source": "env CONSULTANT_INDEX_AS_OF" if config.INDEX_AS_OF else "not set",
                        "last_update": config.INDEX_AS_OF or None})
    except Exception:  # noqa: BLE001
        return jsonify({"ok": False, "index_as_of": config.INDEX_AS_OF or "unknown"})


@app.get("/state")
def get_state():
    # не берём gui_lock: читаем последний снимок + пытаемся лёгкий опрос окна
    out = {"busy": state["busy"], "current": state["session"]["query"],
           "depth": len(state["nav"]), "tabs": [], "session": {
               "query": state["session"]["query"], "category": state["session"]["category"],
               "total": state["session"]["total"], "page": state["session"]["page"],
               "page_size": state["session"]["page_size"], "docs_count": len(state["session"]["docs"]),
           }}
    if not state["busy"]["active"]:
        try:
            out.update(_gui.get_state())
        except Exception:  # noqa: BLE001
            pass
    return jsonify(out)


def _pages(total, page_size):
    if not total or total <= 0:
        return 0
    return (total + page_size - 1) // page_size


def _norm(s):
    """Нормализация имени раздела: nbsp→пробел, нижний регистр, схлопнуть пробелы."""
    s = (s or "").replace("\u00a0", " ").strip().lower()
    return re.sub(r"\s+", " ", s)


def _match_category(cats, requested):
    """Робастный поиск раздела по имени: точное → подстрока (в обе стороны).
    Возвращает dict-категорию или None."""
    rl = _norm(requested)
    if not rl:
        return None
    for c in cats:  # 1) точное совпадение
        if _norm(c["name"]) == rl:
            return c
    cands = [c for c in cats if rl in _norm(c["name"]) or _norm(c["name"]) in rl]
    if cands:  # 2) самое короткое (самое точное) вхождение
        cands.sort(key=lambda c: len(_norm(c["name"])))
        return cands[0]
    return None


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
            hit["cached"] = True
            return jsonify(hit)

    def work():
        _ensure_gui()
        # сброс сессии: при любой ошибке ниже docs останутся пустыми → /doc честно отдаст 400
        state["session"].update(query=None, category=None, total=0, page=page,
                                page_size=page_size, docs=[])
        _gui.do_search(query)
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
        # выбрать раздел
        sel = None
        sel_count = 0
        selection_rule = None
        if category:
            chosen = _match_category(cats, category)
            if not chosen:
                raise NotFound("unknown_category")
            _gui.select_category(chosen["name"])
            sel = chosen["name"]
            sel_count = chosen.get("count") or 0
            selection_rule = "requested_category"
        else:
            leaves = [c for c in cats if c["leaf"]]
            if leaves:
                chosen = leaves[0]  # детерминированно: первый лист в порядке дерева
                _gui.select_category(chosen["name"])
                sel = chosen["name"]
                sel_count = chosen.get("count") or 0
            selection_rule = "first_leaf_in_tree_order"
        start_abs = (page - 1) * page_size + 1
        docs = []
        total = 0
        empty_reason = None
        if not cats:
            empty_reason = "no_matches"
        elif sel_count == 0:
            empty_reason = "no_matches"
        else:
            titles = _gui.enumerate_titles(start_abs, page_size)
            qn = _norm(query)
            for i, (ab, tt) in enumerate(titles):
                if not tt or _norm(tt) == qn or tt.startswith("Поиск:"):
                    continue  # отбросить эхо запроса / нечитаемый заголовок (issue cf37)
                docs.append({"index": len(docs), "abs": ab, "title": tt})
            _, pos_total = _gui._doc_position()
            total = pos_total or sel_count
            if not docs:
                empty_reason = "list_not_rendered"
        expected = min(page_size, max(0, total - start_abs + 1)) if total else 0
        sections = [{"name": c["name"], "count": c.get("count")} for c in cats if c["leaf"]]
        resp = {
            "ok": True, "query": query, "total": total,
            "pages": _pages(total, page_size), "page": page, "page_size": page_size,
            "docs": docs, "categories": cats, "sections": sections,
            "selected_category": sel, "requested_category": category,
            "selection_rule": selection_rule,
            "scope": config.SCOPE_SINGLE_SECTION, "truncated": False,
            "parsed_count": len(docs), "expected_count": expected,
            "filter_applied": bool(category),
            "empty_reason": empty_reason,
            "index_as_of": config.INDEX_AS_OF or "unknown",
            "note": _beyond_index_note(query),
        }
        # обновить сессию
        state["session"].update(query=query, category=sel, total=total,
                                page=page, page_size=page_size, docs=docs, categories=cats)
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
        return jsonify({"ok": False, "error": "gui_error", "detail": str(e)}), 502

    cache_store.put_search(ckey, resp)
    return jsonify(resp)


@app.post("/page")
def page():
    b = _body()
    p = max(1, int(b.get("page") or 1))
    sess = state["session"]
    if not sess["query"]:
        return jsonify({"ok": False, "error": "no_active_search"}), 400

    def work():
        _ensure_gui()
        ps = sess["page_size"]
        titles = _gui.enumerate_titles((p - 1) * ps + 1, ps)
        docs = [{"index": i, "abs": ab, "title": tt} for i, (ab, tt) in enumerate(titles) if tt]
        sess.update(page=p, docs=docs)
        return {"ok": True, "page": p, "docs": docs, "total": sess["total"]}

    try:
        return jsonify(gui_call("/page", work))
    except Busy as e:
        return jsonify({"ok": False, "error": "gui_busy", "busy": e.args[0]}), 504


@app.post("/doc")
def doc():
    b = _body()
    p = max(1, int(b.get("page") or 1))
    idx = int(b.get("index") or 0)
    sess = state["session"]
    docs = sess["docs"]
    if not (0 <= idx < len(docs)):
        return jsonify({"ok": False, "error": "index_out_of_range",
                        "parsed_count": len(docs)}), 400
    title = docs[idx].get("title") or ""
    dkey = cache_store.doc_key(title)
    if not b.get("fresh"):
        hit = cache_store.get_doc(dkey)
        if hit:
            hit["cached"] = True
            return jsonify(hit)

    def work():
        _ensure_gui()
        abs_i = docs[idx]["abs"]
        _gui.ensure_doc_open(abs_i)
        t, text, links = None, "", []
        for _attempt in range(3):
            _gui.goto_doc_index(abs_i)
            t, text, links = _gui.export_current_doc(dkey)
            if text and len(text) > config.DOC_MIN_CONTENT:
                break
            time.sleep(0.6)
        _remember_refs(links)
        if not text or len(text) <= config.DOC_MIN_CONTENT:
            kind = "unavailable"
        elif len(links) >= 5:
            kind = "collection"
        else:
            kind = "document"
        out_links = [_link_out(l) for l in links]
        entries = (out_links if kind == "collection" else [])
        resp = {"ok": kind != "unavailable", "kind": kind, "title": t, "content": text,
                "content_len": len(text or ""), "entries": entries, "links": out_links,
                "retryable": kind == "unavailable",
                "message": (None if kind != "unavailable" else
                            "doc_unavailable: экспорт пуст/обрезан — повтори /doc")}
        cache_store.put_doc(dkey, {k: resp[k] for k in ("kind", "title", "message")}, text)
        return resp

    try:
        return jsonify(gui_call("/doc", work))
    except Busy as e:
        return jsonify({"ok": False, "error": "gui_busy", "busy": e.args[0]}), 504
    except GuiError as e:
        return jsonify({"ok": False, "kind": "unavailable", "title": title,
                        "error": "doc_unavailable", "retryable": True,
                        "message": str(e)}), 200


@app.post("/open")
def open_():
    b = _body()
    title = b.get("title")
    ref = b.get("ref")
    uri = b.get("uri")
    if not title and uri and "ref=" in uri:
        ref = uri.split("ref=")[-1].strip()
    # разрешить ref → title из накопленной карты (refs, которые мы сами отдавали в links[])
    if not title and ref:
        title = state["ref_titles"].get(ref)
    if not title:
        return jsonify({"ok": False, "error": "title_or_resolvable_ref_required",
                        "detail": "передай {title} или {ref}/{uri}, ранее полученный из links[]; "
                                  "неизвестный ref через GUI не открывается"}), 400

    def work():
        _ensure_gui()
        # поиск по заголовку, выбрать раздел, открыть ИМЕННО подходящий документ (не первый-попади)
        _gui.do_search(title)
        _gui.open_all_results()
        cats = _gui.read_categories()
        leaves = [c for c in cats if c["leaf"] and c.get("count")]
        leaves.sort(key=lambda c: c["count"] or 0, reverse=True)
        if leaves:
            _gui.select_category(leaves[0]["name"])
        titles = _gui.enumerate_titles(1, max(config.DEFAULT_PAGE_SIZE, 10))
        qn = _norm(title)
        pick = None
        for ab, tt in titles:
            n = _norm(tt)
            if not n:
                continue
            if qn and (qn in n or n in qn):
                pick = ab
                break
        if pick is None and titles:
            pick = titles[0][0]
        if pick is None:
            pick = 1
        _gui.ensure_doc_open(pick)
        t, text, links = None, "", []
        for _attempt in range(3):
            _gui.goto_doc_index(pick)
            t, text, links = _gui.export_current_doc(cache_store.doc_key(title))
            if text and len(text) > config.DOC_MIN_CONTENT:
                break
            time.sleep(0.6)
        _remember_refs(links)
        if not text or len(text) <= config.DOC_MIN_CONTENT:
            kind = "unavailable"
        elif len(links) >= 5:
            kind = "collection"
        else:
            kind = "document"
        out_links = [_link_out(l) for l in links]
        return {"ok": kind != "unavailable", "kind": kind, "title": t, "content": text,
                "content_len": len(text or ""),
                "entries": (out_links if kind == "collection" else []),
                "links": out_links, "retryable": kind == "unavailable",
                "resolved_from_ref": bool(ref and b.get("title") is None),
                "matched_abs": pick}

    try:
        return jsonify(gui_call("/open", work))
    except Busy as e:
        return jsonify({"ok": False, "error": "gui_busy", "busy": e.args[0]}), 504
    except GuiError as e:
        return jsonify({"ok": False, "error": "gui_error", "detail": str(e)}), 502


@app.post("/sub")
def sub():
    b = _body()
    idx = int(b.get("index") or 0)
    docs = state["session"]["docs"]
    if not (0 <= idx < len(docs)):
        return jsonify({"ok": False, "error": "index_out_of_range"}), 400

    def work():
        _ensure_gui()
        abs_i = docs[idx]["abs"]
        _gui.ensure_doc_open(abs_i)
        t, text, links = None, "", []
        for _attempt in range(3):
            _gui.goto_doc_index(abs_i)
            t, text, links = _gui.export_current_doc(cache_store.doc_key(docs[idx]["title"]))
            if text and len(text) > config.DOC_MIN_CONTENT:
                break
            time.sleep(0.6)
        _remember_refs(links)
        out_links = [_link_out(l) for l in links]
        kind = ("collection" if len(links) >= 5 else
                ("document" if text and len(text) > config.DOC_MIN_CONTENT else "unavailable"))
        return {"ok": kind != "unavailable", "kind": kind, "title": t, "text": text,
                "content_len": len(text or ""),
                "entries": (out_links if kind == "collection" else []),
                "links": out_links, "retryable": kind == "unavailable",
                "hint": ("для текста конкретного пункта используй /open {href} из entries")}

    try:
        return jsonify(gui_call("/sub", work))
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
        state["nav"].append({"t": time.time(), "state": _gui._state_suffix()})
        return {"ok": True, "state": _gui._state_suffix()}

    try:
        return jsonify(gui_call("/back", work))
    except Busy as e:
        return jsonify({"ok": False, "error": "gui_busy", "busy": e.args[0]}), 504


# --- трекер заявок -----------------------------------------------------------
_ISSUE_STATUSES = {"new", "triaged", "in_progress", "fixed", "wontfix", "duplicate"}


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
    items = []
    for fn in os.listdir(config.ISSUES_DIR):
        if not fn.endswith(".json"):
            continue
        try:
            with io.open(os.path.join(config.ISSUES_DIR, fn), encoding="utf-8") as f:
                r = json.load(f)
        except (OSError, ValueError):
            continue
        if status and r.get("status") != status:
            continue
        items.append(r)
    items.sort(key=lambda r: r.get("created", 0), reverse=True)
    return jsonify({"ok": True, "count": len(items[:limit]), "issues": items[:limit]})


@app.get("/issues/<iid>")
def issue_one(iid):
    p = _issue_path(iid)
    if not os.path.isfile(p):
        return jsonify({"ok": False, "error": "not_found"}), 404
    with io.open(p, encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.patch("/issues/<iid>")
def issue_patch(iid):
    p = _issue_path(iid)
    if not os.path.isfile(p):
        return jsonify({"ok": False, "error": "not_found"}), 404
    b = _body()
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
    with io.open(p, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    return jsonify({"ok": True, "issue": r})


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
