# -*- coding: utf-8 -*-
"""UIA-разведка окна «КонсультантПлюс»: что отдаёт backend=uia.

Запуск:  D:\\ConsPlus\\venv\\Scripts\\python.exe server\\probe_uia.py
Вывод:   server/probe_uia.txt (UTF-8) — дерево элементов с control_type/name/automation_id.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pywinauto import Desktop  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe_uia.txt")


def dump_elem(el, depth, lines):
    try:
        info = element_info_of(el)
        rect = info.rectangle
        lines.append(
            "  " * depth
            + f"[{info.control_type}] aid={info.automation_id!r} "
            + f"cls={info.class_name!r} name={trunc(info.name)!r} "
            + f"rect=({rect.left},{rect.top},{rect.right},{rect.bottom})"
        )
    except Exception as e:  # noqa: BLE001
        lines.append("  " * depth + f"!! error: {e}")


def element_info_of(el):
    return el.element_info


def trunc(s, n=60):
    s = (s or "").replace("\n", "\\n")
    return s[:n]


def walk(el, depth, lines, max_depth=6, max_children=60):
    dump_elem(el, depth, lines)
    if depth >= max_depth:
        return
    try:
        children = el.children()
    except Exception as e:  # noqa: BLE001
        lines.append("  " * (depth + 1) + f"!! children error: {e}")
        return
    for ch in children[:max_children]:
        walk(ch, depth + 1, lines, max_depth, max_children)
    if len(children) > max_children:
        lines.append("  " * (depth + 1) + f"... {len(children) - max_children} more children")


def main():
    lines = []
    dl = Desktop(backend="uia")
    wins = dl.windows(class_name="ConsultantPlusMainWnd")
    if not wins:
        lines.append("ConsultantPlusMainWnd не найден (uia).")
    for w in wins:
        lines.append(f"\n===== WINDOW title={trunc(w.window_text(), 80)!r} =====")
        walk(w, 0, lines, max_depth=4, max_children=40)

    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"written {OUT}, {len(lines)} lines")


if __name__ == "__main__":
    main()
