# -*- coding: utf-8 -*-
"""Деградационные тесты контракта ConsultantPlus REST (stdlib unittest, без GUI).

Замоканный ConsultantGUI → детерминированно проверяем ровно ту логику формирования
ответов, где живут закрытые issues (волны 1–13). Запуск:

    venv\\Scripts\\python.exe -m unittest discover -s tests -v

Дополнительно есть живой прогон: server/_regress.py и server/_live_test.py (по GUI).
"""
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app as A  # noqa: E402
from server import config  # noqa: E402
from server import rtf_util  # noqa: E402
from server.consultant_gui import NotFound  # noqa: E402


class FakeGUI:
    """Замена ConsultantGUI с настраиваемым поведением (без реального окна)."""

    def __init__(self):
        self.cats = []
        self.titles = []          # [(abs, title)]
        self.pos = (1, 0)         # (cur, total) из _doc_position
        self.export = ("Заголовок", "текст" * 50, [])  # (title, text, links)
        self.selected = []
        self.fail_read = False
        self.page_state = ""      # что показывает окно после do_search
        self.search_calls = 0
        self.back_calls = 0
        self.connect_calls = 0
        self.enum_calls = 0
        # имитация «список не отрисовался с первого раза, со второй — отрисовался»
        self.fail_first_enumeration = False
        # параметры перечисления, чтобы проверять, что объём раздела реально
        # передаётся в GUI (issue e7f7bb098cfd)
        self.enum_args = []
        # True = вести как живой ConsultantGUI: при несовпадении объёма
        # читалки с разделом заголовки не отдавать
        self.honor_expect_total = False

    # подключение/окно
    def connect(self, timeout=30):
        self.connect_calls += 1
        return [1]

    def ensure_window(self):
        pass

    def close_modal_dialogs(self):
        self.modals_closed = getattr(self, "modals_closed", 0) + 1
        return 0

    def close_extra_tabs(self, keep=1):
        return 0

    def reset_for_search(self):
        pass

    def get_state(self):
        return {"tabs": [], "state": self._state_suffix(),
                "doc_index": self.pos[0], "doc_total": self.pos[1]}

    def _state_suffix(self):
        return self.page_state or "Поиск: тест"

    def title(self):
        return "КонсультантПлюс [%s]" % self._state_suffix()

    def page_info(self):
        return {"state": self._state_suffix(),
                "doc_index": self.pos[0], "doc_total": self.pos[1]}

    def go_back(self):
        self.back_calls += 1
        # «Назад» уводит с страницы результатов — имитируем реальный ход стека
        self.page_state = "Стартовая страница"

    # поиск/дерево
    def do_search(self, query):
        self.search_calls += 1
        self.page_state = "Поиск: " + query
        return True

    def open_all_results(self, wait_button=None):
        return True

    def read_categories(self):
        if self.fail_read:
            return []
        return list(self.cats)

    def select_category(self, name):
        self.selected.append(name)
        return True

    def wait_results(self, query, timeout=None):
        return True

    # выдача
    def enumerate_titles(self, start_abs, count, query_flat=None, expect_total=None):
        self.enum_calls += 1
        self.enum_args.append({"start_abs": start_abs, "count": count,
                               "query_flat": query_flat, "expect_total": expect_total})
        if self.fail_first_enumeration and self.enum_calls == 1:
            return []
        if self.honor_expect_total and expect_total and self.pos[1] != expect_total:
            return []          # листаем НЕ список этого запроса — пусто
        return list(self.titles)

    def _doc_position(self):
        return self.pos

    def goto_doc_index(self, target_abs):
        return True

    def ensure_doc_open(self, abs_i):
        return abs_i

    def next_doc(self):
        return True

    def export_current_doc(self, key):
        return tuple(self.export)


def _cat(name, count=None, leaf=True):
    return {"name": name, "count": count, "raw_count": str(count or ""), "leaf": leaf}


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.fake = FakeGUI()
        self._real_gui = A._gui
        A._gui = self.fake
        # hermetic: без реального кэша на диске
        self._cs = A.cache_store
        A.cache_store = _NoCache()
        # чистое состояние сессии
        A.state["session"].update(query=None, category=None, total=None, docs=[],
                                  categories=[], openable=False, from_cache=False,
                                  section_count=None)
        A.state["known_categories"] = list(config.CANONICAL_CATEGORIES)
        A.state["ref_titles"] = {}
        A.state["last_live"] = {}
        A.state["index_observed"] = {"max": None, "evidence": []}
        A.state["nav"] = []
        # GUI считаем свободным: иначе /health и /state будут честно отказываться
        # опрашивать окно (поведение проверено отдельными тестами)
        A.state["busy"].update(active=False, rid=None, path=None)
        A.app.config["TESTING"] = True
        self.client = A.app.test_client()

    def tearDown(self):
        A._gui = self._real_gui
        A.cache_store = self._cs

    def post(self, path, body):
        r = self.client.post(path, data=json.dumps(body),
                             content_type="application/json")
        return r.status_code, json.loads(r.data.decode("utf-8"))

    def get(self, path):
        r = self.client.get(path)
        return r.status_code, json.loads(r.data.decode("utf-8"))


class _NoCache:
    @staticmethod
    def search_key(*a, **k):
        return "k"

    @staticmethod
    def doc_key(*a, **k):
        return "d"

    @staticmethod
    def get_search(*a, **k):
        return None

    @staticmethod
    def get_doc(*a, **k):
        return None

    @staticmethod
    def put_search(*a, **k):
        pass

    @staticmethod
    def put_doc(*a, **k):
        pass


import hashlib
from unittest import mock


