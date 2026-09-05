# -*- coding: utf-8 -*-
"""
오토 클릭 — 단독 프로그램.

줍기·사냥 도우미와 무관하다. 화면을 보지 않고 정해진 간격으로
마우스나 키를 반복 입력하기만 한다.

core/ 는 함께 쓴다 — 인간형 입력(지터·유지시간 변동), 키 캡처 위젯,
페일세이프, DPI 선언이 이미 거기 있고 다시 만들 이유가 없다.
"""
import json
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox

from core import geometry, paths
from core.actuation import HumanInput
from core.keycapture import KeyCaptureEntry, pretty as key_pretty
from core.updateui import UpdateBar, version_text
from core.window import GameWindow, foreground_title, window_at

geometry.declare_dpi_aware()

try:
    from pynput.keyboard import GlobalHotKeys
    HAS_HOTKEYS = True
except Exception:
    HAS_HOTKEYS = False

from pynput.mouse import Button

# 배포본에서는 app/ 안에서 실행되고 data/ 는 그 형제다 (core.paths 참고)
APP_DIR = paths.app_dir(__file__)
DATA_DIR = paths.data_dir(__file__)
CONFIG_FILE = DATA_DIR / "config_autoclick.json"

COLOR_BG      = "#F1F3F8"
COLOR_CARD    = "#FFFFFF"
COLOR_BORDER  = "#E1E4EB"
COLOR_TEXT    = "#1A1A2E"
COLOR_SUBTEXT = "#5C6275"
COLOR_ACCENT  = "#00695C"
COLOR_ACCENT2 = "#004D40"
COLOR_OK      = "#1B5E20"
COLOR_WARN    = "#C62828"
COLOR_OFF     = "#546E7A"

DEFAULT_CONFIG = {
    "interval_ms": 1000,
    "jitter_percent": 0,          # 0 이면 정확히 그 간격
    "do_click": True,
    "click_button": "left",       # left | right | middle
    "do_key": False,
    "key": "",
    "position_mode": "cursor",    # cursor | fixed
    "fixed_x": 0,
    "fixed_y": 0,
    "limit_count": 0,             # 0 = 무제한
    # 누르고 있는 시간. 게임이 프레임 단위로 입력을 읽으면 너무 짧으면 놓친다.
    "click_hold_ms": 60,
    "start_delay_sec": 3,         # 시작 누르고 대상 창으로 돌아갈 시간
    "hotkey_toggle": "<home>",
    "hotkey_stop": "<f12>",
    "failsafe_corner": True,
    "failsafe_margin_px": 3,
    "window_lock": False,
    "window_title": "",
}

_BUTTONS = {"left": Button.left, "right": Button.right,
            "middle": Button.middle}
_BUTTON_LABEL = {"left": "왼쪽", "right": "오른쪽", "middle": "가운데"}


