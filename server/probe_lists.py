# -*- coding: utf-8 -*-
"""Глубокий дамп двух зон: дерево разделов (Tree aid=1016) и список документов
(Pane cls содержит '0001002B'). Показывает, как именно читаются категории и docs[].

Запуск:  D:\\ConsPlus\\venv\\Scripts\\python.exe server\\probe_lists.py
Вывод:   server/probe_lists.txt (UTF-8).
"""
import io
import os
import time

from pywinauto import Desktop

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "probe_lists.txt")


def trunc(s, n=90):
    s = (s or "").replace("\n", "\\n")
    return s[:n]


def walk(el, depth, lines, max_depth, max_children):
    info = el.element_info
    try:
        rect = info.rectangle
        rs = f"({rect.left},{rect.top},{rect.right},{rect.bottom})"
    except Exception:  # noqa: BLE001
        rs = "?"
    lines.append(
        "  " * depth + f"[{info.control_type}] aid={info.automation_id!r} "
        f"cls={trunc(info.class_name, 40)!r} name={trunc(info.name)!r} rect={rs}"
    )
    if depth >= max_depth:
        return
    try:
        ch = el.children()
    except Exception as e:  # noqa: BLE001
        lines.append("  " * (depth + 1) + f"!! {e}")
        return
    for x in ch[:max_children]:
        walk(x, depth + 1, lines, max_depth, max_children)
    if len(ch) > max_children:
        lines.append("  " * (depth + 1) + f"... +{len(ch) - max_children}")


def main():
    lines = []
    dl = Desktop(backend="uia")
    win = dl.window(class_name="ConsultantPlusMainWnd")
    win.set_focus()
    try:
        win.restore()
    except Exception:  # noqa: BLE001
        pass
    time.sleep(0.5)

    # 1) дерево разделов
    trees = win.descendants(control_type="Tree")
    lines.append(f"### Tree-элементов: {len(trees)}")
    for t in trees:
        lines.append("\n===== TREE =====")
        walk(t, 0, lines, max_depth=6, max_children=80)

    # 2) панель со списком документов (класс содержит 0001002B)
    panes = [p for p in win.descendants(control_type="Pane")
             if "0001002B" in (p.element_info.class_name or "")]
    lines.append(f"\n### Pane-списков: {len(panes)}")
    for p in panes:
        lines.append("\n===== LIST PANE =====")
        walk(p, 0, lines, max_depth=4, max_children=40)

    # 3) все Edit с номером [x:y] — это строки выдачи «банк + кол-во»
    lines.append("\n### Candidate doc-row Edits (name содержит '[' )")
    for e in win.descendants(control_type="Edit"):
        n = e.element_info.name or ""
        if "[" in n and "]" in n:
            lines.append(f"   {trunc(n)!r}")

    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"written {OUT}, {len(lines)} lines")


if __name__ == "__main__":
    main()