class _MemCache:
    """Кэш как на диске, но в памяти — проверяем восстановление сессии из кэша."""

    def __init__(self):
        self.search = {}
        self.docs = {}

    @staticmethod
    def search_key(query, category, page, page_size, sort=None):
        return hashlib.sha1("|".join(str(p) for p in
                                     (query, category, page, page_size)).encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def doc_key(title):
        return hashlib.sha1((title or "").strip().encode("utf-8")).hexdigest()[:16]

    def get_search(self, key, ttl=None):
        obj = self.search.get(key)
        if obj is None:
            return None
        obj = dict(obj)
        obj["_age"] = 1.5
        return obj

    def put_search(self, key, payload):
        self.search[key] = json.loads(json.dumps(payload))

    def get_doc(self, key, ttl=None):
        obj = self.docs.get(key)
        if obj is None:
            return None
        obj = dict(obj)
        obj["_age"] = 2.0
        return obj

    def put_doc(self, key, meta, content):
        self.docs[key] = {"kind": meta.get("kind"), "title": meta.get("title"),
                          "content": content, "content_len": len(content or "")}


# ---------------------------------------------------------------- unit: хелперы
class TestHelpers(unittest.TestCase):
    def test_norm_nbsp_case(self):
        self.assertEqual(A._norm("Судебная\u00a0Практика"), "судебная практика")

    def test_match_exact(self):
        cats = [_cat("Судебная практика", 100), _cat("Нормативные акты", 5)]
        self.assertEqual(A._match_category(cats, "Судебная практика")["name"],
                         "Судебная практика")

    def test_match_case_and_nbsp(self):
        cats = [_cat("Судебная\u00a0практика", 100)]
        self.assertIsNotNone(A._match_category(cats, "судебная практика"))

    def test_match_substring_both_ways(self):
        cats = [_cat("Решения высших судов", 50)]
        self.assertIsNotNone(A._match_category(cats, "решения высших"))   # префикс
        self.assertIsNotNone(A._match_category(cats, "Решения высших судов и КС РФ"))  # суперстрока

    def test_match_none(self):
        cats = [_cat("Судебная практика", 100)]
        self.assertIsNone(A._match_category(cats, "совершенно иное"))

    def test_pages(self):
        self.assertEqual(A._pages(0, 5), 0)
        self.assertEqual(A._pages(18, 5), 4)
        self.assertEqual(A._pages(10, 5), 2)

    def test_link_out_adds_href(self):
        l = {"ref": "ABC", "title": "T"}
        o = A._link_out(l)
        self.assertEqual(o["href"], "consultantplus://offline/ref=ABC")
        self.assertEqual(o["label"], "T")

    def test_beyond_index_note_future_year(self):
        old = config.INDEX_AS_OF
        try:
            config.INDEX_AS_OF = "2026-07-01"
            self.assertIsNotNone(A._beyond_index_note("акт от октябрь 2027"))
            self.assertIsNone(A._beyond_index_note("акт от март 2026"))
        finally:
            config.INDEX_AS_OF = old


class TestRtfLinks(unittest.TestCase):
    def test_extract_links_href_label(self):
        fd, p = tempfile.mkstemp(suffix=".rtf")
        os.close(fd)
        try:
            with io.open(p, "w", encoding="cp1251") as f:
                f.write('{\\rtf1\\ansi\\ansicpg1251 '
                        '{\\field{\\*\\fldinst{HYPERLINK '
                        '"consultantplus://offline/ref=17C4769E8F18E711"}}'
                        '{\\fldrslt Позиция ВС }}{\\par}}')
            links = rtf_util.extract_links(p)
            self.assertEqual(len(links), 1)
            self.assertEqual(links[0]["ref"], "17C4769E8F18E711")
            self.assertEqual(links[0]["href"],
                             "consultantplus://offline/ref=17C4769E8F18E711")
            self.assertIn("label", links[0])
        finally:
            os.remove(p)


# ---------------------------------------------------------------- /health, /
class TestMeta(BaseCase):
    def test_health_has_index_as_of(self):
        s, j = self.get("/health")
        self.assertEqual(s, 200)
        self.assertTrue(j["ok"])
        self.assertIn("index_as_of", j)  # issue 04a1
        self.assertEqual(self.fake.connect_calls, 1)   # GUI реально опрошен
        self.assertTrue(j["gui"]["probed"])

    def test_health_does_not_touch_gui_while_busy(self):
        # /health не имеет права дёргать окно из второго потока, пока идёт
        # навигация: раньше это была гонка pywinauto между потоками
        A.state["busy"].update(active=True, rid="r", path="/search")
        try:
            s, j = self.get("/health")
        finally:
            A.state["busy"].update(active=False, rid=None, path=None)
        self.assertEqual(s, 200)
        self.assertEqual(self.fake.connect_calls, 0)   # ни одного обращения к GUI
        self.assertFalse(j["gui"]["probed"])
        self.assertIsNone(j["gui"]["window"])
        self.assertIn("занят", j["gui"]["note"])

    def test_manifest_lists_categories(self):
        s, j = self.get("/")
        self.assertEqual(s, 200)
        self.assertIn("categories", j)          # issue d815
        self.assertGreater(len(j["categories"]), 0)
        self.assertIn("href", j["link_fields"])  # issue 62ca


# ---------------------------------------------------------------- /search
class TestSearch(BaseCase):
    def test_empty_query_400(self):
        s, j = self.post("/search", {"query": "   "})
        self.assertEqual(s, 400)
        self.assertEqual(j["error"], "empty_query")

    def test_happy_shape_and_integrity(self):
        self.fake.cats = [_cat("Судебная практика", 18), _cat("Нормативные акты", 3)]
        self.fake.titles = [(1, "Документ раз"), (2, "Документ два"),
                            (3, "Документ три")]
        self.fake.pos = (3, 18)
        s, j = self.post("/search", {"query": "договор", "page_size": 3, "fresh": True})
        self.assertEqual(s, 200)
        self.assertEqual(j["total"], 18)
        self.assertEqual(len(j["docs"]), 3)
        self.assertEqual(j["parsed_count"], j["expected_count"])
        self.assertEqual(j["selected_category"], "Судебная практика")
        self.assertEqual(j["selection_rule"], "first_leaf_in_tree_order")  # 67fa
        self.assertFalse(j["truncated"])          # все 3 строки прочитаны
        self.assertIn("sections", j)

    def test_deterministic_selection_no_category(self):
        # без category всегда первый лист в порядке дерева, независимо от count
        self.fake.cats = [_cat("Альфа", 1), _cat("Бета", 999)]
        self.fake.titles = [(1, "Док")]
        self.fake.pos = (1, 5)
        s, j = self.post("/search", {"query": "x", "fresh": True})
        self.assertEqual(j["selected_category"], "Альфа")

    def test_category_exact_accepted(self):
        # issue 47ac: имя из categories[] должно приниматься
        self.fake.cats = [_cat("Судебная практика", 50)]
        self.fake.titles = [(1, "Док один")]
        self.fake.pos = (1, 50)
        s, j = self.post("/search", {"query": "ск", "category": "Судебная практика",
                                     "fresh": True})
        self.assertEqual(s, 200)
        self.assertEqual(j["selected_category"], "Судебная практика")
        self.assertTrue(j["filter_applied"])

    def test_unknown_category_400_nonempty_categories(self):
        # issue 47ac: categories[] в 400 не пустой (fallback на known_categories)
        self.fake.cats = []          # дерево не отрисовалось
        s, j = self.post("/search", {"query": "x", "category": "НЕТ ТАКОГО",
                                     "fresh": True})
        self.assertEqual(s, 400)
        self.assertEqual(j["error"], "unknown_category")
        self.assertGreater(len(j["categories"]), 0)
        self.assertEqual(j["requested_category"], "НЕТ ТАКОГО")

    def test_no_matches_reason(self):
        # пустое дерево — ЭТО НЕ «нет результатов»: technical failure, retryable
        self.fake.cats = []          # дерево не прочиталось
        s, j = self.post("/search", {"query": "qqzzxx", "fresh": True})
        self.assertEqual(s, 200)
        self.assertFalse(j["ok"])
        self.assertEqual(j["empty_reason"], "tree_not_read")
        self.assertEqual(j["error"], "tree_not_read")
        self.assertTrue(j["retryable"])
        self.assertIsNone(j["total"])         # не вранье «0Found»
        self.assertIn("НЕ «нет документов", j["note"])

    def test_zero_count_section_no_matches(self):
        self.fake.cats = [_cat("Судебная практика", 0)]
        s, j = self.post("/search", {"query": "q", "category": "Судебная практика",
                                     "fresh": True})
        self.assertEqual(j["empty_reason"], "no_matches")

    def test_echo_titles_filtered(self):
        # issue cf37: заголовок-эхо запроса не должен попадать в docs[]
        q = "обязанность по внесению платы"
        self.fake.cats = [_cat("Судебная практика", 10)]
        self.fake.titles = [(1, q), (2, "Реальный документ-постановление"), (3, q)]
        self.fake.pos = (3, 10)
        s, j = self.post("/search", {"query": q, "page_size": 3, "fresh": True})
        titles = [d["title"] for d in j["docs"]]
        self.assertNotIn(q, titles)
        self.assertIn("Реальный документ-постановление", titles)
        # индексы континуальны 0..n-1
        self.assertEqual([d["index"] for d in j["docs"]], list(range(len(j["docs"]))))

    def test_list_not_rendered(self):
        # раздел непустой, но строки не перечислились → list_not_rendered
        self.fake.cats = [_cat("Судебная практика", 30)]
        self.fake.titles = []
        self.fake.pos = (None, None)
        s, j = self.post("/search", {"query": "q", "fresh": True})
        self.assertEqual(j["empty_reason"], "list_not_rendered")
        self.assertEqual(j["enum_attempts"], 2)      # была реальная 2-я попытка
        self.assertEqual(self.fake.enum_calls, 2)
        self.assertEqual(self.fake.modals_closed, 1)  # модалки сбрасывались
        self.assertIn("30 документов", j["note"])     # не выдаём это за «ничего не найдено»


# ---------------------------------------------------------------- /doc
class TestDoc(BaseCase):
    def _seed_session(self, docs=None, openable=True):
        A.state["session"].update(
            query="q", category="Судебная практика", total=10,
            page=1, page_size=5, openable=openable,
            docs=docs if docs is not None else
            [{"index": 0, "abs": 1, "title": "Док раз",
              "ref": "pos:1"}])

    def test_no_session_docs_honest_400(self):
        # issue aa213ed6f361: вместо туманного index_out_of_range — честная причина
        A.state["session"]["docs"] = []
        s, j = self.post("/doc", {"page": 1, "index": 0})
        self.assertEqual(s, 400)
        self.assertEqual(j["error"], "no_openable_list")
        self.assertTrue(j["retryable"])

    def test_index_out_of_range_400(self):
        self._seed_session()
        s, j = self.post("/doc", {"index": 7})
        self.assertEqual(s, 400)
        self.assertEqual(j["error"], "index_out_of_range")
        self.assertEqual(j["valid_range"], [0, 0])

    def test_row_1_based_alias_and_ref(self):
        # issue 38b7c8795a8a: база индексов документирована + ref из выдачи
        self._seed_session(docs=[{"index": 0, "abs": 1, "title": "Док раз", "ref": "pos:1"},
                                   {"index": 1, "abs": 2, "title": "Док два", "ref": "pos:2"}])
        self.fake.export = ("Док два", "содержательный текст " * 20, [])
        s, j = self.post("/doc", {"row": 2, "fresh": True})
        self.assertEqual(j["matched_index"], 1)
        self.assertEqual(j["matched_title"], "Док два")
        self.assertEqual(j["index_base"], 0)
        s2, j2 = self.post("/doc", {"ref": "pos:2", "fresh": True})
        self.assertEqual(j2["matched_index"], 1)

    def test_stale_cleared_after_failed_search(self):
        # issue f501: /search с битой category → 400, и docs очищаются → /doc 400
        self.fake.cats = [_cat("Судебная практика", 5)]
        self.fake.titles = [(1, "Док один")]  # не эхо
        self.fake.pos = (1, 5)
        self.post("/search", {"query": "q", "fresh": True})       # успех, docs есть
        self.post("/search", {"query": "q2", "category": "НЕТ", "fresh": True})  # 400
        s, j = self.post("/doc", {"page": 1, "index": 0})
        self.assertEqual(s, 400)          # не отдал stale-содержимое
        self.assertEqual(j["error"], "no_openable_list")

    def test_document_kind_and_links_href(self):
        # issue 62ca: links с ref/title/label/href
        self._seed_session()
        links = [{"ref": "R%d" % i, "title": "Т%d" % i, "label": "Т%d" % i,
                  "href": "consultantplus://offline/ref=R%d" % i} for i in range(6)]
        self.fake.export = ("Док раз", "содержательный текст документа " * 20, links)
        s, j = self.post("/doc", {"page": 1, "index": 0, "fresh": True})
        self.assertEqual(s, 200)
        self.assertEqual(j["kind"], "collection")   # >=5 ссылок → collection
        self.assertTrue(j["ok"])
        self.assertEqual(j["links"][0]["href"], "consultantplus://offline/ref=R0")
        self.assertTrue(len(j["entries"]) > 0)       # issue: entries непустой у collection

    def test_unavailable_honest_not_masked(self):
        # issue c69d: крошечный контент → ok=false, kind=unavailable, retryable (не маскировка)
        self._seed_session()
        self.fake.export = ("", "мал", [])
        s, j = self.post("/doc", {"page": 1, "index": 0, "fresh": True})
        self.assertEqual(j["kind"], "unavailable")
        self.assertFalse(j["ok"])
        self.assertTrue(j["retryable"])

    def test_remembers_ref_titles(self):
        self._seed_session()
        links = [{"ref": "ABCDEF", "title": "Очень длинный заголовок позиции",
                  "label": "Очень длинный заголовок позиции",
                  "href": "consultantplus://offline/ref=ABCDEF"}] * 6
        self.fake.export = ("Док", "текст " * 50, links)
        self.post("/doc", {"page": 1, "index": 0, "fresh": True})
        self.assertIn("ABCDEF", A.state["ref_titles"])


# ---------------------------------------------------------------- /open
class TestOpen(BaseCase):
    def test_title_required_400(self):
        s, j = self.post("/open", {})
        self.assertEqual(s, 400)
        self.assertEqual(j["error"], "title_or_resolvable_ref_required")

    def test_open_by_title_matches_best(self):
        # issue 4ca: выбрать doc по совпадению заголовка, а не первый-попади
        self.fake.cats = [_cat("Судебная практика", 5)]
        self.fake.titles = [(1, "Библиографическая шапка"), (2, "Постановление Пленума ВС РФ N 39")]
        self.fake.pos = (2, 5)
        links = [{"ref": "R", "title": "T", "label": "T", "href": "h"}]
        self.fake.export = ("Постановление Пленума ВС РФ N 39",
                            "полный текст постановления " * 30, links)
        s, j = self.post("/open", {"title": "Постановление Пленума ВС РФ N 39"})
        self.assertEqual(s, 200)
        self.assertTrue(j["ok"])
        self.assertGreater(j["content_len"], 40)
        self.assertEqual(j["matched_abs"], 2)   # именно подходящий, не шапка

    def test_open_by_resolvable_ref(self):
        # issue e917: ref из ранее виденных links[] разрешается
        A.state["ref_titles"]["MYREF"] = "Налоговый кодекс часть вторая"
        self.fake.cats = [_cat("Нормативные акты", 5)]
        self.fake.titles = [(1, "Налоговый кодекс часть вторая")]
        self.fake.pos = (1, 5)
        self.fake.export = ("Налоговый кодекс часть вторая", "ст 333.19 " * 30, [])
        s, j = self.post("/open", {"ref": "MYREF"})
        self.assertEqual(s, 200)
        self.assertTrue(j.get("resolved_from_ref"))

    def test_open_unknown_ref_400(self):
        s, j = self.post("/open", {"ref": "UNKNOWN_REF_XYZ"})
        self.assertEqual(s, 400)
        self.assertEqual(j["error"], "title_or_resolvable_ref_required")

    def test_open_by_uri(self):
        A.state["ref_titles"]["URIREF"] = "ГК РФ часть первая"
        self.fake.cats = [_cat("Нормативные акты", 3)]
        self.fake.titles = [(1, "ГК РФ часть первая")]
        self.fake.pos = (1, 3)
        self.fake.export = ("ГК РФ часть первая", "текст кодекса " * 20, [])
        s, j = self.post("/open", {"uri": "consultantplus://offline/ref=URIREF"})
        self.assertEqual(s, 200)
        self.assertTrue(j["ok"])


# ---------------------------------------------------------------- /sub
class TestSub(BaseCase):
    def _seed(self):
        A.state["session"].update(query="q", openable=True,
                                  docs=[{"index": 0, "abs": 1, "title": "Д",
                                         "ref": "pos:1"}])

    def test_sub_not_masked_empty(self):
        # issue 464d: раньше ok=true content=0; теперь честный unavailable
        self._seed()
        self.fake.export = ("", "", [])
        s, j = self.post("/sub", {"index": 0})
        self.assertEqual(s, 200)
        self.assertFalse(j["ok"])
        self.assertTrue(j["retryable"])

    def test_sub_collection_entries_href(self):
        self._seed()
        links = [{"ref": "R%d" % i, "title": "П%d" % i, "label": "П%d" % i,
                  "href": "consultantplus://offline/ref=R%d" % i} for i in range(7)]
        self.fake.export = ("Д", "пункт подборки " * 20, links)
        s, j = self.post("/sub", {"index": 0})
        self.assertEqual(j["kind"], "collection")
        self.assertTrue(all("href" in e for e in j["entries"]))

    def test_sub_schema_matches_doc(self):
        # issue c1dbfe0f2947: контракт обещает content (не text) и entries[] у простого
        # документа тоже непустые, если ссылки есть; hint — только когда есть entries
        self._seed()
        links = [{"ref": "R1", "title": "П1", "label": "П1",
                  "href": "consultantplus://offline/ref=R1"}]
        self.fake.export = ("Д", "текст пункта " * 20, links)
        s, j = self.post("/sub", {"index": 0})
        self.assertTrue(j["ok"])
        self.assertIn("content", j)
        self.assertEqual(j["content"], j["text"])      # алиас обратной совместимости
        self.assertGreater(j["content_len"], 40)
        self.assertEqual(len(j["entries"]), 1)
        self.assertEqual(j["entries"][0]["href"], "consultantplus://offline/ref=R1")
        self.assertTrue(j["hint"])


# ---------------------------------------------------------------- /issues
class TestIssues(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = config.ISSUES_DIR
        config.ISSUES_DIR = self.tmp
        A.app.config["TESTING"] = True
        self.client = A.app.test_client()

    def tearDown(self):
        config.ISSUES_DIR = self._old

    def test_post_get_patch_roundtrip(self):
        r = self.client.post("/issues", data=json.dumps({"title": "Тест бага",
                             "severity": "high"}), content_type="application/json")
        self.assertEqual(r.status_code, 202)
        iid = json.loads(r.data)["id"]
        # лежит на диске персистентно
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, iid + ".json")))
        g = json.loads(self.client.get("/issues").data)
        self.assertEqual(g["count"], 1)
        p = self.client.patch("/issues/" + iid, data=json.dumps(
            {"status": "fixed", "note": "готово"}), content_type="application/json")
        pj = json.loads(p.data)
        self.assertEqual(pj["issue"]["status"], "fixed")
        self.assertEqual(pj["issue"]["resolution_note"], "готово")
        self.assertEqual(len(pj["issue"]["history"]), 1)

    def test_patch_bad_status_400(self):
        r = self.client.post("/issues", data=json.dumps({"title": "B"}),
                             content_type="application/json")
        iid = json.loads(r.data)["id"]
        p = self.client.patch("/issues/" + iid, data=json.dumps({"status": "bogus"}),
                              content_type="application/json")
        self.assertEqual(p.status_code, 400)

    def test_patch_description_is_mutable(self):
        # issue 03a15aee3896: правку описания раньше молча теряли
        r = self.client.post("/issues", data=json.dumps(
            {"title": "Баг", "description": "старое"}), content_type="application/json")
        iid = json.loads(r.data)["id"]
        p = self.client.patch("/issues/" + iid, data=json.dumps(
            {"description": "новое", "severity": "blocker"}),
            content_type="application/json")
        self.assertEqual(p.status_code, 200)
        pj = json.loads(p.data)
        self.assertEqual(pj["issue"]["description"], "новое")
        self.assertEqual(pj["issue"]["severity"], "blocker")
        self.assertEqual(sorted(pj["edited_fields"]), ["description", "severity"])

    def test_patch_unknown_field_400(self):
        r = self.client.post("/issues", data=json.dumps({"title": "B"}),
                             content_type="application/json")
        iid = json.loads(r.data)["id"]
        p = self.client.patch("/issues/" + iid, data=json.dumps({"zzz_unknown": 1}),
                              content_type="application/json")
        self.assertEqual(p.status_code, 400)
        self.assertEqual(json.loads(p.data)["error"], "unknown_field")

    def test_patch_collection_json_405(self):
        p = self.client.patch("/issues", data=json.dumps({"id": "x", "status": "fixed"}),
                              content_type="application/json")
        self.assertEqual(p.status_code, 405)
        self.assertFalse(json.loads(p.data)["ok"])

    def _mk(self, title, status=None):
        r = self.client.post("/issues", data=json.dumps({"title": title}),
                             content_type="application/json")
        iid = json.loads(r.data)["id"]
        if status:
            self.client.patch("/issues/" + iid, data=json.dumps({"status": status}),
                              content_type="application/json")
        return iid

    def test_status_open_is_a_group_not_an_empty_string(self):
        # ?status=open раньше молча давал []; по нему судили, что «всё закрыто»
        self._mk("A")                        # status=new
        self._mk("B", "in_progress")
        self._mk("C", "fixed")
        g = json.loads(self.client.get("/issues?status=open").data)
        self.assertEqual(g["count"], 2)
        self.assertEqual(g["open_total"], 2)
        self.assertEqual(g["by_status"]["fixed"], 1)
        self.assertEqual({r["title"] for r in g["issues"]}, {"A", "B"})
        c = json.loads(self.client.get("/issues?status=closed").data)
        self.assertEqual(c["count"], 1)
        # точное значение тоже работает
        n = json.loads(self.client.get("/issues?status=new").data)
        self.assertEqual(n["count"], 1)

    def test_status_bogus_400(self):
        r = self.client.get("/issues?status=anything")
        self.assertEqual(r.status_code, 400)
        j = json.loads(r.data)
        self.assertEqual(j["error"], "bad_status")
        self.assertIn("open", j["allowed"])


