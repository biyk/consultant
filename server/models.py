# -*- coding: utf-8 -*-
"""Простые схемы ответов (dict-совместимые). Без внешних зависимостей."""
from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class Category:
    name: str
    count: Optional[int] = None      # парсовое число документов (None если ≥/не число)
    raw_count: str = ""              # исходная строка счётчика ("215129", "≥528651")
    leaf: bool = True                # False у заголовков разделов (без числа)

    def to_dict(self):
        return asdict(self)


@dataclass
class DocRef:
    index: int                       # абсолютный индекс в выдаче (0-based)
    title: str
    kind: str = "unknown"            # unknown|document|collection|unavailable
    page: int = 1                    # страница выдачи, к которой относится

    def to_dict(self):
        return asdict(self)


@dataclass
class SearchResponse:
    query: str
    total: int = 0
    pages: int = 0
    page: int = 1
    page_size: int = 20
    docs: List[dict] = field(default_factory=list)
    categories: List[dict] = field(default_factory=list)
    selected_category: Optional[str] = None
    requested_category: Optional[str] = None
    scope: str = "single_section"
    truncated: bool = False
    parsed_count: int = 0
    expected_count: int = 0
    filter_applied: bool = False
    empty_reason: Optional[str] = None   # None|no_matches|list_not_rendered
    note: Optional[str] = None
    cached: bool = False

    def to_dict(self):
        return asdict(self)


@dataclass
class DocResponse:
    kind: str = "document"           # document|collection|unavailable
    title: str = ""
    content: Optional[str] = None
    entries: List[dict] = field(default_factory=list)
    links: List[dict] = field(default_factory=list)
    message: Optional[str] = None
    cached: bool = False

    def to_dict(self):
        return asdict(self)
