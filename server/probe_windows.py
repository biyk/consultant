# -*- coding: utf-8 -*-
"""Разведка GUI «КонсультантПлюс»: окно, дочерние контролы, чем читаются тексты.

Запуск:  python server/probe_windows.py
Вывод:  stdout (UTF-8) — список контролов класса ConsultantPlusMainWnd с попыткой
        прочитать текст через WM_GETTEXT. Никаких сторонних библиотек не требует.
"""
import ctypes as c
from ctypes import wintypes as wt
import json
import sys

user32 = c.windll.user32

EnumWindows = user32.EnumWindows
EnumChildWindows = user32.EnumChildWindows
GetClassNameW = user32.GetClassNameW
GetWindowTextW = user32.GetWindowTextW
GetWindowTextLengthW = user32.GetWindowTextLengthW
GetDlgCtrlID = user32.GetDlgCtrlID
IsWindowVisible = user32.IsWindowVisible
GetWindowRect = user32.GetWindowRect
SendMessageW = user32.SendMessageW

WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E

EnumWindowsProc = c.WINFUNCTYPE(c.c_bool, wt.HWND, wt.LPARAM)
EnumChildProc = c.WINFUNCTYPE(c.c_bool, wt.HWND, wt.LPARAM)


def get_text(hwnd, max_len=8192):
    buf = c.create_unicode_buffer(max_len)
    SendMessageW(hwnd, WM_GETTEXT, max_len - 1, buf)
    return buf.value


def get_text_len(hwnd):
    return SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0)


def describe(hwnd):
    cls = c.create_unicode_buffer(256)
    GetClassNameW(hwnd, cls, 256)
    title_len = GetWindowTextLengthW(hwnd)
    title = c.create_unicode_buffer(title_len + 1)
    GetWindowTextW(hwnd, title, title_len + 1)
    rect = wt.RECT()
    GetWindowRect(hwnd, c.byref(rect))
    return {
        "hwnd": hwnd,
        "class": cls.value,
        "id": GetDlgCtrlID(hwnd),
        "visible": bool(IsWindowVisible(hwnd)),
        "title": title.value,
        "rect": [rect.left, rect.top, rect.right, rect.bottom],
        "wmtext_len": get_text_len(hwnd),
        "wmtext_head": get_text(hwnd, 400)[:300],
    }


def find_main_windows(class_name="ConsultantPlusMainWnd"):
    found = []

    def cb(hwnd, _):
        cls = c.create_unicode_buffer(256)
        GetClassNameW(hwnd, cls, 256)
        if cls.value == class_name:
            found.append(hwnd)
        return True

    EnumWindows(EnumWindowsProc(cb), 0)
    return found


def list_children(hwnd):
    kids = []

    def cb(child, _):
        kids.append(child)
        return True

    EnumChildWindows(hwnd, EnumChildProc(cb), 0)
    return kids


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    wins = find_main_windows()
    if not wins:
        print("ConsultantPlusMainWnd НЕ найден — клиент не запущен или окно закрыто.")
        return 1
    for hwnd in wins:
        info = describe(hwnd)
        print(f"\n===== MainWindow hwnd={hex(hwnd)} title={info['title']!r} =====")
        rows = [describe(ch) for ch in list_children(hwnd)]
        for r in rows:
            flag = "V" if r["visible"] else "h"
            txt = ""
            if r["wmtext_len"] or r["wmtext_head"]:
                head = (r["wmtext_head"] or "").replace("\n", "\\n")[:80]
                txt = f" text[{r['wmtext_len']}]={head!r}"
            print(f"  {flag} {r['class']:<18} id={r['id']:<7} "
                  f"rect={r['rect']} title={r['title'][:40]!r}{txt}")
        # сводка: класс -> сколько контролов и сколько с читаемым текстом
        summary = {}
        for r in rows:
            s = summary.setdefault(r["class"], [0, 0])
            s[0] += 1
            if r["wmtext_len"] > 0:
                s[1] += 1
        print("\n----- сводка class: controls / readable-via-WM_GETTEXT -----")
        print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