# ------------------------------------------------- кэш ↔ сессия (issues d3c7, bb95)
class TestCacheSession(BaseCase):
    def test_cache_hit_rehydrates_session(self):
        A.cache_store = _MemCache()
        self.fake.cats = [_cat("Судебная практика", 30)]
        self.fake.titles = [(1, "Первый документ ALPHA"), (2, "Второй документ BETA")]
        self.fake.pos = (2, 30)
        s1, j1 = self.post("/search", {"query": "альфа", "page_size": 2})
        self.assertTrue(j1["ok"])
        # другой запрос — сессия переезжает на него
        self.fake.titles = [(1, "Третий документ GAMMA")]
        self.post("/search", {"query": "гамма", "page_size": 1})
        self.assertEqual(A.state["session"]["query"], "гамма")
        # повтор первого запроса приходит из кэша: сессия ОБЯЗАНА вернуться к «альфа»
        self.fake.titles = [(1, "Третий документ GAMMA")]
        s3, j3 = self.post("/search", {"query": "альфа", "page_size": 2})
        self.assertTrue(j3.get("cached"))
        self.assertIsNotNone(j3.get("_age"))
        self.assertEqual(A.state["session"]["query"], "альфа")
        self.assertEqual([d["title"] for d in A.state["session"]["docs"]],
                         ["Первый документ ALPHA", "Второй документ BETA"])
        self.assertTrue(A.state["session"]["openable"])
        # и /doc адресует строку этой же выдачи, а не соседнего запроса
        self.fake.export = ("Первый документ ALPHA", "тело " * 40, [])
        s4, j4 = self.post("/doc", {"index": 0})
        self.assertEqual(j4["matched_title"], "Первый документ ALPHA")
        self.assertEqual(j4["title_match"], "yes")


