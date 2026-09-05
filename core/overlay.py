# -*- coding: utf-8 -*-
"""
디버그 오버레이 (P1.8).

검출 결과를 화면 위에 직접 그린다. 이게 없으면 임계값 조정이 추측이다 —
"0.85 로 안 잡히니 0.80 으로 내려볼까" 를 로그 숫자만 보고 반복하게 된다.
오버레이가 있으면 무엇이 어디서 몇 점으로 잡히는지 눈으로 보고 정한다.

클릭이 통과하는 투명 창이라 게임 조작을 방해하지 않는다.
"""
import ctypes
import sys
import tkinter as tk

_IS_WIN = sys.platform == "win32"

# 투명색 — 이 색으로 칠한 픽셀은 화면이 비쳐 보인다.
# 검정을 쓰면 게임의 검은 부분과 섞이므로 잘 안 쓰는 색을 고른다.
_CHROMA = "#010203"

_BOX_OK = "#22DD55"      # 임계값 통과
_BOX_TRY = "#FFCC22"     # 시도 중
_BOX_BLOCK = "#FF4444"   # 제외됨


class DebugOverlay:
    """검출 박스를 그리는 클릭 통과 창."""

    def __init__(self, parent, engine, interval_ms=200):
        self.engine = engine
        self.interval = interval_ms
        self._win = None
        self._canvas = None
        self._after_id = None
        self._parent = parent

    def is_open(self) -> bool:
        return self._win is not None

    def toggle(self):
        self.close() if self.is_open() else self.open()

    # ------------------------------------------------------------------
    def open(self):
        if self._win is not None:
            return
        w = tk.Toplevel(self._parent)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        try:
            w.attributes("-transparentcolor", _CHROMA)
        except tk.TclError:
            # 투명색 미지원 환경 — 창 전체를 반투명으로 대신한다
            try:
                w.attributes("-alpha", 0.35)
            except tk.TclError:
                pass

        sw = w.winfo_screenwidth()
        sh = w.winfo_screenheight()
        w.geometry(f"{sw}x{sh}+0+0")

        self._canvas = tk.Canvas(w, width=sw, height=sh, bg=_CHROMA,
                                 highlightthickness=0)
        self._canvas.pack()
        self._win = w

        w.update_idletasks()
        self._make_click_through()
        self._tick()

    def _make_click_through(self):
        """마우스 입력이 오버레이를 통과해 게임으로 가게 한다.

        이걸 안 하면 오버레이가 화면 전체를 덮고 있어서 게임을 클릭할 수 없다.
        매크로가 보내는 클릭도 막힌다.
        """
        if not _IS_WIN or self._win is None:
            return
        try:
            hwnd = ctypes.windll.user32.GetParent(self._win.winfo_id())
            if not hwnd:
                hwnd = self._win.winfo_id()
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_TOOLWINDOW = 0x00000080     # Alt+Tab 목록에서 숨긴다
            cur = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE,
                cur | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW)
        except Exception:
            pass

    def close(self):
        if self._after_id is not None:
            try:
                self._parent.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if self._win is not None:
            try:
                self._win.destroy()
            except Exception:
                pass
            self._win = None
            self._canvas = None

    # ------------------------------------------------------------------
    def _tick(self):
        if self._win is None:
            return
        try:
            self._draw()
        except Exception:
            pass
        self._after_id = self._parent.after(self.interval, self._tick)

    def _draw(self):
        c = self._canvas
        if c is None:
            return
        c.delete("all")

        snap = self.engine.snapshot()
        tracks = {}
        try:
            for t in self.engine.tracker.tracks:
                tracks[(round(t.x / 8), round(t.y / 8))] = t
        except Exception:
            pass

        # 스캔 영역 테두리 — 어디를 보고 있는지 알려준다
        if snap is not None and snap.client_rect:
            l, t, w, h = snap.client_rect
            c.create_rectangle(l + 1, t + 1, l + w - 1, t + h - 1,
                               outline="#3399FF", width=1, dash=(6, 6))

        n = 0
        if snap is not None:
            for d in snap.detections:
                n += 1
                x0 = d.x - d.w // 2
                y0 = d.y - d.h // 2
                tr = tracks.get((round(d.x / 8), round(d.y / 8)))
                color = _BOX_OK
                label = f"{d.name} {d.score:.3f}"
                if tr is not None:
                    if tr.is_blocked():
                        color = _BOX_BLOCK
                        label += "  제외"
                    elif tr.attempts > 0:
                        color = _BOX_TRY
                        label += f"  시도{tr.attempts}"
                c.create_rectangle(x0, y0, x0 + d.w, y0 + d.h,
                                   outline=color, width=2)
                # 글자에 그림자를 깔아 밝은 배경에서도 읽히게 한다
                c.create_text(x0 + 1, y0 - 7, text=label, anchor="w",
                              fill="#000000", font=("맑은 고딕", 9, "bold"))
                c.create_text(x0, y0 - 8, text=label, anchor="w",
                              fill=color, font=("맑은 고딕", 9, "bold"))

        # 좌상단 상태판
        lines = [f"검출 {n}개"]
        if snap is not None:
            lines.append(f"스캔 {snap.scan_ms:.1f}ms")
            if not snap.detections and snap.top_miss:
                nm, sc, th = snap.top_miss
                lines.append(f"최고 {sc:.3f} / 임계 {th:.2f}  [{nm}]")
        try:
            lines.append(self.engine.tracker.summary())
            lines.append(self.engine.stats.brief())
        except Exception:
            pass
        # 페일세이프가 좌상단 모서리라 상태판은 조금 내려 그린다
        y = 60
        for ln in lines:
            c.create_text(21, y + 1, text=ln, anchor="w",
                          fill="#000000", font=("맑은 고딕", 10, "bold"))
            c.create_text(20, y, text=ln, anchor="w",
                          fill="#FFFFFF", font=("맑은 고딕", 10, "bold"))
            y += 18
