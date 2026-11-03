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

    # подключение/окно
    def connect(self, timeout=30):
        return [1]

    def ensure_window(self):
        pass

    def close_extra_tabs(self, keep=1):
        return 0

    def reset_for_search(self):
        pass

    def get_state(self):
        return {"tabs": []}

    def _state_suffix(self):
        return "Поиск: тест"

    def title(self):
        return "КонсультантПлюс [Поиск: тест]"

    def go_back(self):
        pass

    # поиск/дерево
    def do_search(self, query):
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
    def enumerate_titles(self, start_abs, count):
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
        A.state["session"].update(query=None, category=None, total=0, docs=[], categories=[])
        A.state["known_categories"] = list(config.CANONICAL_CATEGORIES)
        A.state["ref_titles"] = {}
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
        self.fake.cats = []          # пусто → no_matches
        s, j = self.post("/search", {"query": "qqzzxx", "fresh": True})
        self.assertEqual(s, 200)
        self.assertEqual(j["total"], 0)
        self.assertEqual(j["empty_reason"], "no_matches")

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


# ---------------------------------------------------------------- /doc
class TestDoc(BaseCase):
    def _seed_session(self):
        A.state["session"].update(query="q", category="Судебная практика", total=10,
                                  page=1, page_size=5,
                                  docs=[{"index": 0, "abs": 1, "title": "Док раз"}])

    def test_index_out_of_range_400(self):
        A.state["session"]["docs"] = []
        s, j = self.post("/doc", {"page": 1, "index": 0})
        self.assertEqual(s, 400)
        self.assertEqual(j["error"], "index_out_of_range")

    def test_stale_cleared_after_failed_search(self):
        # issue f501: /search с битой category → 400, и docs очищаются → /doc 400
        self.fake.cats = [_cat("Судебная практика", 5)]
        self.fake.titles = [(1, "Док")]
        self.fake.pos = (1, 5)
        self.post("/search", {"query": "q", "fresh": True})       # успех, docs есть
        self.post("/search", {"query": "q2", "category": "НЕТ", "fresh": True})  # 400
        s, j = self.post("/doc", {"page": 1, "index": 0})
        self.assertEqual(s, 400)          # не отдал stale-содержимое
        self.assertEqual(j["error"], "index_out_of_range")

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
    def test_sub_not_masked_empty(self):
        # issue 464d: раньше ok=true content=0; теперь честный unavailable
        A.state["session"].update(query="q", docs=[{"index": 0, "abs": 1, "title": "Д"}])
        self.fake.export = ("", "", [])
        s, j = self.post("/sub", {"index": 0})
        self.assertEqual(s, 200)
        self.assertFalse(j["ok"])
        self.assertTrue(j["retryable"])

    def test_sub_collection_entries_href(self):
        A.state["session"].update(query="q", docs=[{"index": 0, "abs": 1, "title": "Д"}])
        links = [{"ref": "R%d" % i, "title": "П%d" % i, "label": "П%d" % i,
                  "href": "consultantplus://offline/ref=R%d" % i} for i in range(7)]
        self.fake.export = ("Д", "пункт подборки " * 20, links)
        s, j = self.post("/sub", {"index": 0})
        self.assertEqual(j["kind"], "collection")
        self.assertTrue(all("href" in e for e in j["entries"]))


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