# ------------------------------------------------- защита от протечки выдачи
class TestLeakGuards(BaseCase):
    def test_live_search_rejects_previous_list(self):
        # issue bb9515a15b8e: второй live-/search отдал тот же список
        self.fake.cats = [_cat("Судебная практика", 914)]
        self.fake.titles = [(1, "Документ один ООО"), (2, "Документ два ООО")]
        self.fake.pos = (2, 914)
        s1, j1 = self.post("/search", {"query": "ключевая ставка", "page_size": 2,
                                       "fresh": True})
        self.assertTrue(j1["ok"])
        s2, j2 = self.post("/search", {"query": "коап ред от 26 06 2026 обзор",
                                       "page_size": 2, "fresh": True})
        self.assertFalse(j2["ok"])
        self.assertTrue(j2["stale_suspect"])
        self.assertEqual(j2["empty_reason"], "list_not_rendered")
        self.assertEqual(j2["docs"], [])
        self.assertTrue(j2["retryable"])

    def test_results_page_not_opened(self):
        # issue aa213ed6f361, 41fd983ff936: GUI не перешёл на страницу результатов
        self.fake.cats = [_cat("Судебная практика", 5)]
        self.fake.titles = [(1, "Док один")]
        self.fake.pos = (1, 5)
        self.fake.do_search = lambda q: setattr(self.fake, "page_state", "Стартовая страница") or False
        s, j = self.post("/search", {"query": "постановление пленума", "fresh": True})
        self.assertFalse(j["ok"])
        self.assertEqual(j["error"], "results_page_not_opened")
        self.assertTrue(j["retryable"])
        self.assertEqual(A.state["session"]["docs"], [])

    def test_retry_recovers_when_list_renders_second_time(self):
        # retryable=true не должен быть пустым словом: вторая попытка реально
        # перечитывает список и выдача становится успешной
        self.fake.cats = [_cat("Судебная практика", 12)]
        self.fake.titles = [(1, "Обзор практики N 1"), (2, "Обзор практики N 2")]
        self.fake.pos = (1, 12)
        self.fake.fail_first_enumeration = True
        s, j = self.post("/search", {"query": "обзор практики", "page_size": 2,
                                    "fresh": True})
        self.assertTrue(j["ok"])
        self.assertEqual(j["enum_attempts"], 2)
        self.assertEqual(j["parsed_count"], 2)
        self.assertEqual(j["total"], 12)

    def test_total_only_from_reader_position(self):
        # issue 3c1c7cd864d7: total больше не берётся из sel_count и не наследится
        self.fake.cats = [_cat("Судебная практика", 6568)]
        self.fake.titles = [(1, "Документ реальный А"), (2, "Документ реальный Б")]
        self.fake.pos = (2, None)          # «Док.N/total» не читается
        s, j = self.post("/search", {"query": "ключевая ставка", "page_size": 2,
                                    "fresh": True})
        self.assertTrue(j["ok"])
        self.assertIsNone(j["total"])
        self.assertEqual(j["total_source"], "unavailable")
        self.assertEqual(j["section_count"], 6568)
        self.assertIsNone(j["pages"])

    def test_no_silent_section_substitution(self):
        # issue 2cc486c55387: «Региональное законодательство» не должен
        # молча превращаться в «Законодательство»
        self.fake.cats = [_cat("Законодательство", 100)]
        self.fake.titles = [(1, "Док один")]
        self.fake.pos = (1, 100)
        s, j = self.post("/search", {"query": "ключевая ставка",
                                     "category": "Региональное законодательство",
                                     "fresh": True})
        self.assertEqual(s, 400)
        self.assertEqual(j["error"], "unknown_category")

    def test_approximate_section_is_reported(self):
        self.fake.cats = [_cat("Решения высших судов", 40)]
        self.fake.titles = [(1, "Док один")]
        self.fake.pos = (1, 40)
        s, j = self.post("/search", {"query": "док", "category": "решения высших",
                                    "fresh": True})
        self.assertTrue(j["ok"])
        self.assertEqual(j["selection_rule"], "approximate")
        self.assertIn("выбран близкий", j["note"])

    def test_echo_titles_of_short_query(self):
        # issue 4ad19b1f37b8: эхо и на коротких запросах, в кавычках
        q = "порядок пользования жилым помещением"
        self.fake.cats = [_cat("Российское законодательство (Версия Проф)", 1459)]
        self.fake.titles = [(1, '"%s"' % q), (2, '"%s"' % q),
                            (3, "Жилищный кодекс Российской Федерации")]
        self.fake.pos = (3, 1459)
        s, j = self.post("/search", {"query": q, "page_size": 3, "fresh": True})
        titles = [d["title"] for d in j["docs"]]
        self.assertNotIn('"%s"' % q, titles)
        self.assertIn("Жилищный кодекс Российской Федерации", titles)

    def test_partial_list_is_marked_truncated(self):
        # список прочитан оборванно, но ОБЪЁМ читалки совпадает с разделом —
        # это именно «прочитано частично», а не «листим не тот список»
        self.fake.cats = [_cat("Российское законодательство (Версия Проф)", 38)]
        self.fake.titles = [(1, "Обзор: практика ВС РФ N 1 (2026)")]
        self.fake.pos = (1, 38)
        s, j = self.post("/search", {"query": "обзор практики", "page_size": 3,
                                     "fresh": True})
        self.assertTrue(j["ok"])
        self.assertTrue(j["truncated"])
        self.assertEqual(j["parsed_count"], 1)
        self.assertEqual(j["expected_count"], 3)
        self.assertIn("прочитан частично", j["note"])
        self.assertIsNone(j["scope_mismatch"])

    def test_rows_identical_is_not_success(self):
        # issue 5607db8a1c12: дублирование одной строки masquerade под успех
        self.fake.cats = [_cat("Судебная практика", 65)]
        self.fake.titles = [(1, "Обзор судебной практики N 3"),
                            (2, "Обзор судебной практики N 3")]
        self.fake.pos = (2, 65)
        s, j = self.post("/search", {"query": "обзор практики", "page_size": 2,
                                    "fresh": True})
        self.assertFalse(j["ok"])
        self.assertTrue(j["rows_identical"])
        self.assertEqual(j["empty_reason"], "list_not_rendered")


