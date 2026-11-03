# -*- coding: utf-8 -*-
"""Тест Ctrl+W: фокус на открытом документе, Ctrl+W, ловим новый файл в C:\Temp.
probe_export.txt (UTF-8) + список новых файлов и первые строки содержимого."""
import glob
import io
import os
import time

from pywinauto import Desktop

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "probe_export.txt")
TMP = r"C:\Temp"


def snapshot():
    set_ = {}
    for p in glob.glob(os.path.join(TMP, "*")):
        try:
            set_[p] = os.path.getmtime(p)
        except OSError:
            pass
    return set_


def main():
    lines = []
    dl = Desktop(backend="uia")
    win = dl.window(class_name="ConsultantPlusMainWnd")
    win.set_focus()
    time.sleep(0.3)

    before = snapshot()
    lines.append(f">>> шлю Ctrl+W; всего файлов в C:\\Temp до: {len(before)}")

    # Ctrl+W — экспорт активного документа
    win.type_keys("^w", pause=0.2)
    time.sleep(2.0)
    for _ in range(10):
        after = snapshot()
        new = [p for p in after if p not in before or after[p] > before.get(p, 0)]
        if new:
            break
        time.sleep(1.0)

    lines.append(f">>> новых/изменённых: {len(new)}")
    for p in sorted(new, key=lambda x: after[x], reverse=True)[:20]:
        sz = os.path.getsize(p) if os.path.isfile(p) else 0
        lines.append(f"   {p}  ({sz} bytes)")
        if os.path.isfile(p) and sz < 4_000_000:
            head = read_head(p)
            lines.append("      HEAD:")
            for ln in head.splitlines()[:25]:
                lines.append("        " + ln[:160])

    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"written {OUT}, new={len(new)}")


def read_head(path):
    for enc in ("utf-8-sig", "utf-16", "cp1251"):
        try:
            with io.open(path, "r", encoding=enc) as f:
                return f.read(3000)
        except Exception:  # noqa: BLE001
            continue
    try:
        with io.open(path, "rb") as f:
            return f.read(1500).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return f"<binary or err: {e}>"


if __name__ == "__main__":
    main()
