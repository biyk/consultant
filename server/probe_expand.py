# -*- coding: utf-8 -*-
"""Интерактивная разведка списка выдачи:
 1) выбрать реальную категорию в дереве (двойной клик по TreeItem);
 2) проверить, появились ли дочерние элементы у LIST PANE (cls ...0001002);
 3) попробовать Ctrl+A/Ctrl+C в списке и прочитать clipboard.
Пишет всё в probe_expand.txt (UTF-8)."""
import io
import os
import time

import win32clipboard
from pywinauto import Desktop

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "probe_expand.txt")


def trunc(s, n=120):
    s = (s or "").replace("\n", "\\n")
    return s[:n]


def brief(el):
    i = el.element_info
    try:
        r = i.rectangle
        rs = f"({r.left},{r.top},{r.right},{r.bottom})"
    except Exception:  # noqa: BLE001
        rs = "?"
    return f"[{i.control_type}] aid={i.automation_id!r} cls={trunc(i.class_name,26)!r} name={trunc(i.name)!r} {rs}"


def get_clip():
    win32clipboard.OpenClipboard()
    try:
        data = win32clipboard.GetClipboardData()
    except Exception:  # noqa: BLE001
        data = ""
    finally:
        win32clipboard.CloseClipboard()
    return data if isinstance(data, str) else (data or b"").decode("utf-8", "replace")


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

    tree = win.child_window(control_type="Tree", auto_id="1016").wrapper_object()
    items = tree.children()
    lines.append(f"### TreeItem: {len(items)}")
    for it in items:
        lines.append("   " + brief(it))

    # выбираем вторую категорию (первая часто — заголовок раздела)
    target = items[1] if len(items) > 1 else items[0]
    lines.append(f"\n>>> double-click: {trunc(target.element_info.name)!r}")
    try:
        target.double_input()
    except Exception as e:  # noqa: BLE001
        lines.append(f"   double_input err: {e}")
        try:
            target.select()
            target.click_input()
        except Exception as e2:  # noqa: BLE001
            lines.append(f"   select err: {e2}")
    time.sleep(2.5)

    # пересобираем pane-списки
    panes = [p for p in win.descendants(control_type="Pane")
             if "0001002" in (p.element_info.class_name or "")]
    lines.append(f"\n### LIST PANE после выбора: {len(panes)}")
    for p in panes:
        kids = p.descendants()
        lines.append(f"   PANE {brief(p)} descendants={len(kids)}")
        for k in kids[:40]:
            lines.append("      " + brief(k))

    # пробуем Ctrl+C в области списка (крупнейший pane)
    if panes:
        big = max(panes, key=lambda p: (p.rectangle().right - p.rectangle().left))
        try:
            big.click_input()
            time.sleep(0.3)
            win.type_keys("^a", pause=0.05)
            win.type_keys("^c", pause=0.1)
            time.sleep(0.5)
            clip = get_clip()
            lines.append(f"\n### CLIPBOARD len={len(clip)}")
            lines.append(clip[:4000])
        except Exception as e:  # noqa: BLE001
            lines.append(f"clipboard err: {e}")

    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"written {OUT}, {len(lines)} lines")


if __name__ == "__main__":
    main()
