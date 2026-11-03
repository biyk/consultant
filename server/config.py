# -*- coding: utf-8 -*-
"""Конфигурация сервера «КонсультантПлюс»: пути, id контролов, таймауты.

Все значения — абсолютные, завязаны на проект D:\\ConsPlus. Зависимости только из
локального venv. Значения контролов подтверждены разведкой (см. server/probe_*.py).
"""
import os

# --- Пути проекта -----------------------------------------------------------
PROJECT_DIR = r"D:\ConsPlus"
SERVER_DIR = os.path.join(PROJECT_DIR, "server")
DATA_DIR = os.path.join(PROJECT_DIR, "data")
SEARCH_CACHE = os.path.join(DATA_DIR, "search")
DOCS_CACHE = os.path.join(DATA_DIR, "docs")
RTF_INBOX = os.path.join(DATA_DIR, "rtf_inbox")
ISSUES_DIR = os.path.join(DATA_DIR, "issues")
LOGS_DIR = os.path.join(PROJECT_DIR, "logs")

for _d in (DATA_DIR, SEARCH_CACHE, DOCS_CACHE, RTF_INBOX, ISSUES_DIR, LOGS_DIR):
    os.makedirs(_d, exist_ok=True)

# --- Клиент КонсультантПлюс -------------------------------------------------
CONSULTANT_EXE = os.environ.get(
    "CONSULTANT_EXE",
    r"E:\Downloads\Cons_Shell_2026.8\Shell_PC_2026\ConsultantPlus (01.08.2026)\cons.exe",
)
MAIN_WIN_CLASS = "ConsultantPlusMainWnd"
# Куда К+ складывает RTF после Ctrl+W (падение с задержкой; *.tmp игнорировать)
RTF_EXPORT_DIR = os.environ.get("CONSULTANT_RTF_DIR", r"C:\Temp")

# --- automation_id контролов (подтверждены UIA-разведкой) ------------------
AID_SEARCH_EDIT = "1001"          # поле на Стартовой странице (class Edit)
AID_SEARCH_EDIT2 = "1063"         # поле на странице поиска (вложен в ComboBox)
AID_SEARCH_COMBO = "341"          # ComboBox страницы поиска
AID_BTN_FIND_START = "1"          # «Найти» на стартовой
AID_BTN_FIND = "271"              # «Найти» на странице поиска
AID_TREE = "1016"                 # дерево разделов/инфобанков
AID_TABBAR = "59397"              # панель вкладок
AID_MDICLIENT = "59648"           # рабочее пространство MDI
AID_MDI_VIEW = "59648"            # внутренняя панель области просмотра
BTN_ALL_RESULTS = "Все\xa0результаты\xa0поиска"   # кнопка полного списка выдачи
BTN_FIND_LABEL = "Найти"
BTN_PREV_DOC = "Предыдущий документ"
BTN_NEXT_DOC = "Следующий документ"
BTN_BACK = "Назад"
BTN_FORWARD = "Вперед"
BTN_EXPORT = "Экспорт в Word"     # Ctrl+W (совпадение по началу имени)

# --- Таймауты / лимиты ------------------------------------------------------
GUI_LOCK_TIMEOUT = int(os.environ.get("CONSULTANT_GUI_TIMEOUT", "120"))  # сек
WAIT_RESULTS_TIMEOUT = float(os.environ.get("CONSULTANT_WAIT_RESULTS", "60"))
WAIT_RTF_TIMEOUT = float(os.environ.get("CONSULTANT_WAIT_RTF", "30"))
WAIT_TREE_TIMEOUT = float(os.environ.get("CONSULTANT_WAIT_TREE", "20"))
WAIT_DOC_RENDER = float(os.environ.get("CONSULTANT_WAIT_DOC", "20"))
POLL = 0.4                        # шаг опроса состояний окна, сек
DEFAULT_PAGE_SIZE = int(os.environ.get("CONSULTANT_PAGE_SIZE", "20"))
MAX_PAGE_SIZE = 100
NAV_STEP_TIMEOUT = 60.0           # лимит на листание к N-му документу

# --- HTTP -------------------------------------------------------------------
HOST = os.environ.get("CONSULTANT_HOST", "0.0.0.0")
PORT = int(os.environ.get("CONSULTANT_PORT", "8000"))

# Прочие поведенческие константы
SCOPE_SINGLE_SECTION = "single_section"
# Минимальная длина текста, чтобы считать экспорт документа удался (иначе unavailable)
DOC_MIN_CONTENT = int(os.environ.get("CONSULTANT_DOC_MIN_CONTENT", "40"))
# Дата среза индекса (best-effort; юрист-клиент distinguishes «нет в базе» vs «не обновлено»).
# Задаётся снаружи: env CONSULTANT_INDEX_AS_OF=ГГГГ-ММ-ДД (или пусто → «unknown»).
INDEX_AS_OF = os.environ.get("CONSULTANT_INDEX_AS_OF", "").strip()
# Канонический список разделов верхнего уровня (для манифеста и фолбэка hints,
# когда свежее чтение дерева не далo имён).
CANONICAL_CATEGORIES = [
    "Российское законодательство (Версия Проф)",
    "Нормативные акты", "Судебная практика", "Формы документов",
    "Комментарии законодательства", "Справочная информация",
    "Проекты документов", "Кадры и обучение", "Финансовые консультации",
    "Региональное законодательство", "Итоги и анализ", "Новое в российском законодательстве",
]