# ------------------------------------------------- сверка ОБЪЁМА списка
# (issues e7f7bb098cfd, e15c0d424393)
class TestListScopeMismatch(BaseCase):
    """Живой прогон 05.11.2026: /search отдал 5 заголовков блока «Последние
    открытые документы» как выдачу запроса, потому что двойной клик по (900,300)
    ничего не открыл, а перечисление поехало листать уже открытый СТАРЫЙ
    документ: читалка показывала «Док.5/31» при разделе в 1588 документов.
    Ложный успех для юридической цитаты хуже честного отказа — такое больше
    не должно уходить как ok=true."""

    def _stale_reader(self):
        self.fake.cats = [_cat("Российское законодательство (Версия Проф)", 1588)]
        self.fake.titles = [(1, "Обзор: ВС РФ обобщил позиции судов"),
                            (2, "Приказ ФНС от 01.02.2024 N 10-н")]
        self.fake.pos = (5, 31)      # объём ЧУЖОГО списка, а не раздела

    def test_search_refuses_foreign_list(self):
        self._stale_reader()
        s, j = self.post("/search", {"query": "ключевая ставка", "page_size": 2,
                                     "fresh": True})
        self.assertFalse(j["ok"])
        self.assertEqual(j["empty_reason"], "list_scope_mismatch")
        self.assertEqual(j["error"], "list_scope_mismatch")
        self.assertEqual(j["docs"], [])
        self.assertEqual(j["parsed_count"], 0)
        self.assertTrue(j["retryable"])
        self.assertIsNone(j["total"])
        self.assertEqual(j["section_count"], 1588)
        self.assertEqual(j["scope_mismatch"],
                         {"opened_list_total": 31, "section_count": 1588,
                          "section": "Российское законодательство (Версия Проф)"})
        self.assertIn("открытый список содержит 31", j["note"])
        self.assertIn("1588", j["note"])
        self.assertFalse(j["openable"])
        # и сессия не оставляется адресной: /doc по такой «выдаче» честно 400
        self.assertEqual(A.state["session"]["docs"], [])
        s2, j2 = self.post("/doc", {"index": 0})
        self.assertEqual(s2, 400)
        self.assertEqual(j2["error"], "no_openable_list")

    def test_scope_mismatch_beats_list_not_rendered(self):
        # сам GUI отказался отдавать чужие заголовки ([]), но причину надо
        # назвать точную: не «строки не отрендерились», а «листим не тот список»
        self._stale_reader()
        self.fake.honor_expect_total = True
        s, j = self.post("/search", {"query": "ключевая ставка", "page_size": 2,
                                     "fresh": True})
        self.assertEqual(j["empty_reason"], "list_scope_mismatch")
        self.assertNotIn("не отрендерились", j["note"])
        self.assertEqual(j["enum_attempts"], 2)     # вторая попытка была

    def test_expect_total_is_passed_to_gui(self):
        # без этого аргумента проверка объёма осталась бы только на нашей стороне
        self._stale_reader()
        self.post("/search", {"query": "ключевая ставка", "page_size": 2,
                              "fresh": True})
        self.assertEqual(self.fake.enum_args[0]["expect_total"], 1588)
        self.assertTrue(self.fake.enum_args[0]["query_flat"])   # запрос тоже ушёл

    def test_matching_volume_is_success(self):
        self.fake.cats = [_cat("Российское законодательство (Версия Проф)", 1588)]
        self.fake.titles = [(1, "Документ первый"), (2, "Документ второй")]
        self.fake.pos = (2, 1588)      # ровно объём выбранного раздела
        s, j = self.post("/search", {"query": "ключевая ставка", "page_size": 2,
                                     "fresh": True})
        self.assertTrue(j["ok"])
        self.assertIsNone(j["scope_mismatch"])
        self.assertEqual(j["total"], 1588)

    def test_approximate_section_count_allows_bigger_reader_total(self):
        # «≥1588» — точного числа нет, поэтому требуем только total >= section
        self.fake.cats = [{"name": "Российское законодательство (Версия Проф)",
                           "count": 1588, "raw_count": "\u22651588", "leaf": True}]
        self.fake.titles = [(1, "Документ первый")]
        self.fake.pos = (1, 2000)
        s, j = self.post("/search", {"query": "ключевая ставка", "fresh": True})
        self.assertTrue(j["ok"])
        self.assertIsNone(j["scope_mismatch"])
        self.assertIsNone(self.fake.enum_args[0]["expect_total"])  # сверку делает app

    def test_approximate_section_still_refuses_smaller_list(self):
        self.fake.cats = [{"name": "Российское законодательство (Версия Проф)",
                           "count": 1588, "raw_count": "\u22651588", "leaf": True}]
        self.fake.titles = [(1, "Документ первый")]
        self.fake.pos = (5, 31)        # меньше раздела — это точно чужой список
        s, j = self.post("/search", {"query": "ключевая ставка", "fresh": True})
        self.assertFalse(j["ok"])
        self.assertEqual(j["empty_reason"], "list_scope_mismatch")
        self.assertEqual(j["scope_mismatch"]["opened_list_total"], 31)

    def test_total_unreadable_is_not_scope_mismatch(self):
        # «Док.N/total» не прочитался → объём сверить нечем, прежняя причина
        self.fake.cats = [_cat("Российское законодательство (Версия Проф)", 1588)]
        self.fake.titles = [(1, "Документ первый")]
        self.fake.pos = (1, None)
        s, j = self.post("/search", {"query": "ключевая ставка", "fresh": True})
        self.assertTrue(j["ok"])
        self.assertIsNone(j["scope_mismatch"])
        self.assertIsNone(j["total"])

    def test_page_refuses_foreign_list(self):
        # успешная выдача, а потом /page ушёл в чужой список — строки не отдаём,
        # сессию не троем
        self.fake.cats = [_cat("Судебная практика", 12)]
        self.fake.titles = [(1, "Док один"), (2, "Док два")]
        self.fake.pos = (2, 12)
        s, j = self.post("/search", {"query": "док", "page_size": 2, "fresh": True})
        self.assertTrue(j["ok"])
        self.assertEqual(A.state["session"]["section_count"], 12)
        self.fake.pos = (5, 31)
        s2, j2 = self.post("/page", {"page": 2})
        self.assertFalse(j2["ok"])
        self.assertEqual(j2["error"], "list_scope_mismatch")
        self.assertEqual(j2["docs"], [])
        self.assertEqual(j2["scope_mismatch"]["opened_list_total"], 31)
        self.assertEqual(j2["scope_mismatch"]["section_count"], 12)
        self.assertIn("не выдача запроса", j2["note"])
        self.assertEqual(len(A.state["session"]["docs"]), 2)   # прежняя выдача цела

    def test_open_refuses_foreign_list(self):
        # /open берёт строки только из списка этого запроса: candidates и
        # «найденный документ» не должны приезжать из старой вкладки
        self.fake.cats = [_cat("Российское законодательство (Версия Проф)", 1588)]
        self.fake.titles = [(1, "Обзор: ВС РФ обобщил позиции судов")]
        self.fake.pos = (1, 31)
        self.fake.honor_expect_total = True
        s, j = self.post("/open", {"title": "Обзор: ВС РФ обобщил позиции судов"})
        self.assertEqual(s, 404)
        self.assertEqual(j["error"], "doc_not_found")
        self.assertEqual(j["candidates"], [])
        self.assertNotIn("content", j)

    def test_manifest_declares_new_reason(self):
        # контракт: новый empty_reason обязан быть перечислен в манифесте,
        # иначе клиент не знает, как его трактовать
        s, j = self.get("/")
        self.assertIn("list_scope_mismatch", j["notes"]["empty_reason"])
        self.assertIn("list_scope_mismatch", j["notes"]["empty_reason_semantics"])


