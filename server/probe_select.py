# -*- coding: utf-8 -*-
"""Корректно выбираем категорию (click_input по центру + Enter), ждём загрузку
списка и переснимаем окно: histogram control_type + все name, которые появились.
probe_select.txt (UTF-8)."""
import io
import os
import time
from collections import Counter

from pywinauto import Desktop

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "probe_select.txt")


def trunc(s, n=120):
    return (s or "").replace("\n", "\\n")[:n]


def main():
    lines = []
    dl = Desktop(backend="uia")
    win = dl.window(class_name="ConsultantPlusMainWnd")
    try:
        win.restore()
    except Exception:  # noqa: BLE001
        pass
    win.set_focus()
    time.sleep(0.4)

    before = {}
    for e in win.descendants():
        i = e.element_info
        before[(i.control_type, i.name, i.automation_id)] = 1

    tree = win.child_window(control_type="Tree", auto_id="1016").wrapper_object()
    items = tree.children()
    target = items[1] if len(items) > 1 else items[0]
    lines.append(f">>> click_input category: {trunc(target.element_info.name)!r}")
    target.click_input()
    time.sleep(0.6)
    win.type_keys("{ENTER}", pause=0.1)
    time.sleep(3.0)

    after = win.descendants()
    ctr = Counter(e.element_info.control_type for e in after)
    lines.append("\n### control_type histogram ПОСЛЕ выбора:")
    for k, v in ctr.most_common():
        lines.append(f"   {k!r}: {v}")

    # новые name
    lines.append("\n### НОВЫЕ элементы (не были до выбора):")
    n = 0
    for e in after:
        i = e.element_info
        key = (i.control_type, i.name, i.automation_id)
        if key not in before and i.name:
            try:
                r = i.rectangle
                rs = f"({r.left},{r.top},{r.right},{r.bottom})"
            except Exception:  # noqa: BLE001
                rs = "?"
            lines.append(f"   [{i.control_type}] aid={i.automation_id!r} "
                         f"cls={trunc(i.class_name,24)!r} name={trunc(i.name)!r} {rs}")
            n += 1
            if n > 120:
                break
    lines.append(f"\n(новых: {n})")

    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"written {OUT}, new={n}")


if __name__ == "__main__":
    main()
