# -*- coding: utf-8 -*-
"""Диагностика/уборка клиента К+: перечислить видимые окна процесса cons.exe и
(с --close) закрыть залипшие попапы/модалки, не трогая главное окно.

Только для THIS-машины cleanup после зонда. Запуск:
    venv\\Scripts\\python.exe scripts\\client_windows.py
    venv\\Scripts\\python.exe scripts\\client_windows.py --close
"""
import sys
import time
import ctypes

try:
    ctypes.windll.kernel32.SetPriorityClass(
        ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000)
except Exception:  # noqa: BLE001
    pass

import win32gui
import win32process
import win32con
import win32api

MAIN_CLS = "ConsultantPlusMainWnd"


def find_main():
    out = []

    def cb(h, _):
        if win32gui.GetClassName(h) == MAIN_CLS:
            out.append(h)
        return True
    win32gui.EnumWindows(cb, None)
    return out[0] if out else None


def main_windows_of(pid):
    rows = []

    def cb(h, _):
        if win32process.GetWindowThreadProcessId(h)[1] == pid \
                and win32gui.IsWindowVisible(h):
            rows.append((h, win32gui.GetClassName(h), win32gui.GetWindowText(h),
                         win32gui.GetWindowLong(h, win32con.GWL_STYLE)))
        return True
    win32gui.EnumWindows(cb, None)
    return rows


def main():
    do_close = "--close" in sys.argv
    mh = find_main()
    if not mh:
        print("главное окно К+ (%s) НЕ найдено" % MAIN_CLS)
        return 2
    pid = win32process.GetWindowThreadProcessId(mh)[1]
    print("main hwnd=%s pid=%d title=%r" % (mh, pid, win32gui.GetWindowText(mh)))
    rows = main_windows_of(pid)
    print("видимых окон процесса: %d" % len(rows))
    for h, cls, t, style in rows:
        r = win32gui.GetWindowRect(h)
        w, hh = r[2] - r[0], r[3] - r[1]
        tag = "MAIN" if h == mh else "popup"
        print("  [%s] hwnd=%-10s cls=%-26r title=%-20r %dx%d style=0x%08X"
              % (tag, h, cls[:26], t[:20], w, hh, style))

    if not do_close:
        print("\n(диактив; --close чтобы закрыть попапы)")
        return 0

    def esc_key():
        win32api.keybd_event(0x1B, 0, 0, 0)                # VK_ESCAPE down
        win32api.keybd_event(0x1B, 0, win32con.KEYEVENTF_KEYUP, 0)

    def dump_children(h):
        kids = []

        def cbk(c, _):
            kids.append((c, win32gui.GetClassName(c), win32gui.GetWindowText(c)))
            return True
        try:
            win32gui.EnumChildWindows(h, cbk, None)
        except Exception as exc:  # noqa: BLE001
            print("    EnumChildWindows: %r" % exc)
        for c, cls, t in kids:
            print("    child hwnd=%-9s cls=%-16r %r" % (c, cls[:16], t[:34]))
        return kids

    def force_foreground(h):
        mine = win32api.GetCurrentThreadId()
        tgt = win32process.GetWindowThreadProcessId(h)[0]
        attached = False
        try:
            if mine != tgt:
                win32process.AttachThreadInput(mine, tgt, True)
                attached = True
        except Exception:  # noqa: BLE001
            pass
        for op in (
            lambda: win32gui.BringWindowToTop(h),
            lambda: win32gui.SetForegroundWindow(h),
            lambda: win32gui.SetActiveWindow(h),
            lambda: win32gui.SetWindowPos(h, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                                          win32con.SWP_NOMOVE | win32con.SWP_NOSIZE),
            lambda: win32gui.SetWindowPos(h, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                                          win32con.SWP_NOMOVE | win32con.SWP_NOSIZE),
        ):
            try:
                op()
            except Exception:  # noqa: BLE001
                pass
        if attached:
            try:
                win32process.AttachThreadInput(mine, tgt, False)
            except Exception:  # noqa: BLE001
                pass

    def click_at(cx, cy):
        win32api.SetCursorPos((cx, cy))
        time.sleep(0.1)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, cx, cy, 0, 0)
        time.sleep(0.05)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, cx, cy, 0, 0)

    def hard_close(h, cls):
        kids = dump_children(h)
        force_foreground(h)
        time.sleep(0.2)
        esc_key()                        # реальный Esc в фокус
        time.sleep(0.6)
        if win32gui.IsWindow(h) and win32gui.IsWindowVisible(h):
            # кликнуть по кнопке «Отмена/ОК/Закрыть» реальным курсором
            for c, ccls, ct in kids:
                if ccls == "Button" and any(
                        x in (ct or "") for x in ("Отмена", "Закрыть", "Cancel")):
                    r = win32gui.GetWindowRect(c)
                    click_at((r[0] + r[2]) // 2, (r[1] + r[3]) // 2)
                    print("    реальный клик по %r" % ct[:20])
                    time.sleep(0.6)
                    break
        if win32gui.IsWindow(h) and win32gui.IsWindowVisible(h):
            try:
                win32gui.SendMessageTimeout(h, win32con.WM_CLOSE, 0, 0,
                                            win32con.SMTO_ABORTIFHUNG | 0x0002,
                                            2000)
            except Exception:  # noqa: BLE001
                pass

    closed = 0
    for h, cls, t, style in rows:
        if h == mh:
            continue
        print("\n  попап hwnd=%s cls=%r title=%r" % (h, cls[:12], t[:30]))
        hard_close(h, cls)
        closed += 1
    time.sleep(0.6)
    after2 = main_windows_of(pid)
    print("\nпосле close видимых окон: %d (из них попапов: %d)" %
          (len(after2), len([x for x in after2 if x[0] != mh])))
    for h, cls, t, style in after2:
        if h != mh:
            print("  ЗАЛИПЛО: hwnd=%s cls=%r title=%r" % (h, cls[:20], t[:30]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
