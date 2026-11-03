# -*- coding: utf-8 -*-
"""Полный снимок всех непустых name в активном MDI-окне результатов + разбор
структуры списка (родитель pane -> дети). probe_dump.txt (UTF-8)."""
import io
import os

from pywinauto import Desktop

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "probe_dump.txt")


def trunc(s, n=140):
    return (s or "").replace("\n", "\\n")[:n]


def main():
    lines = []
    dl = Desktop(backend="uia")
    win = dl.window(class_name="ConsultantPlusMainWnd")
    lines.append(f"### TITLE: {trunc(win.window_text())!r}")

    # активный MDI child = Window внутри MDIClient с наибольшим числом детей
    mdi = win.child_window(control_type="Pane", auto_id="59648",
                           class_name="MDIClient").wrapper_object()
    kids = [c for c in mdi.children() if c.element_info.control_type == "Window"]
    for w in kids:
        lines.append(f"\n===== MDI CHILD {trunc(w.element_info.name)!r} "
                     f"aid={w.element_info.automation_id!r} =====")
        for e in w.descendants():
            i = e.element_info
            if i.name:
                try:
                    r = i.rectangle
                    rs = f"({r.left},{r.top},{r.right},{r.bottom})"
                except Exception:  # noqa: BLE001
                    rs = "?"
                lines.append(f"   [{i.control_type}] aid={i.automation_id!r} "
                             f"name={trunc(i.name)!r} {rs}")

    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"written {OUT}, {len(lines)} lines")


if __name__ == "__main__":
    main()