# ------------------------------------------------- точность /open
class TestOpenExactness(BaseCase):
    def test_open_bogus_title_404(self):
        # issue 7ff67e4db6f7: вместо чужого фрагмента УК РФ — честный 404
        self.fake.cats = [_cat("Нормативные акты", 3)]
        self.fake.titles = [(1, "Уголовный кодекс Российской Федерации"),
                            (2, "Иной документ")]
        self.fake.pos = (2, 3)
        s, j = self.post("/open", {"title": "щщщ заведомо отсутствующий документ "
                                              "проверки open 2026 зюкзюк"})
        self.assertEqual(s, 404)
        self.assertEqual(j["error"], "doc_not_found")
        self.assertFalse(j["exact_match"])
        self.assertGreater(len(j["candidates"]), 0)
        self.assertNotIn("content", j)      # чужое тело не отдаётся вообще

    def test_open_unrelated_title_404(self):
        # issue d0f56f25fda9: псевдострока-эхо не открывает постороннюю книгу
        self.fake.cats = [_cat("Комментарии законодательства", 8)]
        self.fake.titles = [(1, "Упрощенные производства в гражданском судопроизводстве")]
        self.fake.pos = (1, 8)
        s, j = self.post("/open", {"title": "регрессное взыскание коммунальных платежей "
                                              "с сособственника пропорционально доле"})
        self.assertEqual(s, 404)
        self.assertEqual(j["error"], "doc_not_found")

    def test_open_sets_session_unopenable(self):
        # /open уходит с выдачи → /doc обязан отказать, а не читать чужой список
        self.fake.cats = [_cat("Нормативные акты", 3)]
        self.fake.titles = [(1, "ГК РФ часть первая")]
        self.fake.pos = (1, 3)
        self.fake.export = ("ГК РФ часть первая", "текст кодекса " * 20, [])
        self.post("/search", {"query": "гк рф", "fresh": True})
        self.assertTrue(A.state["session"]["openable"])
        s, j = self.post("/open", {"title": "ГК РФ часть первая"})
        self.assertTrue(j["exact_match"])
        self.assertFalse(A.state["session"]["openable"])
        s2, j2 = self.post("/doc", {"index": 0})
        self.assertEqual(s2, 400)
        self.assertEqual(j2["error"], "list_not_active")


# ------------------------------------------------- /back и /state
class TestBackStack(BaseCase):
    def _search(self):
        self.fake.cats = [_cat("Судебная практика", 12)]
        self.fake.titles = [(1, "Док один"), (2, "Док два")]
        self.fake.pos = (2, 12)
        return self.post("/search", {"query": "сто пятьдесят пять жк", "page_size": 2,
                                    "fresh": True})

    def test_back_decrements_depth(self):
        # issue 2075ba12d5ca: 12 нажатий не должны раздувать стек
        s, j = self._search()
        self.assertTrue(j["ok"])
        st0, j0 = self.get("/state")
        d0 = j0["depth"]
        for _ in range(12):
            self.post("/back", {})
        st1, j1 = self.get("/state")
        self.assertLessEqual(j1["depth"], d0)
        self.assertEqual(j1["depth"], 0)

    def test_back_invalidates_session_and_state_current(self):
        self._search()
        s, j = self.post("/back", {})
        self.assertFalse(j["session_openable"])
        self.assertEqual(j["state"], "Стартовая страница")
        st, js = self.get("/state")
        self.assertIsNone(js["current"])       # current не залипает
        self.assertFalse(js["session_valid"])
        s2, j2 = self.post("/doc", {"index": 0})
        self.assertEqual(j2["error"], "list_not_active")

    def test_page_does_not_wipe_session(self):
        self._search()
        self.fake.titles = []                   # страница не отрендерилась
        s, j = self.post("/page", {"page": 2})
        self.assertFalse(j["ok"])
        self.assertEqual(j["error"], "list_not_rendered")
        self.assertEqual(len(A.state["session"]["docs"]), 2)   # прежняя выдача цела