# ===================================================================
# 엔진
# ===================================================================
class ClickEngine:
    """타이머 하나로 도는 단순 반복기.

    줍기·사냥과 달리 화면을 보지 않으므로 스레드가 하나면 충분하다.
    """

    def __init__(self, config_getter, log=None, on_state=None, on_count=None):
        self._cfg = config_getter
        self._log = log or (lambda m: None)
        self._on_state = on_state
        self._on_count = on_count

        self.hands = HumanInput(config_getter, log)
        self.window = GameWindow()

        self._running = False
        self._stop = threading.Event()
        self._thread = None
        self.count = 0
        self.started_at = 0.0

    def _c(self, key, default):
        v = (self._cfg() or {}).get(key, default)
        return default if v is None else v

    def is_running(self):
        return self._running

    def elapsed(self):
        return (time.monotonic() - self.started_at) if self._running else 0.0

    # ---------------------------------------------------------------
    def start(self):
        if self._running:
            return
        cfg = self._cfg() or {}
        if not cfg.get("do_click") and not cfg.get("do_key"):
            self._log("⚠  마우스 클릭이나 키 입력 중 하나는 켜야 합니다.")
            return
        if cfg.get("do_key") and not str(cfg.get("key", "")).strip():
            self._log("⚠  키 입력을 켰는데 키가 비어 있습니다.")
            return

        self._running = True
        self._stop.clear()
        self.count = 0
        self.started_at = time.monotonic()

        parts = []
        if cfg.get("do_click"):
            parts.append(f"{_BUTTON_LABEL.get(cfg.get('click_button'), '왼쪽')} 클릭")
        if cfg.get("do_key"):
            parts.append(f"'{str(cfg.get('key')).upper()}' 키")
        limit = int(cfg.get("limit_count", 0) or 0)
        self._log(f"▶  시작 — {' + '.join(parts)} · "
                  f"{cfg.get('interval_ms', 1000)}ms 간격"
                  + (f" · {limit}회 후 정지" if limit > 0 else ""))
        if cfg.get("failsafe_corner", True):
            self._log("🛟  커서를 화면 왼쪽 위 모서리로 보내면 즉시 정지합니다")

        delay = max(0, int(cfg.get("start_delay_sec", 0) or 0))
        if delay:
            self._log(f"{delay}초 뒤 시작합니다 — 그동안 대상 창을 눌러 두세요")

        self.window.set_filter(cfg.get("window_title", "")
                               if cfg.get("window_lock") else "")
        if self._on_state:
            self._on_state(True)
        geometry.raise_timer_resolution(1)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        if not self._running:
            return
        self._running = False
        self._stop.set()
        geometry.restore_timer_resolution(1)
        el = time.monotonic() - self.started_at
        self._log(f"■  정지 — {self.count}회 · {el:.1f}초")
        if self._on_state:
            self._on_state(False)

    def toggle(self):
        self.stop() if self._running else self.start()

    # ---------------------------------------------------------------
    def _run(self):
        # 시작 직후에는 이 프로그램 창이 활성이다. 대상 창으로 돌아갈 틈을 준다.
        delay = max(0, int(self._c("start_delay_sec", 0) or 0))
        if delay and self._stop.wait(delay):
            return
        next_at = time.monotonic()
        while self._running and not self._stop.is_set():
            now = time.monotonic()
            if now < next_at:
                if self._stop.wait(min(next_at - now, 0.2)):
                    return
                continue

            if self._blocked():
                if self._stop.wait(0.15):
                    return
                next_at = time.monotonic()
                continue

            try:
                self._fire()
            except Exception as e:
                self._log(f"⚠  입력 실패: {e}")

            limit = int(self._c("limit_count", 0) or 0)
            if limit > 0 and self.count >= limit:
                self._log(f"✓  {limit}회 완료")
                self.stop()
                return

            base = float(self._c("interval_ms", 1000))
            gap = self.hands.jittered_ms(base) if self._c("jitter_percent", 0) \
                else base
            next_at = time.monotonic() + gap / 1000.0

    def _blocked(self) -> bool:
        """페일세이프와 창 필터. 막혀 있으면 True."""
        if self._c("failsafe_corner", True):
            try:
                x, y = self.hands.cursor()
                m = int(self._c("failsafe_margin_px", 3))
                if x <= m and y <= m:
                    self._log("⛔  페일세이프 — 커서가 좌상단 모서리에 닿음")
                    self.stop()
                    return True
            except Exception:
                pass
        if self._c("window_lock", False):
            if not self.window.is_foreground():
                return True
        return False

    def _fire(self):
        # 고정 좌표 모드면 먼저 그 자리로 옮긴다
        if self._c("position_mode", "cursor") == "fixed":
            fx = int(self._c("fixed_x", 0))
            fy = int(self._c("fixed_y", 0))
            cur = self.hands.cursor()
            if abs(cur[0] - fx) > 2 or abs(cur[1] - fy) > 2:
                self.hands.mouse.position = (fx, fy)
                self.hands.last_moved_to = (fx, fy)

        if self._c("do_click", True):
            btn = _BUTTONS.get(self._c("click_button", "left"), Button.left)
            hold = max(5.0, float(self._c("click_hold_ms", 60))) / 1000.0
            self.hands.mouse.press(btn)
            time.sleep(hold)
            self.hands.mouse.release(btn)

        if self._c("do_key", False):
            key = str(self._c("key", "")).strip()
            if key:
                self.hands.press_key(key, self._stop)

        self.count += 1
        if self.count == 1:
            self._report_target()
        if self._on_count:
            self._on_count(self.count)

    def _report_target(self):
        """첫 입력이 어디로 갔는지 한 번 알린다.

        "클릭은 되는데 게임이 반응 없다" 는 말은 두 가지를 뜻할 수 있다.
        엉뚱한 창을 누르고 있거나, 정말로 게임이 무시하거나. 그걸 가른다.
        """
        try:
            x, y = self.hands.cursor()
            under = window_at(x, y) or "(알 수 없음)"
            active = foreground_title() or "(없음)"
            self._log(f"첫 입력 → ({x}, {y}) · 그 자리의 창 [{under}]")
            if active != under:
                self._log(f"⚠  활성 창은 [{active}] 입니다. "
                          f"입력은 활성 창이 받습니다 — 대상 창을 눌러 활성으로 두세요")
        except Exception:
            pass


