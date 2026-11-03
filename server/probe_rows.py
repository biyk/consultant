# -*- coding: utf-8 -*-
"""Ищем, где лежат строки выдачи: статистика control_type по всему окну +
раскрытие нетиповых зон (List/DataGrid/Table/Text/Hyperlink)."""
import io
import os
import time
from collections import Counter

from pywinauto import Desktop

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "probe_rows.txt")
TYPES = ["List", "DataGrid", "Table", "ListItem", "Hyperlink", "Text", "Edit", "Custom"]


def trunc(s, n=100):
    s = (s or "").replace("\n", "\\n")
    return s[:n]


def brief(el):
    i = el.element_info
    try:
        r = i.rectangle
        rs = f"({r.left},{r.top},{r.right},{r.bottom})"
    except Exception:  # noqa: BLE001
        rs = "?"
    return f"[{i.control_type}] aid={i.automation_id!r} cls={trunc(i.class_name,30)!r} name={trunc(i.name)!r} {rs}"


def main():
    lines = []
    dl = Desktop(backend="uia")
    win = dl.window(class_name="ConsultantPlusMainWnd")
    try:
        win.restore()
    except Exception:  # noqa: BLE001
        pass
    win.set_focus()
    time.sleep(0.5)

    allc = win.descendants()
    ctr = Counter(c.element_info.control_type for c in allc)
    lines.append("### control_type histogram (всё окно):")
    for k, v in ctr.most_common():
        lines.append(f"   {k!r}: {v}")

    for t in TYPES:
        els = [c for c in allc if c.element_info.control_type == t]
        lines.append(f"\n### {t}: {len(els)}")
        for e in els[:60]:
            lines.append("   " + brief(e))

    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"written {OUT}, {len(lines)} lines, total descendants={len(allc)}")


if __name__ == "__main__":
    main()