# ------------------------------------------------- кодировка и даты среза
class TestEncodingAndFreshness(unittest.TestCase):
    def test_cp1251_read_as_latin1_is_repaired(self):
        # issue afeb1abcaef3
        bad = ("Äîêóìåíò ïðåäîñòàâëåí ÊîíñóëüòàíòÏëþñ. Âàæíåéøàÿ ïðàêòèêà "
               "ïî ñò. 190 Ãê ÐÔ")
        fixed, rep = rtf_util.fix_mojibake(bad)
        self.assertTrue(rep)
        self.assertIn("Документ предоставлен КонсультантПлюс", fixed)

    def test_normal_russian_untouched(self):
        good = ("Федеральный закон от 04.10.2014 N 280-ФЗ «Об исполнении "
                "федерального бюджета за 2013 год»")
        fixed, rep = rtf_util.fix_mojibake(good)
        self.assertFalse(rep)
        self.assertEqual(fixed, good)

    def test_extract_freshness_dates(self):
        text = ("«Гражданский кодекс Российской Федерации (часть первая) от "
                "30.11.1994 N 51-ФЗ (ред. от 10.06.2026)», «КоАП (ред. от "
                "26.06.2026) (с изм. и доп., вступ. в силу с 07.07.2026), «"
                "Суханов Е.А.» (Статут, 2026)")
        mx, ev = rtf_util.extract_freshness_dates(text)
        self.assertEqual(mx, "2026-06-26")
        self.assertIn("2026-06-10", ev)

    def test_future_effective_date_not_taken_as_cut(self):
        mx, _ev = rtf_util.extract_freshness_dates(
            "КоАП (ред. от 30.12.2030) — дата в будущем игнорируется")
        self.assertIsNone(mx)


class TestIndexAsOf(BaseCase):
    def test_unknown_when_nothing_known(self):
        old = config.INDEX_AS_OF
        config.INDEX_AS_OF = ""
        try:
            s, j = self.get("/health")
            self.assertEqual(j["index_as_of"], "unknown")
            self.assertEqual(j["index_as_of_source"], "not set")
            self.assertTrue(j["index_incomplete"])
        finally:
            config.INDEX_AS_OF = old

    def test_observed_dates_win_over_unknown(self):
        old = config.INDEX_AS_OF
        config.INDEX_AS_OF = ""
        try:
            A.state["index_observed"] = {"max": "2026-06-26",
                                          "evidence": [{"date": "2026-06-26",
                                                          "title": "КоАП"}]}
            s, j = self.get("/health")
            self.assertEqual(j["index_as_of"], "2026-06-26")
            self.assertIn("observed", j["index_as_of_source"])
            s2, j2 = self.post("/search", {"query": "док", "fresh": True})
            self.assertEqual(j2["index_as_of"], "2026-06-26")
        finally:
            config.INDEX_AS_OF = old

    def test_env_value_reported(self):
        old = config.INDEX_AS_OF
        config.INDEX_AS_OF = "2026-07-03"
        try:
            s, j = self.get("/health")
            self.assertEqual(j["index_as_of"], "2026-07-03")
            self.assertEqual(j["last_update"], "2026-07-03")
            self.assertFalse(j["index_incomplete"])
        finally:
            config.INDEX_AS_OF = old


# ------------------------------------------------- гигиена дерева GUI
class TestGuiCategories(unittest.TestCase):
    def test_read_categories_strips_search_suffix_and_dedupes(self):
        # issue 5f6bfa0e4a5b: «(Искать)» — элемент интерфейса, не имя раздела
        from server.consultant_gui import ConsultantGUI
        g = ConsultantGUI.__new__(ConsultantGUI)     # без подключения к окну
        g.tree_items = lambda: [
            (None, "Судебная практика 123"),
            (None, "Судебная практика (Искать)"),
            (None, "Арбитражные суды (Искать) 4"),
        ]
        cats = g.read_categories()
        names = [c["name"] for c in cats]
        self.assertEqual(names, ["Судебная практика", "Арбитражные суды"])
        self.assertEqual(cats[0]["count"], 123)
        self.assertFalse(any("(Искать)" in n for n in names))


class TestDocPosition(unittest.TestCase):
    """ статус-бар К+ содержит ДВА счётчика: «Док. N /M» (документ в списке)
    и «Абз. K /L» (абзац во всём результате). Прежний парсер брал последнее
    «/число» и возвращал число АБЗАЦЕВ вместо объёма списка — из-за этого
    сверка объёма была невозможна (issues e7f7bb098cfd, e15c0d424393)."""

    def _gui(self, names):
        """names — [(left, имя)] в порядке обхода окна."""
        edits = [_El(name=nm, rect=_Rect(l, 1049, l + 50, 1070))
                 for l, nm in names]
        return _bare_gui(_descendants=lambda control_type=None, **kw: edits)

    BAR = [(700, "Док.\xa03"), (752, "/1588"), (806, "Абз.\xa02668"), (885, "/10061")]

    def test_doc_pair_not_paragraph_total(self):
        g = self._gui(self.BAR)
        self.assertEqual(g._doc_position(), (3, 1588))

    def test_order_independent(self):
        # абзацная пара в обходе раньше документной — геометрия спасает
        g = self._gui([(806, "Абз.\xa02668"), (885, "/10061"),
                       (700, "Док.\xa03"), (752, "/1588")])
        self.assertEqual(g._doc_position(), (3, 1588))

    def test_without_paragraph_counter(self):
        g = self._gui([(700, "Док.\xa01"), (752, "/90")])
        self.assertEqual(g._doc_position(), (1, 90))

    def test_no_doc_counter(self):
        # счётчика «Док.» нет (не на списке) — прежний запасной путь
        g = self._gui([(806, "Абз.\xa02668"), (885, "/10061")])
        self.assertEqual(g._doc_position(), (None, 10061))

    def test_empty_status_bar(self):
        g = self._gui([(700, "Результаты поиска")])
        self.assertEqual(g._doc_position(), (None, None))

    def test_title_is_the_changing_edit_not_band_header(self):
        # заголовок документа (top=179) важнее полосы раздела (top=191)
        edits = [_El(name="Российское законодательство (Версия Проф",
                     rect=_Rect(300, 191, 792, 215)),
                 _El(name='"Основные направления единой денежно-кредитной политики"',
                     rect=_Rect(300, 179, 1378, 203))]
        g = _bare_gui(_descendants=lambda control_type=None, **kw: edits,
                      _w=lambda e: e.width(),
                      _state_suffix=lambda: "Поиск: ключевая ставка")
        self.assertIn("Основные направления", g._doc_title("ключевая ставка"))


class _Rect:
    """Как rectangle() у pywinauto: границы + width()/height()."""

    def __init__(self, left, top, right, bottom):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom

    def width(self):
        return self.right - self.left

    def height(self):
        return self.bottom - self.top


class _El:
    """Мини-обёртка элемента UIA (element_info + rectangle) — без окна."""

    def __init__(self, name="", aid="", cls="", rect=None):
        self.element_info = type("I", (), {"name": name, "automation_id": aid,
                                          "class_name": cls})()
        self._rect = rect or _Rect(0, 0, 0, 0)

    def rectangle(self):
        return self._rect

    def width(self):
        return self._rect.width()


def _bare_gui(**overrides):
    """ConsultantGUI без подключения к окну: подставляем только то, что зовём."""
    from server.consultant_gui import ConsultantGUI
    g = ConsultantGUI.__new__(ConsultantGUI)
    for k, v in overrides.items():
        setattr(g, k, v)
    return g