# ===================================================================
# GUI
# ===================================================================
class HoverButton(tk.Button):
    def __init__(self, master, bg, hover_bg, fg="white", **kw):
        super().__init__(master, bg=bg, fg=fg, activebackground=hover_bg,
                         activeforeground=fg, relief="flat", bd=0,
                         cursor="hand2", **kw)
        self._bg, self._hover = bg, hover_bg
        self.bind("<Enter>", lambda _: self.config(bg=self._hover))
        self.bind("<Leave>", lambda _: self.config(bg=self._bg))


class AutoClickApp:
    def __init__(self, root):
        self.root = root
        root.title("오토 클릭")
        # 스크롤과 하단 고정이 있으므로 작게 줄여도 저장 버튼은 남는다
        root.geometry("560x720")
        root.minsize(460, 320)
        root.configure(bg=COLOR_BG)

        self.cfg = self._load()
        self.engine = ClickEngine(
            lambda: self.cfg, log=self._log_safe,
            on_state=self._state_safe, on_count=self._count_safe)
        self._hotkeys = None
        self._picking = False

        self._build()
        self._sync_to_ui()
        self._update_hotkeys()
        self._tick()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------- 설정 ----------------
    def _load(self):
        cfg = dict(DEFAULT_CONFIG)
        try:
            if CONFIG_FILE.exists():
                saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                for k in DEFAULT_CONFIG:
                    if k in saved:
                        cfg[k] = saved[k]
        except Exception:
            pass
        return cfg

    def _save(self):
        try:
            CONFIG_FILE.write_text(
                json.dumps(self.cfg, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception as e:
            self._log(f"⚠  설정 저장 실패: {e}")

    # ---------------- UI ----------------
    def _card(self, parent, title, desc=""):
        # parent 는 스크롤 영역(body)이다. self.root 에 붙이면 스크롤 밖에 남는다.
        outer = tk.Frame(parent, bg=COLOR_BG)
        outer.pack(fill="x", padx=16, pady=(12, 0))
        head = tk.Frame(outer, bg=COLOR_BG)
        head.pack(fill="x", padx=2)
        tk.Label(head, text=title, font=("맑은 고딕", 11, "bold"),
                 bg=COLOR_BG, fg=COLOR_TEXT).pack(side="left")
        if desc:
            tk.Label(head, text=f"   {desc}", font=("맑은 고딕", 9),
                     bg=COLOR_BG, fg=COLOR_SUBTEXT).pack(side="left")
        card = tk.Frame(outer, bg=COLOR_CARD,
                        highlightbackground=COLOR_BORDER, highlightthickness=1)
        card.pack(fill="x", pady=(4, 0))
        return card

    def _build(self):
        # 헤더
        hdr = tk.Frame(self.root, bg=COLOR_ACCENT, height=54)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="🖱  오토 클릭", font=("맑은 고딕", 15, "bold"),
                 bg=COLOR_ACCENT, fg="white").pack(side="left", padx=18)
        tk.Label(hdr, text="정해진 간격으로 반복 입력",
                 font=("맑은 고딕", 10), bg=COLOR_ACCENT,
                 fg="#B2DFDB").pack(side="left")
        tk.Label(hdr, text=version_text(), font=("맑은 고딕", 9),
                 bg=COLOR_ACCENT, fg="#B2DFDB").pack(side="right", padx=16)

        # 새 버전이 있을 때만 나타나는 띠
        self.update_bar = UpdateBar(
            self.root, app_dir=APP_DIR, log=self._log,
            on_before_restart=lambda: self.engine.stop())
        self.update_bar.check()

        # 상태 배너
        self.banner = tk.Frame(self.root, bg=COLOR_OFF, height=42)
        self.banner.pack(fill="x")
        self.banner.pack_propagate(False)
        self.state_label = tk.Label(
            self.banner, text="■  정지됨", font=("맑은 고딕", 11, "bold"),
            bg=COLOR_OFF, fg="white")
        self.state_label.pack(side="left", padx=18)
        self.hint_label = tk.Label(
            self.banner, text="", font=("맑은 고딕", 9),
            bg=COLOR_OFF, fg="#E0E0E0")
        self.hint_label.pack(side="right", padx=18)

        # ── 하단 고정 ──
        # 창을 줄여도 저장 버튼은 남아야 한다. 먼저 pack 해서 자리를 잡는다.
        bottom = tk.Frame(self.root, bg=COLOR_BG)
        bottom.pack(side="bottom", fill="x", padx=16, pady=(6, 8))
        HoverButton(bottom, bg="#1565C0", hover_bg="#0D47A1",
                    text="💾  설정 저장", font=("맑은 고딕", 10, "bold"),
                    padx=18, pady=6, command=self._save_from_ui).pack(
            side="left")
        self.log_label = tk.Label(
            bottom, text="", font=("맑은 고딕", 9), bg=COLOR_BG,
            fg=COLOR_SUBTEXT, anchor="w", justify="left")
        self.log_label.pack(side="left", padx=12, fill="x", expand=True)

        # ── 스크롤 영역 ──
        # 창이 작아지면 설정이 잘린다. 잘린 곳에 닿을 수 있어야 한다.
        wrap = tk.Frame(self.root, bg=COLOR_BG)
        wrap.pack(fill="both", expand=True)
        canvas = tk.Canvas(wrap, bg=COLOR_BG, highlightthickness=0)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        body = tk.Frame(canvas, bg=COLOR_BG)
        win = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(win, width=e.width))

        def _wheel(e):
            # 스크롤할 것이 없으면 가만히 둔다 (창이 충분히 크면 안 움직인다)
            r = canvas.bbox("all")
            if r and r[3] > canvas.winfo_height():
                canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
        canvas.bind_all("<MouseWheel>", _wheel)
        self._scroll_canvas = canvas

        # 시작 버튼 + 카운터
        top = tk.Frame(body, bg=COLOR_BG)
        top.pack(fill="x", padx=16, pady=(14, 0))
        self.toggle_btn = HoverButton(
            top, bg=COLOR_OK, hover_bg="#2E7D32", text="▶   시작",
            font=("맑은 고딕", 13, "bold"), padx=26, pady=10,
            command=self._toggle)
        self.toggle_btn.pack(side="left")
        self.count_label = tk.Label(
            top, text="0 회", font=("맑은 고딕", 20, "bold"),
            bg=COLOR_BG, fg=COLOR_TEXT)
        self.count_label.pack(side="right", padx=(0, 6))
        self.elapsed_label = tk.Label(
            top, text="", font=("맑은 고딕", 9),
            bg=COLOR_BG, fg=COLOR_SUBTEXT)
        self.elapsed_label.pack(side="right", padx=8)

        # ── 간격 ──
        card = self._card(body, "⏱  간격")
        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=(10, 4))
        tk.Label(row, text="입력 간격:", font=("맑은 고딕", 10),
                 bg=COLOR_CARD).pack(side="left")
        self.interval_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.interval_var, width=8,
                  justify="right").pack(side="left", padx=6)
        tk.Label(row, text="ms", font=("맑은 고딕", 10),
                 bg=COLOR_CARD).pack(side="left")
        for label, ms in (("50", 50), ("100", 100), ("500", 500),
                          ("1000", 1000)):
            HoverButton(row, bg="#78909C", hover_bg="#546E7A", text=label,
                        font=("맑은 고딕", 8), padx=7, pady=1,
                        command=lambda v=ms: self.interval_var.set(str(v))
                        ).pack(side="left", padx=2)

        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=(2, 10))
        tk.Label(row, text="흔들림:", font=("맑은 고딕", 10),
                 bg=COLOR_CARD).pack(side="left")
        self.jitter_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.jitter_var, width=6,
                  justify="right").pack(side="left", padx=6)
        tk.Label(row, text="%   (0 이면 정확히 그 간격으로)",
                 font=("맑은 고딕", 9), bg=COLOR_CARD,
                 fg=COLOR_SUBTEXT).pack(side="left")

        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=(2, 4))
        tk.Label(row, text="누르는 시간:", font=("맑은 고딕", 10),
                 bg=COLOR_CARD).pack(side="left")
        self.hold_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.hold_var, width=6,
                  justify="right").pack(side="left", padx=6)
        tk.Label(row, text="ms   (게임이 반응 없으면 80~120 으로 늘려보세요)",
                 font=("맑은 고딕", 9), bg=COLOR_CARD,
                 fg=COLOR_SUBTEXT).pack(side="left")

        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=(2, 10))
        tk.Label(row, text="시작 지연:", font=("맑은 고딕", 10),
                 bg=COLOR_CARD).pack(side="left")
        self.delay_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.delay_var, width=6,
                  justify="right").pack(side="left", padx=6)
        tk.Label(row, text="초   (그 사이에 게임 창을 눌러 두세요)",
                 font=("맑은 고딕", 9), bg=COLOR_CARD,
                 fg=COLOR_SUBTEXT).pack(side="left")

        # ── 무엇을 누를까 ──
        card = self._card(body, "🖱  동작", "둘 다 켜면 함께 나갑니다.")
        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=(10, 4))
        self.click_var = tk.BooleanVar()
        ttk.Checkbutton(row, text="마우스", variable=self.click_var).pack(
            side="left")
        self.button_var = tk.StringVar()
        for val, lab in (("left", "왼쪽"), ("right", "오른쪽"),
                         ("middle", "가운데")):
            ttk.Radiobutton(row, text=lab, value=val,
                            variable=self.button_var).pack(side="left", padx=6)

        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=(2, 10))
        self.key_on_var = tk.BooleanVar()
        ttk.Checkbutton(row, text="키 입력", variable=self.key_on_var).pack(
            side="left", padx=(0, 8))
        self.key_var = tk.StringVar()
        KeyCaptureEntry(row, self.key_var, mode="plain", width=10,
                        bg=COLOR_CARD).pack(side="left")
        tk.Label(row, text="  (칸을 클릭하고 키를 누르세요)",
                 font=("맑은 고딕", 9), bg=COLOR_CARD,
                 fg=COLOR_SUBTEXT).pack(side="left")

        # ── 위치 ──
        card = self._card(body, "📍  클릭 위치")
        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=(10, 4))
        self.pos_var = tk.StringVar()
        ttk.Radiobutton(row, text="커서가 있는 자리", value="cursor",
                        variable=self.pos_var).pack(side="left")
        ttk.Radiobutton(row, text="고정 좌표", value="fixed",
                        variable=self.pos_var).pack(side="left", padx=(14, 8))
        self.pos_label = tk.Label(row, text="(0, 0)", font=("맑은 고딕", 9),
                                  bg=COLOR_CARD, fg=COLOR_SUBTEXT)
        self.pos_label.pack(side="left", padx=(0, 8))
        HoverButton(row, bg=COLOR_ACCENT, hover_bg=COLOR_ACCENT2,
                    text="위치 찍기", font=("맑은 고딕", 9), padx=10, pady=2,
                    command=self._pick_position).pack(side="left")

        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=(2, 10))
        tk.Label(row, text="반복 횟수:", font=("맑은 고딕", 10),
                 bg=COLOR_CARD).pack(side="left")
        self.limit_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.limit_var, width=8,
                  justify="right").pack(side="left", padx=6)
        tk.Label(row, text="회   (0 이면 멈출 때까지 계속)",
                 font=("맑은 고딕", 9), bg=COLOR_CARD,
                 fg=COLOR_SUBTEXT).pack(side="left")

        # ── 단축키 · 안전 ──
        card = self._card(body, "⌨  단축키와 안전")
        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=(10, 4))
        tk.Label(row, text="시작/정지:", font=("맑은 고딕", 10),
                 bg=COLOR_CARD).pack(side="left")
        self.hk_toggle_var = tk.StringVar()
        KeyCaptureEntry(row, self.hk_toggle_var, mode="hotkey", width=14,
                        bg=COLOR_CARD).pack(side="left", padx=(6, 16))
        tk.Label(row, text="비상 정지:", font=("맑은 고딕", 10),
                 bg=COLOR_CARD).pack(side="left")
        self.hk_stop_var = tk.StringVar()
        KeyCaptureEntry(row, self.hk_stop_var, mode="hotkey", width=14,
                        bg=COLOR_CARD).pack(side="left", padx=6)

        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=2)
        self.failsafe_var = tk.BooleanVar()
        ttk.Checkbutton(row, text="커서를 화면 왼쪽 위 모서리로 보내면 즉시 정지",
                        variable=self.failsafe_var).pack(side="left")

        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=(2, 10))
        self.wlock_var = tk.BooleanVar()
        ttk.Checkbutton(row, text="이 창이 활성일 때만:",
                        variable=self.wlock_var).pack(side="left")
        self.wtitle_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.wtitle_var, width=20).pack(
            side="left", padx=6)


    # ---------------- 설정 <-> UI ----------------
    def _sync_to_ui(self):
        c = self.cfg
        self.interval_var.set(str(c.get("interval_ms", 1000)))
        self.jitter_var.set(str(c.get("jitter_percent", 0)))
        self.hold_var.set(str(c.get("click_hold_ms", 60)))
        self.delay_var.set(str(c.get("start_delay_sec", 3)))
        self.click_var.set(bool(c.get("do_click", True)))
        self.button_var.set(c.get("click_button", "left"))
        self.key_on_var.set(bool(c.get("do_key", False)))
        self.key_var.set(str(c.get("key", "")))
        self.pos_var.set(c.get("position_mode", "cursor"))
        self.pos_label.config(
            text=f"({c.get('fixed_x', 0)}, {c.get('fixed_y', 0)})")
        self.limit_var.set(str(c.get("limit_count", 0)))
        self.hk_toggle_var.set(c.get("hotkey_toggle", "<home>"))
        self.hk_stop_var.set(c.get("hotkey_stop", "<f12>"))
        self.failsafe_var.set(bool(c.get("failsafe_corner", True)))
        self.wlock_var.set(bool(c.get("window_lock", False)))
        self.wtitle_var.set(c.get("window_title", ""))
        self._update_hint()

    def _save_from_ui(self, silent=False):
        c = self.cfg
        try:
            iv = int(self.interval_var.get() or "1000")
            if iv < 1:
                raise ValueError("입력 간격은 1ms 이상이어야 합니다.")
            c["interval_ms"] = iv
            c["jitter_percent"] = max(0, min(90,
                                             int(self.jitter_var.get() or "0")))
            c["limit_count"] = max(0, int(self.limit_var.get() or "0"))
            c["click_hold_ms"] = max(5, int(self.hold_var.get() or "60"))
            c["start_delay_sec"] = max(0, int(self.delay_var.get() or "0"))
        except ValueError as e:
            messagebox.showerror("입력 오류", str(e))
            return False

        c["do_click"] = bool(self.click_var.get())
        c["click_button"] = self.button_var.get() or "left"
        c["do_key"] = bool(self.key_on_var.get())
        c["key"] = self.key_var.get().strip()
        c["position_mode"] = self.pos_var.get() or "cursor"
        c["hotkey_toggle"] = self.hk_toggle_var.get().strip() or "<home>"
        c["hotkey_stop"] = self.hk_stop_var.get().strip() or "<f12>"
        c["failsafe_corner"] = bool(self.failsafe_var.get())
        c["window_lock"] = bool(self.wlock_var.get())
        c["window_title"] = self.wtitle_var.get().strip()

        self._save()
        self._update_hotkeys()
        self._update_hint()
        if not silent:
            self._log("✓  설정을 저장했습니다")
        return True

    # ---------------- 위치 찍기 ----------------
    def _pick_position(self):
        """3초 뒤 커서 위치를 고정 좌표로 잡는다.

        화면 어디든 찍을 수 있어야 하므로 창을 가리지 않고, 남은 시간을
        버튼 대신 상태 줄에 보여준다.
        """
        if self._picking:
            return
        self._picking = True
        self.pos_var.set("fixed")

        def countdown(n):
            if n > 0:
                self._log(f"📍  {n}초 뒤 커서 위치를 기록합니다 — 원하는 곳에 올려두세요")
                self.root.after(1000, lambda: countdown(n - 1))
                return
            x, y = self.engine.hands.cursor()
            self.cfg["fixed_x"], self.cfg["fixed_y"] = int(x), int(y)
            self.pos_label.config(text=f"({int(x)}, {int(y)})")
            self._log(f"📍  고정 좌표: ({int(x)}, {int(y)})")
            self._picking = False

        countdown(3)

    # ---------------- 실행 ----------------
    def _toggle(self):
        if not self.engine.is_running():
            if not self._save_from_ui(silent=True):
                return
        self.engine.toggle()

    def _update_hotkeys(self):
        if not HAS_HOTKEYS:
            return
        if self._hotkeys is not None:
            try:
                self._hotkeys.stop()
            except Exception:
                pass
            self._hotkeys = None
        try:
            self._hotkeys = GlobalHotKeys({
                self.cfg.get("hotkey_toggle", "<home>"):
                    lambda: self.root.after(0, self.engine.toggle),
                self.cfg.get("hotkey_stop", "<f12>"):
                    lambda: self.root.after(0, self.engine.stop),
            })
            self._hotkeys.start()
        except Exception as e:
            self._log(f"⚠  단축키 등록 실패: {e}")
            self._hotkeys = None

    def _update_hint(self):
        self.hint_label.config(
            text=f"시작/정지 {key_pretty(self.cfg.get('hotkey_toggle'))}"
                 f"   ·   비상 정지 {key_pretty(self.cfg.get('hotkey_stop'))}")

    # ---------------- 콜백 (스레드 -> GUI) ----------------
    def _post(self, fn):
        """워커 스레드에서 GUI 로 넘긴다.

        창이 닫히는 중이면 after 가 RuntimeError 를 던진다. 그걸 그냥 두면
        워커 스레드가 통째로 죽으므로 삼킨다 — 어차피 보여줄 창이 없다.
        """
        try:
            self.root.after(0, fn)
        except (RuntimeError, tk.TclError):
            pass

    def _log_safe(self, msg):
        self._post(lambda: self._log(msg))

    def _state_safe(self, running):
        self._post(lambda: self._paint_state(running))

    def _count_safe(self, n):
        self._post(lambda: self.count_label.config(text=f"{n} 회"))

    def _log(self, msg):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_label.config(text=f"[{stamp}] {msg}")

    def _paint_state(self, running):
        if running:
            self.banner.config(bg=COLOR_OK)
            self.state_label.config(bg=COLOR_OK, text="●  실행 중")
            self.hint_label.config(bg=COLOR_OK)
            self.toggle_btn.config(bg=COLOR_WARN, text="■   정지")
            self.toggle_btn._bg, self.toggle_btn._hover = COLOR_WARN, "#8B0000"
        else:
            self.banner.config(bg=COLOR_OFF)
            self.state_label.config(bg=COLOR_OFF, text="■  정지됨")
            self.hint_label.config(bg=COLOR_OFF)
            self.toggle_btn.config(bg=COLOR_OK, text="▶   시작")
            self.toggle_btn._bg, self.toggle_btn._hover = COLOR_OK, "#2E7D32"

    def _tick(self):
        if self.engine.is_running():
            el = self.engine.elapsed()
            rate = self.engine.count / el * 60 if el > 0.5 else 0
            self.elapsed_label.config(
                text=f"{el:.0f}초 · 분당 {rate:.0f}회")
        else:
            self.elapsed_label.config(text="")
        self.root.after(300, self._tick)

    def _on_close(self):
        try:
            self.engine.stop()
        except Exception:
            pass
        if self._hotkeys is not None:
            try:
                self._hotkeys.stop()
            except Exception:
                pass
        self.root.destroy()


def main():
    root = tk.Tk()
    AutoClickApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
