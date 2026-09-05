# -*- coding: utf-8 -*-
"""
키 입력 위젯 — 누르면 그 키가 들어간다.

예전에는 `<ctrl>+<shift>+z` 같은 문자열을 손으로 타이핑해야 했다.
형식을 외워야 하고, 오타가 나면 조용히 동작하지 않는다.

여기서는 칸을 클릭하고 원하는 키를 누르면 끝난다. tkinter 의 keysym 을
pynput 이 이해하는 이름으로 변환해준다.

두 가지 형식이 필요하다.
  hotkey  — GlobalHotKeys 용.  <home>, <ctrl>+<shift>+z
  plain   — press_key 용.      home, z            (꺾쇠 없음)
"""
import tkinter as tk

# tkinter keysym -> pynput Key 이름
_KEYSYM = {
    "Home": "home", "End": "end", "Insert": "insert", "Delete": "delete",
    "Prior": "page_up", "Next": "page_down",
    "Up": "up", "Down": "down", "Left": "left", "Right": "right",
    "Return": "enter", "KP_Enter": "enter",
    "Escape": "esc", "Tab": "tab", "BackSpace": "backspace",
    "space": "space", "Pause": "pause",
    "Caps_Lock": "caps_lock", "Num_Lock": "num_lock",
    "Scroll_Lock": "scroll_lock", "Print": "print_screen",
    "Menu": "menu",
}
for i in range(1, 25):
    _KEYSYM[f"F{i}"] = f"f{i}"
# 숫자패드는 위쪽 숫자열과 같은 문자로 취급한다
for i in range(10):
    _KEYSYM[f"KP_{i}"] = str(i)

# 수정자 자체는 단독으로 받지 않는다 (Ctrl 만 눌러 저장되면 곤란하다)
_MODIFIER_SYMS = {
    "Control_L", "Control_R", "Shift_L", "Shift_R",
    "Alt_L", "Alt_R", "Win_L", "Win_R", "Super_L", "Super_R",
    "ISO_Level3_Shift",
}

# event.state 비트 (Windows)
_SHIFT = 0x0001
_CTRL = 0x0004
_ALT = 0x20000


def event_to_key(event, allow_modifiers=True):
    """tkinter 키 이벤트를 (base, mods) 로 바꾼다. 못 쓰는 키면 None.

    base : pynput 이름 ('home', 'z', 'f1')
    mods : ['ctrl', 'shift', 'alt'] 중 눌린 것
    """
    sym = event.keysym
    if sym in _MODIFIER_SYMS:
        return None

    base = _KEYSYM.get(sym)
    if base is None:
        if len(sym) == 1:
            base = sym.lower()
        elif event.char and len(event.char) == 1 and event.char.isprintable():
            base = event.char.lower()
        else:
            return None

    mods = []
    if allow_modifiers:
        st = event.state
        if st & _CTRL:
            mods.append("ctrl")
        if st & _ALT:
            mods.append("alt")
        if st & _SHIFT:
            mods.append("shift")
    return (base, mods)


def format_hotkey(base, mods) -> str:
    """GlobalHotKeys 형식.  <ctrl>+<shift>+z"""
    parts = [f"<{m}>" for m in mods]
    parts.append(base if len(base) == 1 else f"<{base}>")
    return "+".join(parts)


def format_plain(base, mods=None) -> str:
    """press_key 형식. 수정자는 버린다 — 줍기 키에 조합은 쓰지 않는다."""
    return base


def pretty(value: str) -> str:
    """설정에 저장된 값을 사람이 읽기 좋게. '<home>' -> 'Home'"""
    if not value:
        return "(없음)"
    out = []
    for part in str(value).split("+"):
        p = part.strip().strip("<>")
        out.append(p.upper() if len(p) == 1 else
                   p.replace("_", " ").title())
    return " + ".join(out)


class KeyCaptureEntry(tk.Frame):
    """클릭하면 키 입력을 기다리고, 누른 키를 그대로 담는 칸."""

    def __init__(self, master, textvariable, mode="hotkey",
                 width=18, bg="#FFFFFF", **kw):
        super().__init__(master, bg=bg, **kw)
        self.var = textvariable
        self.mode = mode              # "hotkey" | "plain"
        self._armed = False

        self._label = tk.Label(
            self, textvariable=None, text="", width=width,
            font=("맑은 고딕", 9), bg="#FFFFFF", fg="#1A1A2E",
            relief="solid", bd=1, padx=6, pady=3,
            anchor="w", cursor="hand2")
        self._label.pack(fill="x")
        self._label.bind("<Button-1>", self._arm)
        self._label.bind("<FocusOut>", self._disarm)

        self.var.trace_add("write", lambda *_: self._render())
        self._render()

    # ------------------------------------------------------------------
    def _render(self):
        if self._armed:
            return
        self._label.config(text=pretty(self.var.get()),
                           bg="#FFFFFF", fg="#1A1A2E")

    def _arm(self, _=None):
        self._armed = True
        self._label.config(text="키를 누르세요…", bg="#FFF6D8", fg="#8A5B00")
        self._label.focus_set()
        self._label.bind("<KeyPress>", self._on_key)
        # 포커스를 잃으면 원래대로
        self._label.bind("<FocusOut>", self._disarm)

    def _disarm(self, _=None):
        if not self._armed:
            return
        self._armed = False
        self._label.unbind("<KeyPress>")
        self._render()

    def _on_key(self, event):
        got = event_to_key(event, allow_modifiers=(self.mode == "hotkey"))
        if got is None:
            return "break"          # 수정자만 눌렀다 — 계속 기다린다
        base, mods = got
        if self.mode == "hotkey":
            self.var.set(format_hotkey(base, mods))
        else:
            self.var.set(format_plain(base, mods))
        self._disarm()
        return "break"


# ---------------------------------------------------------------
# 시간 표기 — 설정은 ms 로 두고 화면에는 초로 보여준다
# ---------------------------------------------------------------
def sec_text(ms) -> str:
    """밀리초를 사람이 읽는 초 문자열로.  1000 -> '1',  250 -> '0.25'

    설정 파일은 계속 ms 를 쓴다. 바꾸면 이미 쓰던 사람의 설정이 깨지고,
    내부 계산도 전부 손봐야 한다. 보여줄 때만 초로 옮긴다.
    """
    try:
        v = float(ms) / 1000.0
    except (TypeError, ValueError):
        return "0"
    # :g 는 불필요한 0 을 없앤다 (1.0 -> '1', 0.250 -> '0.25')
    return f"{v:g}"


def sec_to_ms(text, default=1000) -> int:
    """초 문자열을 밀리초로.  '0.25' -> 250,  '1' -> 1000

    비었거나 숫자가 아니면 기본값을 돌려준다 — 입력 중에 잠깐 빈 칸이
    되는 것을 오류로 다루면 쓰기 불편하다.
    """
    try:
        s = str(text).strip().replace("초", "").strip()
        if not s:
            return int(default)
        return max(1, int(round(float(s) * 1000)))
    except (TypeError, ValueError):
        return int(default)