class TestGuiTitleEcho(unittest.TestCase):
    """_doc_title обязан отличать заголовок документа от ЭХА запроса
    (issue e7f7bb098cfd: на пустой читалке выдача была «запрос ×N»)."""

    Q = "обзор судебной практики верховный суд"

    def _gui(self, edits):
        return _bare_gui(_descendants=lambda control_type=None, **kw: edits,
                         _w=lambda e: e.width(),
                         _state_suffix=lambda: "Поиск: " + self.Q)

    def test_norm_title_ignores_quotes_nbsp_case(self):
        from server.consultant_gui import _norm_title
        self.assertEqual(_norm_title("\u00abОбзор\xa0судебной  практики\u00bb"),
                         "обзор судебной практики")
        self.assertEqual(_norm_title('"обзор судебной практики"'),
                         _norm_title("обзор судебной практики"))
        self.assertEqual(_norm_title(None), "")

    def test_search_field_by_aid_is_never_a_title(self):
        # широкие поля поиска (aid 1001/1063) — не заголовок, даже с текстом
        edits = [_El(name=self.Q, aid=config.AID_SEARCH_EDIT2,
                     rect=_Rect(300, 210, 1352, 240)),
                 _El(name="Обзор: ВС РФ обобщил позиции судов", aid="",
                     rect=_Rect(300, 260, 900, 290))]
        g = self._gui(edits)
        self.assertEqual(g._doc_title(self.Q), "Обзор: ВС РФ обобщил позиции судов")

    def test_echo_without_known_aid_is_skipped(self):
        # эхо может лежать в Edit с НЕИЗВЕСТНЫМ aid (колоночный чип) —
        # спасает только сравнение с нормализованным запросом
        edits = [_El(name='"%s"' % self.Q, aid="7777",
                     rect=_Rect(300, 210, 1352, 240))]
        g = self._gui(edits)
        self.assertEqual(g._doc_title(self.Q), "")     # fallback: состояние = «Поиск:» → пусто
        # без query_flat та же строка прошла бы как «заголовок» — вот и источник
        # «выдачи из одного и того же текста»
        self.assertEqual(g._doc_title(), '"%s"' % self.Q)

    def test_title_with_query_inside_is_kept(self):
        # регресс зонда main_titles: реальный заголовок, СОДЕРЖАЩИЙ слова
        # запроса, — не «эхо» и не должен теряться. Раньше из-за этого на
        # 2-м документе /search отдавал полосу раздела вместо заголовка
        # (при запросе «ставка» заголовок «...Ключевая ставка и процентная
        # ставка...» терялся как «эхо», и побеждала полоса на top=191).
        q = "ставка"
        title = 'Справочная информация: "Ключевая ставка и процентная ставка"'
        edits = [_El(name=title, aid="",
                     rect=_Rect(291, 179, 1363, 200)),
                 _El(name="Российское законодательство (Версия Проф)", aid="",
                     rect=_Rect(291, 191, 783, 212))]
        self.assertEqual(self._gui(edits)._doc_title(q), title)


class TestGuiOpenFirstDoc(unittest.TestCase):
    """Открытие строки списка (issues e15c0d424393, e7f7bb098cfd): клик
    ВСЕГДА проверяется — 'Док.N' обязан измениться, иначе успех вслепую
    невозможен. Первой пробуем доказанную живым прогоном точку первой строки,
    pane-точки — запасными для других раскладок."""

    PANE = _Rect(290, 268, 1872, 900)      # внутренняя область контента

    def _gui(self, pane=None, clicks=None, open_after=None, stale=None):
        """Читалка: stale — какой (cur,total) показывает ВСЕГДА (залипший
        список); open_after — сколько кликов нужно, чтобы список открылся."""
        if clicks is None:
            clicks = []
        state = {"backs": 0}

        def doc_position():
            if stale is not None:
                return stale
            if open_after is not None and len(clicks) >= open_after:
                return (1, 1588)
            return (None, None)

        def click(coords=None, double=False, **kw):
            clicks.append(coords)

        g = _bare_gui(ensure_window=lambda: None,
                      _doc_position=doc_position,
                      go_back=lambda: state.__setitem__("backs", state["backs"] + 1),
                      list_pane_rect=lambda: pane,
                      win=type("W", (), {"click_input":
                                         lambda self, **kw: click(**kw)})(),
                      _state_suffix=lambda: "Поиск: ключевая ставка")
        g.state = state
        return g

    def test_proven_point_is_tried_first(self):
        # доказанная первая строка (900,300) открывает список сразу — pane-
        # точки (которые на этой сборке промахивают и жгут ~время) не тратятся
        clicks = []
        g = self._gui(pane=self.PANE, clicks=clicks, open_after=1)
        with mock.patch("time.sleep"):
            self.assertTrue(g.open_first_doc())
        self.assertEqual(clicks, [(900, 300)])

    def test_falls_back_to_pane_points_when_proven_misses(self):
        # если (900,300) не открыл (другая раскладка/DPI) — пробуем pane-точки
        clicks = []
        g = self._gui(pane=self.PANE, clicks=clicks, open_after=2)
        with mock.patch("time.sleep"):
            self.assertTrue(g.open_first_doc())
        self.assertEqual(clicks[0], (900, 300))          # доказанная — первой
        self.assertEqual(len(clicks), 2)
        x, y = clicks[1]
        self.assertTrue(self.PANE.left <= x <= self.PANE.right)
        self.assertTrue(self.PANE.top <= y <= self.PANE.bottom)

    def test_returns_false_when_nothing_opens(self):
        # ни одна точка не открыла → честный False (а не «успех» вслепую)
        clicks = []
        g = self._gui(pane=self.PANE, clicks=clicks, stale=(5, 31))
        with mock.patch("time.sleep"):
            self.assertFalse(g.open_first_doc())
        self.assertEqual(clicks[0], (900, 300))          # первой была доказанная
        self.assertEqual(g.state["backs"], 2)            # из читалки вышли («Назад»)

    def test_no_pane_falls_back_to_old_point(self):
        clicks = []
        g = self._gui(pane=None, clicks=clicks, open_after=1)
        with mock.patch("time.sleep"):
            self.assertTrue(g.open_first_doc())
        self.assertEqual(clicks, [(900, 300)])

    def test_enumerate_returns_empty_when_open_failed(self):
        # ключевая гарантия: без подтверждённого открытия строки заголовки
        # НЕ собираются — иначе отдадим список старой вкладки за выдачу
        clicks = []
        g = self._gui(pane=self.PANE, clicks=clicks, open_after=None)
        g.goto_doc_index = lambda n: True
        g._doc_title = lambda qf=None: "КАКОЙ-ТО ЗАГОЛОВОК"
        g.next_doc = lambda: True
        with mock.patch("time.sleep"):
            out = g.enumerate_titles(1, 3, "ключевая ставка", expect_total=1588)
        self.assertEqual(out, [])

    def test_enumerate_drops_foreign_volume(self):
        # читалка листает список в 31 документ при разделе в 1588 → пусто
        g = self._gui(pane=self.PANE, clicks=[], stale=(1, 31))
        g.goto_doc_index = lambda n: True
        g._doc_title = lambda qf=None: "Обзор: ВС РФ"
        g.next_doc = lambda: True
        out = g.enumerate_titles(1, 3, "ключевая ставка", expect_total=1588)
        self.assertEqual(out, [])

    def test_enumerate_keeps_matching_volume(self):
        cur = {"n": 1}
        g = _bare_gui(ensure_window=lambda: None,
                      _doc_position=lambda: (cur["n"], 1588),
                      goto_doc_index=lambda n: True,
                      next_doc=lambda: (cur.__setitem__("n", cur["n"] + 1), True)[1],
                      _doc_title=lambda qf=None: "Документ",
                      _state_suffix=lambda: "Поиск: ключевая ставка")
        out = g.enumerate_titles(1, 3, "ключевая ставка", expect_total=1588)
        self.assertEqual([ab for ab, _t in out], [1, 2, 3])

    def test_list_pane_picks_inner_content_area(self):
        els = [_El(name="", cls="QWidget", rect=_Rect(0, 0, 1920, 1080)),   # top<230 → нет
               _El(name="", cls="MDIClient", rect=_Rect(0, 240, 1900, 1050)),
               _El(name="Рабочая область", cls="Afx:1", rect=_Rect(0, 240, 1900, 1050)),
               _El(name="", cls="Afx:2", rect=_Rect(290, 268, 1872, 900)),
               _El(name="", cls="Afx:3", rect=_Rect(290, 268, 1872, 339))]  # полоса-заголовок
        g = _bare_gui(_descendants=lambda control_type=None, **kw: els)
        r = g.list_pane_rect()
        self.assertEqual((r.left, r.top, r.right, r.bottom), (290, 268, 1872, 900))


if __name__ == "__main__":
    unittest.main(verbosity=2)
