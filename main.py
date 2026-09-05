# -*- coding: utf-8 -*-
"""
트릭스터 자동 줍기 매크로 — 메인 GUI.

두 가지 모드:
  - 템플릿 스캔: 화면에서 아이템 PNG를 찾아 마우스 이동 후 클릭
  - 고정 위치: 현재 커서 위치에 주기적 클릭 (템플릿 없을 때)
"""
import json
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox

import engine
from core import geometry, paths
from core.overlay import DebugOverlay
from core.keycapture import KeyCaptureEntry, pretty as key_pretty
from core.profiles import ProfileStore
from core.updateui import UpdateBar, version_text

try:
    from pynput.keyboard import GlobalHotKeys
    HAS_HOTKEYS = True
except Exception:
    HAS_HOTKEYS = False

try:
    from PIL import Image, ImageTk, ImageEnhance
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# -----------------------------------------------------------
# 경로 / 테마
# -----------------------------------------------------------
# DPI 인식 선언 — 창을 만들기 전에, 프로세스당 한 번 (P0.2).
# 선언하지 않으면 배율 125% 이상에서 mss 캡처 좌표와 pynput 클릭 좌표가
# 서로 다른 좌표계를 쓰게 되어 클릭이 빗나간다.
geometry.declare_dpi_aware()

# 배포본에서는 코드가 app/ 안에 있고 data/ 는 그 형제다.
# 업데이트가 app/ 만 갈아끼우므로 설정과 템플릿이 살아남는다.
APP_DIR     = paths.app_dir(__file__)
DATA_DIR    = paths.data_dir(__file__)

# 줍기와 사냥은 별개 프로그램이다. 코드는 하나지만 실행 인자로 갈리고,
# 설정 파일도 따로 쓴다 — 한쪽 설정을 만져도 다른 쪽이 흔들리지 않게.
HUNT_MODE = "--hunt" in sys.argv
MODE      = "hunt" if HUNT_MODE else "pickup"
APP_TITLE = ("트릭스터 사냥 매크로" if HUNT_MODE
             else "트릭스터 자동 줍기 매크로")
APP_TAG   = ("스킬 사냥 · 물약 · 자동 줍기" if HUNT_MODE
             else "템플릿 스캔 / 고정 위치 클릭")

CONFIG_FILE = DATA_DIR / f"config_{MODE}.json"

# 예전 단일 설정 파일이 있으면 줍기 쪽으로 한 번만 옮겨준다
_OLD_CONFIG = DATA_DIR / "config.json"
if _OLD_CONFIG.exists() and not CONFIG_FILE.exists() and MODE == "pickup":
    try:
        CONFIG_FILE.write_bytes(_OLD_CONFIG.read_bytes())
    except OSError:
        pass

COLOR_BG      = "#F1F3F8"
COLOR_CARD    = "#FFFFFF"
COLOR_BORDER  = "#E1E4EB"
COLOR_TEXT    = "#1A1A2E"
COLOR_SUBTEXT = "#5C6275"
COLOR_ACCENT  = "#1565C0"
COLOR_ACCENT2 = "#0D47A1"
COLOR_OK      = "#1B5E20"
COLOR_WARN    = "#C62828"
COLOR_OFF     = "#546E7A"


DEFAULT_CONFIG = {
    "window_title": "Trickster",
    # 제목만 보면 엉뚱한 창이 걸린다 — 실제로 "trickster_macro - 파일 탐색기"가
    # 매칭돼 탐색기에 입력이 갈 뻔했다. 실행 파일 이름까지 확인한다.
    "window_process": "Trickster.bin",
    "window_lock": True,
    # 주기 (ms)
    "click_interval_ms": 1200,
    "key_interval_ms": 200,
    "pickup_key": "z",
    # 단축키
    "hotkey_toggle": "<home>",
    "hotkey_stop": "<f12>",
    # 자연스러운 동작
    "jitter_percent": 30,
    "hesitate_probability": 0.08,
    "hesitate_ms_min": 180,
    "hesitate_ms_max": 650,
    "rest_cycle_enabled": True,
    "work_min_minutes": 25,
    "work_max_minutes": 50,
    "rest_min_minutes": 4,
    "rest_max_minutes": 12,
    # 템플릿 스캔
    "templates": [],
    "default_threshold": 0.85,
    "mouse_move_ms": 120,
    "pre_move_delay_ms": 20,

    # --- v4: 지각 (P1.3) ---
    "scan_interval_ms": 250,      # 지각 주기 — 클릭 주기와 독립
    "coarse_scale": 0.5,          # 1차 스캔 축소 비율
    "coarse_margin": 0.22,        # 축소본에서 후보를 넓게 잡는 여유
    "fast_reject": True,          # 색이 없으면 매칭 자체를 건너뜀
    "max_detections": 12,         # 한 프레임에서 취할 최대 검출 수
    "scan_radius_px": 0,          # 0이면 창 전체, 양수면 중심 반경만
    "scan_center_dx": 0,
    "scan_center_dy": 0,
    "max_snapshot_age_sec": 1.5,  # 이보다 오래된 관측으로는 클릭하지 않음

    # --- v4: 추적 (P1.4) ---
    "track_match_px": 28,         # 프레임 간 같은 대상으로 볼 거리
    "track_lost_sec": 1.2,        # 이 시간 안 보이면 사라진 것으로 판정
    "max_attempts": 3,            # 이 횟수를 넘겨 실패하면 제외
    "block_sec": 20,              # 제외 유지 시간
    "retry_gap_sec": 1.0,         # 같은 대상 재시도 최소 간격

    # --- v4: 인간형 입력 (P1.6) ---
    "overshoot_enabled": True,    # 목표를 지나쳤다 되돌아오는 보정
    "micro_drift": True,          # 클릭 직전 미세 흔들림
    "click_hold_min_ms": 42,
    "click_hold_max_ms": 96,
    "key_hold_min_ms": 28,
    "key_hold_max_ms": 72,

    # --- v4: 사냥 (P2) ---
    # 사냥 프로그램에서는 기본으로 켜져 있다 (아래에서 모드에 맞춰 덮어씀)
    "combat_enabled": False,
    "attack_interval_ms": 1500,     # 같은 대상을 다시 클릭하는 간격
    # 공격 스킬 — 트릭스터는 스킬키를 누른 뒤 대상을 클릭한다.
    # 비우면 평타(클릭만). 쿨다운이 지난 것부터 순환해서 쓴다.
    "attack_skills": [],            # [{"key": "q", "cooldown": 3.0}, ...]
    "skill_click_gap_ms": 90,       # 스킬키 누른 뒤 클릭까지
    "attack_timeout_sec": 12,       # 이 시간 안에 못 잡으면 대상 교체
    "engage_block_sec": 15,         # 포기한 대상을 다시 안 보는 시간
    # HP/MP 바 — 설정 탭에서 영역을 지정하면 채워진다
    "hp_bar": None,
    "mp_bar": None,
    "hp_potion_key": "1",
    "hp_potion_percent": 50,        # 이 % 이하로 떨어지면 물약
    "mp_potion_key": "",
    "mp_potion_percent": 30,
    "potion_cooldown_sec": 2.0,     # 물약 연타 방지
    "potion_gap_ms": 350,           # 물약 먹은 뒤 다음 행동까지
    "hp_halt_percent": 15,          # 이 % 이하면 위험 — 스스로 정지
    "death_hp_percent": 0,          # 이 % 이하를 사망으로 본다

    # --- v4: 안전 (P1.7) ---
    "failsafe_corner": True,          # 커서를 좌상단 모서리로 → 즉시 정지
    "failsafe_margin_px": 3,
    "pause_on_user_input": True,      # 사람이 마우스를 만지면 일시정지
    "user_move_tolerance_px": 6,
    "user_pause_sec": 4,
    "stop_when_window_gone": True,
    "window_gone_grace_sec": 5,
    "max_consecutive_failures": 25,
}


# 사냥 프로그램은 사냥이 켜진 상태로 시작한다. 줍기 프로그램은 꺼진 채로 두고
# 사냥 관련 위젯도 만들지 않으므로 이 값이 바뀔 일이 없다.
if HUNT_MODE:
    DEFAULT_CONFIG["combat_enabled"] = True


# -----------------------------------------------------------
# 캡처 오버레이 (모듈 레벨)
# -----------------------------------------------------------
class _CaptureOverlay(tk.Toplevel):
    """전체 화면 오버레이 — 스크린샷을 배경으로 표시하고 드래그로 영역 선택."""

    def __init__(self, parent, pil_image, on_select, on_cancel):
        super().__init__(parent)
        self._on_select = on_select
        self._on_cancel = on_cancel
        self._start_xy  = None
        self._rect_id   = None

        w = self.winfo_screenwidth()
        h = self.winfo_screenheight()

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.geometry(f"{w}x{h}+0+0")

        # 스크린샷을 배경으로
        darkened = ImageEnhance.Brightness(pil_image).enhance(0.65)
        self._photo = ImageTk.PhotoImage(darkened)

        self.canvas = tk.Canvas(
            self, width=w, height=h,
            highlightthickness=0, cursor="crosshair", bg="#000000")
        self.canvas.pack()
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo)

        # 안내 바
        self.canvas.create_rectangle(0, 0, w, 52, fill="#111827", outline="")
        self.canvas.create_text(
            w // 2, 26,
            text="마우스를 드래그해서 아이템을 선택하세요   |   ESC = 취소",
            fill="#F0F4FF", font=("맑은 고딕", 13, "bold"))

        self.canvas.bind("<ButtonPress-1>",   self._press)
        self.canvas.bind("<B1-Motion>",       self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.bind("<Escape>", self._cancel)
        self.focus_force()

    def _press(self, e):
        self._start_xy = (e.x, e.y)
        if self._rect_id:
            self.canvas.delete(self._rect_id)
            self._rect_id = None

    def _drag(self, e):
        if not self._start_xy:
            return
        if self._rect_id:
            self.canvas.delete(self._rect_id)
        x1, y1 = self._start_xy
        self._rect_id = self.canvas.create_rectangle(
            x1, y1, e.x, e.y,
            outline="#00E676", width=2, dash=(6, 3))

    def _release(self, e):
        if not self._start_xy:
            return
        x1, y1 = self._start_xy
        x2, y2 = e.x, e.y
        self.destroy()
        rx1, rx2 = sorted([x1, x2])
        ry1, ry2 = sorted([y1, y2])
        if (rx2 - rx1) >= 6 and (ry2 - ry1) >= 6:
            self._on_select(rx1, ry1, rx2, ry2)
        else:
            self._on_cancel()

    def _cancel(self, _=None):
        self.destroy()
        self._on_cancel()


# -----------------------------------------------------------
# HoverButton
# -----------------------------------------------------------
class HoverButton(tk.Button):
    def __init__(self, master, bg, hover_bg, fg="white", **kw):
        super().__init__(
            master, bg=bg, fg=fg,
            activebackground=hover_bg, activeforeground=fg,
            relief="flat", bd=0, cursor="hand2", **kw)
        self._bg    = bg
        self._hover = hover_bg
        self.bind("<Enter>", lambda _: self.config(bg=self._hover))
        self.bind("<Leave>", lambda _: self.config(bg=self._bg))


# -----------------------------------------------------------
# App
# -----------------------------------------------------------
class MacroApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("900x700")
        self.root.minsize(780, 580)
        self.root.configure(bg=COLOR_BG)

        self.config_data = self._load_config()
        self.engine = engine.MacroEngine()
        self.engine.set_config(self.config_data)
        self.engine.set_callbacks(
            log=self._on_engine_log_threadsafe,
            status=self._on_engine_status_threadsafe,
            phase=self._on_engine_phase_threadsafe,
        )
        # 시작 시 저장된 템플릿 로드
        self.engine.load_templates(DATA_DIR, self.config_data.get("templates", []))

        self._hotkey_listener = None
        self._overlay = DebugOverlay(self.root, self.engine)
        self._profiles = ProfileStore(DATA_DIR / "profiles")

        # 템플릿 탭 내부 상태
        self._tpl_list_frame  = None
        self._tpl_list_canvas = None
        self._tpl_list_win_id = None
        self._tpl_row_vars    = []  # [(enabled_BoolVar, threshold_StringVar), ...]

        self._setup_style()
        self._build_ui()
        self._sync_settings_to_ui()
        self._refresh_summary()
        self._update_hotkey_listener()
        self._refresh_profiles()
        self._start_metric_timer()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # -------------------------------------------------
    # Config
    # -------------------------------------------------
    def _load_config(self) -> dict:
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                cfg = {k: raw.get(k, v) for k, v in DEFAULT_CONFIG.items()}
                # templates 는 리스트 타입 — 구버전에 있던 경우 그대로 보존
                if isinstance(raw.get("templates"), list):
                    cfg["templates"] = raw["templates"]
                return cfg
            except Exception as e:
                messagebox.showwarning("설정 로드 실패",
                                       f"{e}\n기본값으로 시작합니다.")
        return json.loads(json.dumps(DEFAULT_CONFIG))

    def _save_config(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            messagebox.showerror("설정 저장 실패", str(e))

    # -------------------------------------------------
    # Style
    # -------------------------------------------------
    def _setup_style(self):
        style = ttk.Style()
        try:
            if "clam" in style.theme_names():
                style.theme_use("clam")
        except Exception:
            pass
        style.configure("TNotebook", background=COLOR_BG, borderwidth=0)
        style.configure(
            "TNotebook.Tab", padding=[18, 8],
            font=("맑은 고딕", 10, "bold"))
        style.map(
            "TNotebook.Tab",
            background=[("selected", COLOR_ACCENT), ("!selected", "#E3E7EF")],
            foreground=[("selected", "white"), ("!selected", COLOR_TEXT)])
        style.configure("TEntry", padding=4)

    # -------------------------------------------------
    # UI
    # -------------------------------------------------
    def _build_ui(self):
        # ── 헤더 ──
        head_bg = "#6A1B9A" if HUNT_MODE else COLOR_ACCENT
        header = tk.Frame(self.root, bg=head_bg, height=60)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header, text=("⚔  " if HUNT_MODE else "🎯  ") + APP_TITLE,
            font=("맑은 고딕", 15, "bold"),
            bg=head_bg, fg="white",
        ).pack(side="left", padx=20)
        tk.Label(
            header, text=version_text(), font=("맑은 고딕", 9),
            bg=head_bg, fg="#E1BEE7" if HUNT_MODE else "#B3E5FC",
        ).pack(side="right", padx=18)
        tk.Label(
            header, text=APP_TAG,
            font=("맑은 고딕", 10),
            bg=head_bg, fg="#E1BEE7" if HUNT_MODE else "#B3E5FC",
        ).pack(side="left")

        # 새 버전이 있을 때만 나타나는 띠. 없으면 화면에 아무것도 안 생긴다.
        self.update_bar = UpdateBar(
            self.root, app_dir=APP_DIR, log=lambda m: self._log_ui(m, "accent"),
            on_before_restart=lambda: self.engine.shutdown())
        self.update_bar.check()

        # ── 상태 배너 ──
        self.status_banner = tk.Frame(self.root, bg=COLOR_OFF, height=44)
        self.status_banner.pack(fill="x")
        self.status_banner.pack_propagate(False)
        self.status_label = tk.Label(
            self.status_banner, text="■  정지됨",
            font=("맑은 고딕", 12, "bold"),
            bg=COLOR_OFF, fg="white")
        self.status_label.pack(side="left", padx=20)
        self.hotkey_hint = tk.Label(
            self.status_banner, text="",
            font=("맑은 고딕", 9),
            bg=COLOR_OFF, fg="#CFD8DC")
        self.hotkey_hint.pack(side="right", padx=20)

        # ── Notebook ──
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=10, pady=10)

        self._build_run_tab()
        self._build_template_tab()
        self._build_settings_tab()

    # -------------------------------------------------
    # Run tab
    # -------------------------------------------------
    def _build_run_tab(self):
        f = tk.Frame(self.nb, bg=COLOR_BG)
        self.nb.add(f, text="▶  실행")

        # ── 시작 버튼 + 상태 요약 ──
        btn_wrap = tk.Frame(f, bg=COLOR_BG)
        btn_wrap.pack(fill="x", padx=20, pady=(14, 6))
        self.toggle_btn = HoverButton(
            btn_wrap, bg=COLOR_OK, hover_bg="#2E7D32",
            text="▶   시작",
            font=("맑은 고딕", 14, "bold"),
            padx=32, pady=12,
            command=self._on_toggle_clicked,
        )
        self.toggle_btn.pack(side="left")

        HoverButton(
            btn_wrap, bg="#5C6BC0", hover_bg="#3F51B5",
            text="?  사용법", font=("맑은 고딕", 9),
            padx=12, pady=4, command=self._toggle_help,
        ).pack(side="right", pady=8)

        sumcol = tk.Frame(btn_wrap, bg=COLOR_BG)
        sumcol.pack(side="left", padx=18, fill="x", expand=True)
        self.summary_label = tk.Label(
            sumcol, text="", font=("맑은 고딕", 10),
            bg=COLOR_BG, fg=COLOR_TEXT, anchor="w", justify="left")
        self.summary_label.pack(anchor="w")
        # 지금 왜 그렇게 동작하는가 — 창을 찾았는지, 왜 멈췄는지
        # 상태 줄은 버튼 행 밖에 둔다 — 안에 두면 남은 폭만 받아 두 줄로 접힌다
        self.ready_label = tk.Label(
            f, text="", font=("맑은 고딕", 9),
            bg=COLOR_BG, fg=COLOR_SUBTEXT, anchor="w", justify="left")
        self.ready_label.pack(fill="x", padx=22, pady=(0, 2))

        # ── 지표 타일 ──
        # v4 가 만들어내는 수치를 로그에서 끌어올린다. 예전에는 30초마다
        # 로그 한 줄로만 지나가서 지금 잘 되고 있는지 알 수 없었다.
        metrics = tk.Frame(f, bg=COLOR_BG)
        metrics.pack(fill="x", padx=20, pady=(6, 8))
        self.metric_vars = {}
        cells = (
            ("picked", "주운", "—"),
            ("rate",   "시간당", "—"),
            ("clicks", "클릭", "—"),
            ("scan",   "스캔", "—"),
            ("hit",    "발견율", "—"),
            ("track",  "추적", "—"),
        )
        for i, (key, label, init) in enumerate(cells):
            metrics.grid_columnconfigure(i, weight=1, uniform="m")
            cell = tk.Frame(metrics, bg=COLOR_CARD,
                            highlightbackground=COLOR_BORDER,
                            highlightthickness=1)
            cell.grid(row=0, column=i, sticky="ew",
                      padx=(0 if i == 0 else 6, 0))
            tk.Label(cell, text=label, font=("맑은 고딕", 8),
                     bg=COLOR_CARD, fg=COLOR_SUBTEXT).pack(pady=(7, 0))
            v = tk.StringVar(value=init)
            tk.Label(cell, textvariable=v,
                     font=("맑은 고딕", 15, "bold"),
                     bg=COLOR_CARD, fg=COLOR_TEXT).pack(pady=(0, 8))
            self.metric_vars[key] = v

        # ── 사용법 (기본 접힘) ──
        self.help_frame = tk.Frame(
            f, bg=COLOR_CARD,
            highlightbackground=COLOR_BORDER, highlightthickness=1)
        tk.Label(
            self.help_frame,
            text=(
                "   [템플릿 스캔 모드]  템플릿 탭에서 아이템을 캐프처해두면 자동으로 찾아서 클릭\n"
                "   [고정 위치 모드]  템플릿 없을 때 — 마우스 커서 위치에 그대로 클릭\n\n"
                "   1.  트릭스터 실행 → 템플릿 탭에서 [새 템플릿 캐프처] 클릭\n"
                "   2.  창이 최소화되면 게임 화면에서 아이템을 드래그로 선택\n"
                "   3.  F1 (또는 [시작]) 으로 매크로 시작\n"
                "   4.  멈출 땐 F1 다시 또는 F12 (비상 정지)\n"
                "   ※  급할 땐 마우스를 화면 왼쪽 위 모서리로 — 즉시 정지합니다"
            ),
            font=("맑은 고딕", 9),
            bg=COLOR_CARD, fg=COLOR_SUBTEXT,
            justify="left", anchor="w",
        ).pack(fill="x", padx=12, pady=10)
        self._help_open = False

        # ── 실행 로그 ──
        self.log_wrap = tk.Frame(
            f, bg=COLOR_CARD,
            highlightbackground=COLOR_BORDER, highlightthickness=1)
        self.log_wrap.pack(fill="both", expand=True, padx=20, pady=(0, 18))

        hdr = tk.Frame(self.log_wrap, bg=COLOR_CARD)
        hdr.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(hdr, text="📋  실행 로그",
                 font=("맑은 고딕", 11, "bold"),
                 bg=COLOR_CARD, fg=COLOR_TEXT).pack(side="left")
        HoverButton(
            hdr, bg="#616161", hover_bg="#424242",
            text="지우기", font=("맑은 고딕", 9),
            padx=12, pady=3, command=self._clear_log,
        ).pack(side="right")
        # 검출 결과를 화면 위에 직접 그린다 — 임계값 조정을 눈으로
        self.overlay_btn = HoverButton(
            hdr, bg="#00695C", hover_bg="#004D40",
            text="🔎 오버레이", font=("맑은 고딕", 9),
            padx=12, pady=3, command=self._toggle_overlay,
        )
        self.overlay_btn.pack(side="right", padx=(0, 6))

        body = tk.Frame(self.log_wrap, bg=COLOR_CARD)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.log_text = tk.Text(
            body, bg="#0F1115", fg="#B8C1EC",
            font=("Consolas", 9),
            relief="flat", bd=0, wrap="word",
            insertbackground="#B8C1EC",
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.log_text.yview)
        sb.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=sb.set)
        self.log_text.tag_configure("ok",     foreground="#81C784")
        self.log_text.tag_configure("warn",   foreground="#FFB74D")
        self.log_text.tag_configure("accent", foreground="#64B5F6")
        self.log_text.tag_configure("time",   foreground="#7E8AA3")

    # -------------------------------------------------
    # HP/MP 바 영역 지정 (P2.1)
    # -------------------------------------------------
    def _capture_bar(self, which: str):
        """게임 화면에서 바 영역을 드래그로 지정한다.

        색은 사용자가 고르지 않는다 — 지정한 영역에서 가장 두드러진
        채도 높은 색을 자동으로 찾아 기준으로 삼는다.
        """
        if not HAS_PIL:
            messagebox.showerror("불가", "Pillow 가 필요합니다.")
            return
        cr = self.engine.window.client_rect()
        if not cr:
            messagebox.showerror(
                "게임 창을 찾을 수 없음",
                "게임을 먼저 실행하세요.\n"
                "바 좌표는 창 기준으로 저장되므로 창이 필요합니다.")
            return

        self.root.iconify()

        def work():
            time.sleep(1.2)
            try:
                import mss as _mss
                with _mss.mss() as sct:
                    shot = sct.grab(sct.monitors[1])
                    img = Image.frombytes("RGB", shot.size,
                                          shot.bgra, "raw", "BGRX")
            except Exception as e:
                self.root.after(0, lambda: self._bar_failed(e))
                return
            self.root.after(0, lambda: self._show_bar_overlay(which, img, cr))

        threading.Thread(target=work, daemon=True).start()

    def _bar_failed(self, err):
        self.root.deiconify()
        messagebox.showerror("캡처 실패", str(err))

    def _show_bar_overlay(self, which, img, client_rect):
        label = "체력" if which == "hp" else "마나"
        _CaptureOverlay(
            self.root, img,
            on_select=lambda x1, y1, x2, y2:
                self._save_bar(which, img, client_rect, x1, y1, x2, y2),
            on_cancel=lambda: self.root.deiconify())
        self._log_ui(f"🩸  {label} 바 영역을 드래그하세요")

    def _save_bar(self, which, img, client_rect, x1, y1, x2, y2):
        self.root.deiconify()
        try:
            import numpy as _np
            import cv2 as _cv2
            from core.vitals import learn_color, BarSpec, read_ratio
        except ImportError:
            messagebox.showerror("불가", "opencv/numpy 가 필요합니다.")
            return

        patch = img.crop((x1, y1, x2, y2))
        bgr = _cv2.cvtColor(_np.array(patch), _cv2.COLOR_RGB2BGR)
        lo, hi = learn_color(bgr)
        if lo is None:
            messagebox.showerror(
                "색을 찾지 못함",
                "바 영역이 너무 작거나 색이 뚜렷하지 않습니다.\n"
                "가득 찬 상태에서 바 안쪽만 잡아보세요.")
            return

        # 화면 절대 → 창 클라이언트 상대 (창을 옮겨도 유효하도록)
        rect = (x1 - client_rect[0], y1 - client_rect[1], x2 - x1, y2 - y1)
        spec = BarSpec(rect, lo, hi)
        ratio = read_ratio(bgr, spec)

        self.config_data[f"{which}_bar"] = spec.to_config()
        self._save_config()
        self.engine.set_config(self.config_data)
        self._sync_bar_labels()

        name = "체력" if which == "hp" else "마나"
        pct = f"{ratio*100:.0f}%" if ratio is not None else "?"
        self._log_ui(f"🩸  {name} 바 지정 — 창 기준 {rect}, 현재 {pct}", "ok")
        messagebox.showinfo(
            "지정 완료",
            f"{name} 바를 등록했습니다.\n\n"
            f"현재 판독값: {pct}\n\n"
            "값이 실제와 다르면 바 안쪽만 다시 잡아주세요.")

    def _sync_bar_labels(self):
        for which, lab in (("hp", getattr(self, "hp_bar_label", None)),
                           ("mp", getattr(self, "mp_bar_label", None))):
            if lab is None:
                continue
            d = self.config_data.get(f"{which}_bar")
            if isinstance(d, dict) and d.get("rect"):
                r = d["rect"]
                lab.config(text=f"{r[2]}×{r[3]} 등록됨", fg=COLOR_OK)
            else:
                lab.config(text="지정 안 됨",
                           fg=COLOR_WARN if which == "hp" else COLOR_SUBTEXT)

    def _toggle_help(self):
        """사용법은 매번 읽는 것이 아니라 기본으로 접어둔다."""
        self._help_open = not self._help_open
        if self._help_open:
            self.help_frame.pack(fill="x", padx=20, pady=(0, 8),
                                 before=self.log_wrap)
        else:
            self.help_frame.pack_forget()

    # -------------------------------------------------
    # Template tab
    # -------------------------------------------------
    def _build_template_tab(self):
        f = tk.Frame(self.nb, bg=COLOR_BG)
        self.nb.add(f, text="🖼  템플릿")

        # ── 캡처 버튼 ──
        top = tk.Frame(f, bg=COLOR_BG)
        top.pack(fill="x", padx=20, pady=(16, 6))
        HoverButton(
            top, bg=COLOR_ACCENT, hover_bg=COLOR_ACCENT2,
            text="📷  새 템플릿 캡처",
            font=("맑은 고딕", 12, "bold"),
            padx=20, pady=8,
            command=self._start_capture,
        ).pack(side="left")
        tk.Label(
            top,
            text="  창이 최소화된 후 게임 화면에서 아이템을 드래그로 선택합니다.",
            font=("맑은 고딕", 9), bg=COLOR_BG, fg=COLOR_SUBTEXT,
        ).pack(side="left")

        # ── 옵션 행 ──
        opts = tk.Frame(f, bg=COLOR_BG)
        opts.pack(fill="x", padx=20, pady=(0, 10))

        tk.Label(opts, text="이동 시간:",
                 font=("맑은 고딕", 10), bg=COLOR_BG).pack(side="left")
        self.mouse_move_ms_var = tk.StringVar(value="120")
        ttk.Entry(opts, textvariable=self.mouse_move_ms_var,
                  width=5, justify="right").pack(side="left", padx=(4, 2))
        tk.Label(opts, text="ms",
                 font=("맑은 고딕", 9), bg=COLOR_BG, fg=COLOR_SUBTEXT).pack(side="left")

        tk.Label(opts, text="    도착 후 대기:",
                 font=("맑은 고딕", 10), bg=COLOR_BG).pack(side="left")
        self.pre_move_delay_var = tk.StringVar(value="20")
        ttk.Entry(opts, textvariable=self.pre_move_delay_var,
                  width=5, justify="right").pack(side="left", padx=(4, 2))
        tk.Label(opts, text="ms",
                 font=("맑은 고딕", 9), bg=COLOR_BG, fg=COLOR_SUBTEXT).pack(side="left")

        tk.Label(opts, text="    기본 임계값:",
                 font=("맑은 고딕", 10), bg=COLOR_BG).pack(side="left")
        self.default_threshold_var = tk.StringVar(value="0.85")
        ttk.Entry(opts, textvariable=self.default_threshold_var,
                  width=6, justify="right").pack(side="left", padx=(4, 2))
        tk.Label(opts, text="(0.5~1.0)",
                 font=("맑은 고딕", 9), bg=COLOR_BG, fg=COLOR_SUBTEXT).pack(side="left")

        HoverButton(
            opts, bg=COLOR_ACCENT, hover_bg=COLOR_ACCENT2,
            text="저장 및 적용",
            font=("맑은 고딕", 9, "bold"),
            padx=12, pady=4,
            command=self._save_template_settings,
        ).pack(side="right")

        # ── 템플릿 목록 ──
        list_outer = tk.Frame(
            f, bg=COLOR_CARD,
            highlightbackground=COLOR_BORDER, highlightthickness=1)
        list_outer.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        # 헤더
        hdr = tk.Frame(list_outer, bg="#E8EAEF")
        hdr.pack(fill="x")
        cols = [("사용", 4), ("미리보기", 9), ("이름", 17)]
        if HUNT_MODE:
            cols.append(("종류", 8))
        else:
            cols[2] = ("이름", 25)
        cols += [("임계값", 8), ("", 6)]
        for text, width in cols:
            tk.Label(hdr, text=text, font=("맑은 고딕", 9, "bold"),
                     bg="#E8EAEF", width=width, anchor="w").pack(
                side="left", padx=(8, 0), pady=4)

        # 스크롤 가능 목록 본문
        canvas = tk.Canvas(list_outer, bg=COLOR_CARD, highlightthickness=0)
        vsb = ttk.Scrollbar(list_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._tpl_list_frame = tk.Frame(canvas, bg=COLOR_CARD)
        self._tpl_list_win_id = canvas.create_window(
            (0, 0), window=self._tpl_list_frame, anchor="nw")
        self._tpl_list_frame.bind("<Configure>", lambda e: (
            canvas.configure(scrollregion=canvas.bbox("all")),
            canvas.itemconfig(self._tpl_list_win_id, width=canvas.winfo_width()),
        ))
        canvas.bind("<Configure>", lambda e:
            canvas.itemconfig(self._tpl_list_win_id, width=e.width))
        canvas.bind_all(
            "<MouseWheel>",
            lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))
        self._tpl_list_canvas = canvas

        self._reload_template_list()

    def _reload_template_list(self):
        if self._tpl_list_frame is None:
            return
        for w in self._tpl_list_frame.winfo_children():
            w.destroy()
        self._tpl_row_vars = []

        templates = self.config_data.get("templates", [])
        if not templates:
            tk.Label(
                self._tpl_list_frame,
                text="등록된 템플릿 없음 — [📷 새 템플릿 캡처] 버튼으로 추가하세요.",
                font=("맑은 고딕", 10),
                bg=COLOR_CARD, fg=COLOR_SUBTEXT,
            ).pack(anchor="w", padx=20, pady=24)
            return

        for i, t in enumerate(templates):
            row = tk.Frame(self._tpl_list_frame, bg=COLOR_CARD)
            row.pack(fill="x", padx=8, pady=3)

            enabled_var = tk.BooleanVar(value=bool(t.get("enabled", True)))
            ttk.Checkbutton(row, variable=enabled_var).pack(
                side="left", padx=(6, 2))

            # 썸네일
            thumb = tk.Label(row, bg=COLOR_CARD, width=7, height=3,
                             relief="groove")
            thumb.pack(side="left", padx=(4, 8))
            self._load_thumb(thumb, t.get("file", ""))

            # 이름
            tk.Label(row, text=t.get("name", "?"),
                     font=("맑은 고딕", 10), bg=COLOR_CARD,
                     anchor="w", width=17 if HUNT_MODE else 25).pack(side="left")

            # 임계값
            kind_var = tk.StringVar(
                value="몬스터" if t.get("kind") == "monster"
                else "아이템")
            if HUNT_MODE:
                kc = ttk.Combobox(row, textvariable=kind_var, width=7,
                                  state="readonly",
                                  values=("아이템", "몬스터"))
                kc.pack(side="left", padx=(0, 10))
            else:
                # 줍기 프로그램에는 종류가 없다 — 전부 아이템이다
                kind_var.set("아이템")

            thr_var = tk.StringVar(value=str(t.get("threshold", 0.85)))
            ttk.Entry(row, textvariable=thr_var, width=7,
                      justify="right", font=("Consolas", 9)).pack(
                side="left", padx=(0, 8))

            # 삭제
            idx = i
            HoverButton(
                row, bg="#B71C1C", hover_bg="#7F0000",
                text="삭제", font=("맑은 고딕", 9),
                padx=10, pady=2,
                command=lambda i=idx: self._delete_template(i),
            ).pack(side="right", padx=(0, 8))

            # 구분선
            tk.Frame(self._tpl_list_frame, bg=COLOR_BORDER, height=1).pack(
                fill="x", padx=8)

            self._tpl_row_vars.append((enabled_var, thr_var, kind_var))

    def _load_thumb(self, label: tk.Label, filename: str):
        if not HAS_PIL or not filename:
            return
        try:
            fpath = DATA_DIR / filename
            if not fpath.exists():
                return
            img = Image.open(str(fpath))
            img.thumbnail((56, 48), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            label.config(image=photo)
            label._photo = photo  # GC 방지
        except Exception:
            pass

    # -------------------------------------------------
    # 캡처 플로우
    # -------------------------------------------------
    def _start_capture(self):
        if not HAS_PIL:
            messagebox.showerror(
                "패키지 없음",
                "Pillow 패키지가 없어 캡처를 사용할 수 없습니다.\n"
                "run_macro.bat 을 다시 실행하거나\n"
                "pip install Pillow opencv-python mss numpy 를 실행하세요.")
            return

        self.root.iconify()

        def _worker():
            time.sleep(1.5)
            try:
                import mss
                import numpy as np
                with mss.mss() as sct:
                    mon = sct.monitors[1]
                    shot = sct.grab(mon)
                    arr = np.array(shot)
                # BGRA → RGB
                pil = Image.fromarray(arr[:, :, [2, 1, 0]])
            except Exception as e:
                self.root.after(0, lambda: (
                    self.root.deiconify(),
                    messagebox.showerror("스크린샷 오류", str(e))
                ))
                return

            def _show_overlay():
                def _on_select(x1, y1, x2, y2):
                    self.root.deiconify()
                    self._save_template(pil, x1, y1, x2, y2)

                def _on_cancel():
                    self.root.deiconify()

                _CaptureOverlay(self.root, pil, _on_select, _on_cancel)

            self.root.after(0, _show_overlay)

        threading.Thread(target=_worker, daemon=True).start()

    def _save_template(self, screenshot_pil, x1: int, y1: int, x2: int, y2: int):
        try:
            cropped = screenshot_pil.crop((x1, y1, x2, y2))
            ts = int(time.time() * 1000) & 0xFFFFFFFF
            fname = f"tpl_{ts:08x}.png"
            fpath = DATA_DIR / fname
            cropped.save(str(fpath))

            templates = self.config_data.setdefault("templates", [])
            name = f"아이템_{len(templates) + 1}"
            threshold = self.config_data.get("default_threshold", 0.85)
            templates.append({
                "name": name,
                "file": fname,
                "threshold": threshold,
                "enabled": True,
            })
            self._save_config()
            self._reload_template_list()
            self.engine.load_templates(DATA_DIR, templates)
            self._log_ui(
                f"✓  템플릿 추가: {name}  ({x2 - x1}×{y2 - y1}px)", "ok")
            self.nb.select(1)  # 템플릿 탭으로 이동
        except Exception as e:
            messagebox.showerror("템플릿 저장 실패", str(e))

    def _delete_template(self, idx: int):
        templates = self.config_data.get("templates", [])
        if not (0 <= idx < len(templates)):
            return
        t = templates.pop(idx)
        try:
            fpath = DATA_DIR / t.get("file", "")
            if fpath.exists():
                fpath.unlink()
        except Exception:
            pass
        self._save_config()
        self._reload_template_list()
        self.engine.load_templates(DATA_DIR, templates)
        self._log_ui(f"✓  템플릿 삭제: {t.get('name', '?')}", "ok")

    def _save_template_settings(self):
        try:
            move_ms = max(0, int(self.mouse_move_ms_var.get() or "120"))
            delay   = max(0, int(self.pre_move_delay_var.get() or "20"))
            thr     = max(0.5, min(1.0,
                          float(self.default_threshold_var.get() or "0.85")))
        except ValueError as e:
            messagebox.showerror("입력 오류", str(e))
            return

        self.config_data["mouse_move_ms"]      = move_ms
        self.config_data["pre_move_delay_ms"]  = delay
        self.config_data["default_threshold"]  = thr

        templates = self.config_data.get("templates", [])
        for i, (enabled_var, thr_var, kind_var) in enumerate(self._tpl_row_vars):
            if i >= len(templates):
                break
            templates[i]["enabled"] = bool(enabled_var.get())
            templates[i]["kind"] = (
                "monster" if kind_var.get() == "몬스터" else "item")
            try:
                templates[i]["threshold"] = max(0.5, min(1.0,
                    float(thr_var.get() or "0.85")))
            except ValueError:
                pass

        self._save_config()
        self.engine.load_templates(DATA_DIR, templates)
        self._log_ui("✓  템플릿 설정 저장 및 적용", "ok")

    # -------------------------------------------------
    # Settings tab
    # -------------------------------------------------
    def _build_settings_tab(self):
        f = tk.Frame(self.nb, bg=COLOR_BG)
        self.nb.add(f, text="⚙  설정")

        canvas = tk.Canvas(f, bg=COLOR_BG, highlightthickness=0)
        vsb = ttk.Scrollbar(f, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=COLOR_BG)
        wid = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: (
            canvas.configure(scrollregion=canvas.bbox("all")),
            canvas.itemconfig(wid, width=canvas.winfo_width()),
        ))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(wid, width=e.width))
        canvas.bind_all(
            "<MouseWheel>",
            lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        # ─ 프로필 ─
        card = self._settings_card(
            inner, "🗂  프로필",
            "사냥터별로 설정과 템플릿 목록을 통째로 저장해두고 바꿔 씁니다.")
        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=(10, 10))
        self.profile_var = tk.StringVar(value="")
        self.profile_combo = ttk.Combobox(
            row, textvariable=self.profile_var, width=22, state="readonly")
        self.profile_combo.pack(side="left", padx=(0, 8))
        HoverButton(row, bg="#1565C0", hover_bg="#0D47A1", text="불러오기",
                    font=("맑은 고딕", 9), padx=12, pady=3,
                    command=self._profile_load).pack(side="left", padx=2)
        HoverButton(row, bg="#2E7D32", hover_bg="#1B5E20", text="현재 설정 저장",
                    font=("맑은 고딕", 9), padx=12, pady=3,
                    command=self._profile_save).pack(side="left", padx=2)
        HoverButton(row, bg="#C62828", hover_bg="#8E0000", text="삭제",
                    font=("맑은 고딕", 9), padx=12, pady=3,
                    command=self._profile_delete).pack(side="left", padx=2)

        # ─ 주기 ─
        card = self._settings_card(
            inner, "⏱  입력 주기",
            "클릭과 키 입력 주기. 화면 스캔은 별도 스레드로 돌며 주기도 따로입니다 (스캔 성능 카드).")
        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=(10, 6))
        tk.Label(row, text="클릭 주기:",
                 font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left")
        self.click_interval_var = tk.StringVar(value="1000")
        ttk.Entry(row, textvariable=self.click_interval_var,
                  width=8, justify="right").pack(side="left", padx=4)
        tk.Label(row, text="ms   (권장: 500~1000)",
                 font=("맑은 고딕", 9), bg=COLOR_CARD,
                 fg=COLOR_SUBTEXT).pack(side="left")

        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=(0, 6))
        tk.Label(row, text="키 입력 주기:",
                 font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left")
        self.key_interval_var = tk.StringVar(value="200")
        ttk.Entry(row, textvariable=self.key_interval_var,
                  width=8, justify="right").pack(side="left", padx=4)
        tk.Label(row, text="ms",
                 font=("맑은 고딕", 9), bg=COLOR_CARD,
                 fg=COLOR_SUBTEXT).pack(side="left")

        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=(0, 10))
        tk.Label(row, text="줍기 키:",
                 font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left")
        self.pickup_key_var = tk.StringVar(value="z")
        KeyCaptureEntry(row, self.pickup_key_var, mode="plain",
                        width=10, bg=COLOR_CARD).pack(side="left", padx=4)
        tk.Label(row, text="  (칸을 클릭하고 키를 누르세요)",
                 font=("맑은 고딕", 9), bg=COLOR_CARD,
                 fg=COLOR_SUBTEXT).pack(side="left")

        # ─ 스캔 성능 ─
        card = self._settings_card(
            inner, "🔍  스캔 성능",
            "스캔은 클릭과 다른 스레드에서 돌기 때문에 짧게 잡아도 입력을 막지 않습니다.")
        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=(10, 4))
        tk.Label(row, text="스캔 주기:",
                 font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left")
        self.scan_interval_var = tk.StringVar(value="250")
        ttk.Entry(row, textvariable=self.scan_interval_var,
                  width=7, justify="right").pack(side="left", padx=4)
        tk.Label(row, text="ms    (권장 150~400)",
                 font=("맑은 고딕", 9), bg=COLOR_CARD,
                 fg=COLOR_SUBTEXT).pack(side="left")

        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=(2, 10))
        tk.Label(row, text="스캔 반경:",
                 font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left")
        self.scan_radius_var = tk.StringVar(value="0")
        ttk.Entry(row, textvariable=self.scan_radius_var,
                  width=7, justify="right").pack(side="left", padx=4)
        tk.Label(row, text="px    (0 = 창 전체 / 큰 화면은 400~600 이 빠릅니다)",
                 font=("맑은 고딕", 9), bg=COLOR_CARD,
                 fg=COLOR_SUBTEXT).pack(side="left")

        # ─ 창 필터 ─
        card = self._settings_card(
            inner, "🪟  게임 창 필터",
            "제목과 실행 파일 이름이 모두 맞는 창이 활성일 때만 입력합니다.")
        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=(10, 10))
        tk.Label(row, text="창 제목 포함:",
                 font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left")
        self.window_title_var = tk.StringVar()
        ttk.Entry(row, textvariable=self.window_title_var,
                  width=24).pack(side="left", padx=(6, 16))
        tk.Label(row, text="실행 파일:",
                 font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left")
        self.window_proc_var = tk.StringVar(value="Trickster.bin")
        ttk.Entry(row, textvariable=self.window_proc_var,
                  width=18).pack(side="left", padx=6)

        row2 = tk.Frame(card, bg=COLOR_CARD)
        row2.pack(fill="x", padx=14, pady=(0, 10))
        self.window_lock_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            row2, text="비활성 창일 땐 입력 중단",
            variable=self.window_lock_var,
        ).pack(side="left")
        tk.Label(row2,
                 text="   실행 파일을 비우면 제목만 확인합니다 — 다른 창이 잡힐 수 있습니다",
                 font=("맑은 고딕", 9), bg=COLOR_CARD,
                 fg=COLOR_SUBTEXT).pack(side="left")

        # 사냥 설정은 사냥 프로그램에만 보인다.
        # 줍기 프로그램에서 이걸 보여주면 켜지도 않을 값을 만지게 된다.
        self.skill_vars = []
        if HUNT_MODE:
            # ─ 사냥 ─
            card = self._settings_card(
                inner, "⚔  사냥",
                "몬스터로 등록한 템플릿을 공격합니다. HP 바를 지정해야 안전하게 돕니다.")
            row = tk.Frame(card, bg=COLOR_CARD)
            row.pack(fill="x", padx=14, pady=(10, 4))
            self.combat_var = tk.BooleanVar(value=False)
            ttk.Checkbutton(
                row, text="사냥 모드 사용  (끄면 줍기만 합니다)",
                variable=self.combat_var).pack(side="left")

            row = tk.Frame(card, bg=COLOR_CARD)
            row.pack(fill="x", padx=14, pady=4)
            tk.Label(row, text="체력 바:",
                     font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left")
            self.hp_bar_label = tk.Label(
                row, text="지정 안 됨", font=("맑은 고딕", 9),
                bg=COLOR_CARD, fg=COLOR_WARN)
            self.hp_bar_label.pack(side="left", padx=(6, 8))
            HoverButton(row, bg="#00695C", hover_bg="#004D40", text="영역 지정",
                        font=("맑은 고딕", 9), padx=10, pady=2,
                        command=lambda: self._capture_bar("hp")).pack(side="left")

            tk.Label(row, text="   마나 바:",
                     font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left")
            self.mp_bar_label = tk.Label(
                row, text="지정 안 됨", font=("맑은 고딕", 9),
                bg=COLOR_CARD, fg=COLOR_SUBTEXT)
            self.mp_bar_label.pack(side="left", padx=(6, 8))
            HoverButton(row, bg="#455A64", hover_bg="#37474F", text="영역 지정",
                        font=("맑은 고딕", 9), padx=10, pady=2,
                        command=lambda: self._capture_bar("mp")).pack(side="left")

            # 공격 스킬 — 스킬키를 누른 뒤 대상을 클릭하는 순서로 나간다
            tk.Label(card, text="공격 스킬  (비우면 평타로 클릭만 합니다)",
                     font=("맑은 고딕", 9), bg=COLOR_CARD,
                     fg=COLOR_SUBTEXT).pack(anchor="w", padx=14, pady=(8, 2))
            self.skill_vars = []
            for i in range(3):
                srow = tk.Frame(card, bg=COLOR_CARD)
                srow.pack(fill="x", padx=14, pady=1)
                tk.Label(srow, text=f"  {i+1}.  키",
                         font=("맑은 고딕", 10), bg=COLOR_CARD,
                         width=6, anchor="w").pack(side="left")
                kv = tk.StringVar(value="")
                KeyCaptureEntry(srow, kv, mode="plain",
                                width=8, bg=COLOR_CARD).pack(side="left", padx=4)
                tk.Label(srow, text="  쿨다운",
                         font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left")
                cv = tk.StringVar(value="0")
                ttk.Entry(srow, textvariable=cv, width=5,
                          justify="right").pack(side="left", padx=4)
                tk.Label(srow, text="초",
                         font=("맑은 고딕", 9), bg=COLOR_CARD,
                         fg=COLOR_SUBTEXT).pack(side="left")
                self.skill_vars.append((kv, cv))

            row = tk.Frame(card, bg=COLOR_CARD)
            row.pack(fill="x", padx=14, pady=(8, 4))
            tk.Label(row, text="HP 물약 키:",
                     font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left")
            self.hp_key_var = tk.StringVar(value="1")
            KeyCaptureEntry(row, self.hp_key_var, mode="plain",
                            width=8, bg=COLOR_CARD).pack(side="left", padx=4)
            tk.Label(row, text="  HP",
                     font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left")
            self.hp_pct_var = tk.StringVar(value="50")
            ttk.Entry(row, textvariable=self.hp_pct_var,
                      width=5, justify="right").pack(side="left", padx=4)
            tk.Label(row, text="% 이하일 때 사용",
                     font=("맑은 고딕", 9), bg=COLOR_CARD,
                     fg=COLOR_SUBTEXT).pack(side="left")

            row = tk.Frame(card, bg=COLOR_CARD)
            row.pack(fill="x", padx=14, pady=4)
            tk.Label(row, text="MP 물약 키:",
                     font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left")
            self.mp_key_var = tk.StringVar(value="")
            KeyCaptureEntry(row, self.mp_key_var, mode="plain",
                            width=8, bg=COLOR_CARD).pack(side="left", padx=4)
            tk.Label(row, text="  MP",
                     font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left")
            self.mp_pct_var = tk.StringVar(value="30")
            ttk.Entry(row, textvariable=self.mp_pct_var,
                      width=5, justify="right").pack(side="left", padx=4)
            tk.Label(row, text="% 이하일 때 사용  (비우면 안 씀)",
                     font=("맑은 고딕", 9), bg=COLOR_CARD,
                     fg=COLOR_SUBTEXT).pack(side="left")

            row = tk.Frame(card, bg=COLOR_CARD)
            row.pack(fill="x", padx=14, pady=(4, 10))
            tk.Label(row, text="HP",
                     font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left")
            self.hp_halt_var = tk.StringVar(value="15")
            ttk.Entry(row, textvariable=self.hp_halt_var,
                      width=5, justify="right").pack(side="left", padx=4)
            tk.Label(row, text="% 이하로 떨어지면 매크로를 정지합니다 (0 = 끔)",
                     font=("맑은 고딕", 9), bg=COLOR_CARD,
                     fg=COLOR_SUBTEXT).pack(side="left")

        # ─ 안전 장치 ─
        card = self._settings_card(
            inner, "🛟  안전 장치",
            "단축키가 듣지 않을 때를 대비한 정지 경로입니다.")
        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=(10, 2))
        self.failsafe_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            row, text="커서를 화면 좌상단 모서리로 보내면 즉시 정지",
            variable=self.failsafe_var).pack(side="left")

        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=2)
        self.pause_user_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            row, text="내가 마우스를 만지면 잠시 멈춤 (몇 초 뒤 자동 재개)",
            variable=self.pause_user_var).pack(side="left")

        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=(2, 10))
        self.stop_gone_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            row, text="게임 창이 사라지면 정지",
            variable=self.stop_gone_var).pack(side="left")

        # ─ 자연스러운 동작 ─
        card = self._settings_card(
            inner, "🥷  자연스러운 동작",
            "타이밍 흔들림·반응 지연·작업휴식 사이클.")
        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=(10, 4))
        tk.Label(row, text="타이밍 변동(±):",
                 font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left")
        self.jitter_var = tk.StringVar(value="30")
        ttk.Entry(row, textvariable=self.jitter_var,
                  width=6, justify="right").pack(side="left", padx=4)
        tk.Label(row, text="%    (권장 20~40)",
                 font=("맑은 고딕", 9), bg=COLOR_CARD,
                 fg=COLOR_SUBTEXT).pack(side="left")

        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=(2, 10))
        tk.Label(row, text="반응 지연 확률:",
                 font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left")
        self.hesitate_var = tk.StringVar(value="8")
        ttk.Entry(row, textvariable=self.hesitate_var,
                  width=6, justify="right").pack(side="left", padx=4)
        tk.Label(row, text="%    (이 확률로 0.2~0.7초 늦게 반응)",
                 font=("맑은 고딕", 9), bg=COLOR_CARD,
                 fg=COLOR_SUBTEXT).pack(side="left")

        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=(4, 4))
        self.rest_enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            row, text="작업·휴식 사이클 사용",
            variable=self.rest_enabled_var,
        ).pack(side="left")

        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=(2, 10))
        tk.Label(row, text="작업 구간:",
                 font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left")
        self.work_min_var = tk.StringVar(value="25")
        ttk.Entry(row, textvariable=self.work_min_var,
                  width=5, justify="right").pack(side="left", padx=(4, 2))
        tk.Label(row, text="~", font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left")
        self.work_max_var = tk.StringVar(value="50")
        ttk.Entry(row, textvariable=self.work_max_var,
                  width=5, justify="right").pack(side="left", padx=(2, 4))
        tk.Label(row, text="분",
                 font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left", padx=(0, 20))

        tk.Label(row, text="휴식 구간:",
                 font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left")
        self.rest_min_var = tk.StringVar(value="4")
        ttk.Entry(row, textvariable=self.rest_min_var,
                  width=5, justify="right").pack(side="left", padx=(4, 2))
        tk.Label(row, text="~", font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left")
        self.rest_max_var = tk.StringVar(value="12")
        ttk.Entry(row, textvariable=self.rest_max_var,
                  width=5, justify="right").pack(side="left", padx=(2, 4))
        tk.Label(row, text="분",
                 font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left")

        # ─ 단축키 ─
        card = self._settings_card(
            inner, "⌨  전역 단축키",
            "칸을 클릭하고 원하는 키를 누르면 그대로 들어갑니다.")
        row = tk.Frame(card, bg=COLOR_CARD)
        row.pack(fill="x", padx=14, pady=(10, 10))
        tk.Label(row, text="시작/정지:",
                 font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left")
        self.hotkey_toggle_var = tk.StringVar(value="<home>")
        KeyCaptureEntry(row, self.hotkey_toggle_var, mode="hotkey",
                        width=18, bg=COLOR_CARD).pack(side="left", padx=(6, 20))
        tk.Label(row, text="비상 정지:",
                 font=("맑은 고딕", 10), bg=COLOR_CARD).pack(side="left")
        self.hotkey_stop_var = tk.StringVar(value="<f12>")
        KeyCaptureEntry(row, self.hotkey_stop_var, mode="hotkey",
                        width=18, bg=COLOR_CARD).pack(side="left", padx=6)

        save_wrap = tk.Frame(inner, bg=COLOR_BG)
        save_wrap.pack(fill="x", padx=14, pady=(14, 20))
        HoverButton(
            save_wrap, bg=COLOR_ACCENT, hover_bg=COLOR_ACCENT2,
            text="💾  설정 저장 및 적용",
            font=("맑은 고딕", 11, "bold"),
            padx=26, pady=8, command=self._save_settings_from_ui,
        ).pack(side="right")

    def _settings_card(self, parent, title, desc):
        outer = tk.Frame(parent, bg=COLOR_BG)
        outer.pack(fill="x", padx=14, pady=(14, 0))
        head = tk.Frame(outer, bg=COLOR_BG)
        head.pack(fill="x", padx=2)
        tk.Label(head, text=title, font=("맑은 고딕", 11, "bold"),
                 bg=COLOR_BG, fg=COLOR_TEXT, anchor="w").pack(side="left")
        if desc:
            tk.Label(head, text=f"   {desc}",
                     font=("맑은 고딕", 9),
                     bg=COLOR_BG, fg=COLOR_SUBTEXT,
                     anchor="w").pack(side="left")
        card = tk.Frame(
            outer, bg=COLOR_CARD,
            highlightbackground=COLOR_BORDER, highlightthickness=1)
        card.pack(fill="x", pady=(4, 0))
        return card

    # -------------------------------------------------
    # Settings sync
    # -------------------------------------------------
    def _sync_settings_to_ui(self):
        c = self.config_data
        self.window_title_var.set(c.get("window_title", ""))
        self.window_proc_var.set(c.get("window_process", "Trickster.bin"))
        self.window_lock_var.set(bool(c.get("window_lock", True)))
        self.click_interval_var.set(str(c.get("click_interval_ms", 1000)))
        self.key_interval_var.set(str(c.get("key_interval_ms", 200)))
        self.pickup_key_var.set(c.get("pickup_key", "z"))
        self.hotkey_toggle_var.set(c.get("hotkey_toggle", "<home>"))
        self.hotkey_stop_var.set(c.get("hotkey_stop", "<f12>"))
        self.jitter_var.set(str(int(c.get("jitter_percent", 30))))
        self.hesitate_var.set(
            str(int(round(float(c.get("hesitate_probability", 0.08)) * 100))))
        self.rest_enabled_var.set(bool(c.get("rest_cycle_enabled", True)))
        self.work_min_var.set(str(c.get("work_min_minutes", 25)))
        self.work_max_var.set(str(c.get("work_max_minutes", 50)))
        self.rest_min_var.set(str(c.get("rest_min_minutes", 4)))
        self.rest_max_var.set(str(c.get("rest_max_minutes", 12)))
        self.scan_interval_var.set(str(c.get("scan_interval_ms", 250)))
        self.scan_radius_var.set(str(c.get("scan_radius_px", 0)))
        # 사냥 설정은 사냥 프로그램에만 위젯이 있다.
        # 안전 설정은 두 프로그램 공통이므로 이 블록 밖에 둔다.
        if HUNT_MODE:
            self.combat_var.set(bool(c.get("combat_enabled", False)))
            skills = c.get("attack_skills") or []
            for i, (kv, cv) in enumerate(self.skill_vars):
                if i < len(skills) and isinstance(skills[i], dict):
                    kv.set(str(skills[i].get("key", "")))
                    cv.set(str(skills[i].get("cooldown", 0)))
                else:
                    kv.set("")
                    cv.set("0")
            self.hp_key_var.set(str(c.get("hp_potion_key", "1")))
            self.hp_pct_var.set(str(c.get("hp_potion_percent", 50)))
            self.mp_key_var.set(str(c.get("mp_potion_key", "")))
            self.mp_pct_var.set(str(c.get("mp_potion_percent", 30)))
            self.hp_halt_var.set(str(c.get("hp_halt_percent", 15)))
            self._sync_bar_labels()
        self.failsafe_var.set(bool(c.get("failsafe_corner", True)))
        self.pause_user_var.set(bool(c.get("pause_on_user_input", True)))
        self.stop_gone_var.set(bool(c.get("stop_when_window_gone", True)))
        self.mouse_move_ms_var.set(str(c.get("mouse_move_ms", 120)))
        self.pre_move_delay_var.set(str(c.get("pre_move_delay_ms", 20)))
        self.default_threshold_var.set(str(c.get("default_threshold", 0.85)))
        self._update_hotkey_hint()

    def _save_settings_from_ui(self, silent=False):
        try:
            c = self.config_data
            c["window_title"] = self.window_title_var.get().strip()
            c["window_process"] = self.window_proc_var.get().strip()
            c["window_lock"]  = bool(self.window_lock_var.get())
            try:
                c["click_interval_ms"] = max(50,
                    int(self.click_interval_var.get() or "1000"))
            except ValueError:
                raise ValueError("클릭 주기: 정수(ms)")
            try:
                c["key_interval_ms"] = max(50,
                    int(self.key_interval_var.get() or "200"))
            except ValueError:
                raise ValueError("키 입력 주기: 정수(ms)")
            c["pickup_key"] = (self.pickup_key_var.get() or "z").strip().lower()
            c["hotkey_toggle"] = (self.hotkey_toggle_var.get() or "<f1>").strip()
            c["hotkey_stop"]   = (self.hotkey_stop_var.get() or "<f12>").strip()
            try:
                c["jitter_percent"] = max(0, min(95,
                    int(self.jitter_var.get() or "0")))
            except ValueError:
                raise ValueError("타이밍 변동: 정수(%)")
            try:
                hp = int(self.hesitate_var.get() or "0")
                c["hesitate_probability"] = max(0.0, min(1.0, hp / 100.0))
            except ValueError:
                raise ValueError("반응 지연 확률: 정수(%)")
            c["rest_cycle_enabled"] = bool(self.rest_enabled_var.get())
            try:
                wmin = float(self.work_min_var.get() or "25")
                wmax = float(self.work_max_var.get() or "50")
                rmin = float(self.rest_min_var.get() or "4")
                rmax = float(self.rest_max_var.get() or "12")
            except ValueError:
                raise ValueError("작업/휴식 구간: 숫자(분)")
            if wmin <= 0 or rmin <= 0:
                raise ValueError("작업/휴식 구간: 0보다 큰 값")
            if wmin > wmax: wmin, wmax = wmax, wmin
            if rmin > rmax: rmin, rmax = rmax, rmin
            c["work_min_minutes"] = wmin
            c["work_max_minutes"] = wmax
            c["rest_min_minutes"] = rmin
            c["rest_max_minutes"] = rmax
            try:
                c["scan_interval_ms"] = max(50, int(self.scan_interval_var.get() or "250"))
                c["scan_radius_px"] = max(0, int(self.scan_radius_var.get() or "0"))
            except ValueError:
                raise ValueError("스캔 주기/반경: 정수")
            if HUNT_MODE:
                c["combat_enabled"] = bool(self.combat_var.get())
                skills = []
                for kv, cv in self.skill_vars:
                    k = kv.get().strip()
                    if not k:
                        continue
                    try:
                        cd = max(0.0, float(cv.get() or "0"))
                    except ValueError:
                        cd = 0.0
                    skills.append({"key": k, "cooldown": cd})
                c["attack_skills"] = skills
                c["hp_potion_key"] = self.hp_key_var.get().strip()
                c["mp_potion_key"] = self.mp_key_var.get().strip()
                try:
                    c["hp_potion_percent"] = max(0, min(100, int(self.hp_pct_var.get() or "50")))
                    c["mp_potion_percent"] = max(0, min(100, int(self.mp_pct_var.get() or "30")))
                    c["hp_halt_percent"]   = max(0, min(100, int(self.hp_halt_var.get() or "0")))
                except ValueError:
                    raise ValueError("물약/정지 임계값: 정수(%)")
            c["failsafe_corner"] = bool(self.failsafe_var.get())
            c["pause_on_user_input"] = bool(self.pause_user_var.get())
            c["stop_when_window_gone"] = bool(self.stop_gone_var.get())
        except ValueError as e:
            messagebox.showerror("입력 오류", str(e))
            return

        self._save_config()
        self.engine.set_config(self.config_data)
        self._update_hotkey_listener()
        self._refresh_summary()
        self._log_ui("✓  설정 저장 및 적용", "ok")
        if not silent:
            messagebox.showinfo("저장 완료", "설정이 저장되었습니다.")

    def _refresh_summary(self):
        """지금 설정이 어떻게 동작하는지 한 줄로.

        v4 에서 스캔과 클릭이 다른 스레드로 갈라졌으므로
        예전처럼 '좌클릭/스캔 5.00초' 로 묶어 적으면 거짓말이 된다.
        """
        c = self.config_data
        tpl_count = len([t for t in c.get("templates", [])
                         if t.get("enabled", True)])
        mode = f"템플릿 {tpl_count}개" if tpl_count else "고정 위치"
        parts = [f"모드: {mode}"]
        if tpl_count:
            parts.append(f"스캔 {c.get('scan_interval_ms', 250)}ms")
        parts.append(f"클릭 {c.get('click_interval_ms', 1200)/1000:.2f}초")
        parts.append(f"키 '{str(c.get('pickup_key', 'z')).upper()}' "
                     f"{c.get('key_interval_ms', 200)/1000:.2f}초")
        self.summary_label.config(text="   ·   ".join(parts))

    # -------------------------------------------------
    # 지표 · 준비 상태 (v4)
    # -------------------------------------------------
    def _start_metric_timer(self):
        self._tick_metrics()

    def _tick_metrics(self):
        try:
            self._refresh_metrics()
        except Exception:
            pass
        self.root.after(700, self._tick_metrics)

    def _refresh_metrics(self):
        eng = self.engine
        running = eng.is_running()

        # 지표 타일
        if running:
            st = eng.stats
            tr = eng.tracker
            self.metric_vars["picked"].set(str(st.picked))
            self.metric_vars["rate"].set(
                f"{st.picks_per_hour:.0f}" if st.picked else "—")
            self.metric_vars["clicks"].set(str(st.clicks))
            self.metric_vars["scan"].set(
                f"{st.scan_avg_ms:.0f}ms" if st.scans else "—")
            self.metric_vars["hit"].set(
                f"{st.hit_rate*100:.0f}%" if st.scans else "—")
            active = sum(1 for t in tr.tracks if not t.is_blocked())
            self.metric_vars["track"].set(str(active))

        # 준비 / 진행 상태 — 왜 지금 이런 상태인가를 말해준다
        bits = []
        try:
            title = eng.window.title()
        except Exception:
            title = ""
        lock = self.config_data.get("window_lock", True)
        want = (self.config_data.get("window_title") or "").strip()
        if not lock:
            bits.append("창 필터 꺼짐")
        elif title:
            bits.append(f"게임 창: {title[:28]}")
        else:
            bits.append(f"게임 창 '{want}' 못 찾음")

        # 사냥 중이면 HP/MP 를 상태 줄에 — 이걸 못 보면 물약이 도는지 알 수 없다
        snap = eng.snapshot()
        if snap is not None and snap.player is not None:
            p = snap.player
            if p.hp_ratio is not None:
                bits.append(f"HP {p.hp_ratio*100:.0f}%")
            if p.mp_ratio is not None:
                bits.append(f"MP {p.mp_ratio*100:.0f}%")
        elif self.config_data.get("combat_enabled") and not self.config_data.get("hp_bar"):
            bits.append("⚠ 체력 바 미지정")

        if running:
            reason = eng.pause_reason()
            phase, remain = eng.phase_remaining()
            if reason:
                bits.append(f"⏸ {reason}")
            elif phase == "rest" and remain:
                bits.append(f"휴식 중 — {remain/60:.1f}분 남음")
            elif remain:
                bits.append(f"작업 중 — 휴식까지 {remain/60:.1f}분")
            self._paint_status(reason, phase)
        else:
            n = eng.backend.template_count()
            bits.append(f"템플릿 {n}개" if n else "템플릿 없음 (고정 위치 모드)")

        self.ready_label.config(text="   ·   ".join(bits))

    def _paint_status(self, reason, phase):
        """실행 중에도 상태는 세 가지다 — 동작 / 일시정지 / 휴식.

        예전에는 '실행 중' 하나뿐이라, 사용자 개입이나 창 비활성으로
        멈췄는데도 화면은 '실행 중' 이라고 말했다.
        """
        if reason:
            bg, txt = "#8A5B00", "⏸  일시정지"
        elif phase == "rest":
            bg, txt = "#4A5568", "💤  휴식 중"
        else:
            bg, txt = COLOR_OK, "●  실행 중"
        self.status_banner.config(bg=bg)
        self.status_label.config(bg=bg, text=txt)
        self.hotkey_hint.config(bg=bg)

    # -------------------------------------------------
    # 실행 / 상태 / 로그
    # -------------------------------------------------
    def _on_toggle_clicked(self):
        if self.engine.is_running():
            self.engine.stop()
        else:
            self.engine.start()

    def _on_engine_log_threadsafe(self, msg: str):
        self.root.after(0, lambda: self._log_ui(msg))

    def _on_engine_status_threadsafe(self, running: bool):
        self.root.after(0, lambda: self._update_status_ui(running))

    def _on_engine_phase_threadsafe(self, phase: str, minutes):
        self.root.after(0, lambda: self._update_phase_ui(phase, minutes))

    def _update_phase_ui(self, phase: str, minutes):
        if phase == "rest":
            bg   = "#455A64"
            text = f"💤  휴식 중  ({minutes:.1f}분)"
        else:
            bg   = COLOR_OK
            text = ("●  실행 중" if minutes is None
                    else f"●  실행 중  (작업 {minutes:.1f}분)")
        self.status_banner.config(bg=bg)
        self.status_label.config(bg=bg, text=text)
        self.hotkey_hint.config(bg=bg)

    def _update_status_ui(self, running: bool):
        if running:
            # 세부 상태(일시정지/휴식)는 _paint_status 가 매 초 갱신한다
            if hasattr(self, "metric_vars"):
                for k in ("picked", "clicks"):
                    self.metric_vars[k].set("0")
            self.status_banner.config(bg=COLOR_OK)
            self.status_label.config(bg=COLOR_OK, text="●  실행 중")
            self.hotkey_hint.config(bg=COLOR_OK)
            self.toggle_btn.config(bg=COLOR_WARN, text="■   정지",
                                   activebackground="#8B0000")
            self.toggle_btn._bg    = COLOR_WARN
            self.toggle_btn._hover = "#8B0000"
        else:
            self.status_banner.config(bg=COLOR_OFF)
            self.status_label.config(bg=COLOR_OFF, text="■  정지됨")
            # 정지하면 지표를 비운다. 0 으로 남겨두면 지난 세션 값처럼 보인다.
            if hasattr(self, "metric_vars"):
                for k in self.metric_vars:
                    self.metric_vars[k].set("—")
            self.hotkey_hint.config(bg=COLOR_OFF)
            self.toggle_btn.config(bg=COLOR_OK, text="▶   시작",
                                   activebackground="#2E7D32")
            self.toggle_btn._bg    = COLOR_OK
            self.toggle_btn._hover = "#2E7D32"

    def _log_ui(self, msg: str, tag: str = None):
        now = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{now}] ", ("time",))
        if tag:
            self.log_text.insert("end", msg + "\n", (tag,))
        else:
            auto = None
            if "⚠" in msg or "오류" in msg or "실패" in msg:
                auto = "warn"
            elif "⌛" in msg:
                auto = "accent"
            elif "✓" in msg or "▶" in msg:
                auto = "ok"
            self.log_text.insert("end", msg + "\n", (auto,) if auto else ())
        self.log_text.see("end")
        line_count = int(self.log_text.index("end-1c").split(".")[0])
        if line_count > 500:
            self.log_text.delete("1.0", f"{line_count-400}.0")

    # -------------------------------------------------
    # 프로필 (P1.9)
    # -------------------------------------------------
    def _refresh_profiles(self, select=None):
        names = self._profiles.list()
        self.profile_combo["values"] = names
        if select and select in names:
            self.profile_var.set(select)
        elif names and not self.profile_var.get():
            self.profile_var.set(names[0])

    def _profile_save(self):
        from tkinter import simpledialog
        cur = self.profile_var.get().strip()
        name = simpledialog.askstring(
            "프로필 저장", "프로필 이름:", initialvalue=cur, parent=self.root)
        if not name:
            return
        # 화면에 입력된 값을 먼저 설정에 반영한 뒤 저장한다
        self._save_settings_from_ui(silent=True)
        try:
            saved = self._profiles.save(name, self.config_data)
        except Exception as e:
            messagebox.showerror("저장 실패", str(e))
            return
        self._refresh_profiles(select=saved)
        self._log_ui(f"🗂  프로필 저장: {saved}", "ok")

    def _profile_load(self):
        name = self.profile_var.get().strip()
        if not name:
            messagebox.showinfo("프로필", "불러올 프로필을 고르세요.")
            return
        n = self._profiles.apply(name, self.config_data)
        if n == 0:
            messagebox.showerror("불러오기 실패", f"'{name}' 을 읽지 못했습니다.")
            return
        self._save_config()
        self.engine.set_config(self.config_data)
        self.engine.load_templates(DATA_DIR, self.config_data.get("templates", []))
        self._sync_settings_to_ui()
        self._reload_template_list()
        self._refresh_summary()
        self._log_ui(f"🗂  프로필 적용: {name} ({n}개 설정)", "ok")

    def _profile_delete(self):
        name = self.profile_var.get().strip()
        if not name:
            return
        if not messagebox.askyesno("프로필 삭제", f"'{name}' 을 삭제할까요?"):
            return
        self._profiles.delete(name)
        self.profile_var.set("")
        self._refresh_profiles()
        self._log_ui(f"🗂  프로필 삭제: {name}")

    def _toggle_overlay(self):
        """검출 박스 오버레이를 켜고 끈다."""
        try:
            self._overlay.toggle()
        except Exception as e:
            self._log_ui(f"⚠  오버레이 오류: {e}")
            return
        on = self._overlay.is_open()
        self.overlay_btn.config(text="🔎 오버레이 끄기" if on else "🔎 오버레이")
        self._log_ui("🔎  오버레이 " + ("켬 — 검출 박스와 점수를 화면에 표시합니다."
                                        if on else "끔"))

    def _clear_log(self):
        self.log_text.delete("1.0", "end")

    # -------------------------------------------------
    # 전역 단축키
    # -------------------------------------------------
    def _update_hotkey_listener(self):
        if self._hotkey_listener is not None:
            try: self._hotkey_listener.stop()
            except Exception: pass
            self._hotkey_listener = None

        if not HAS_HOTKEYS:
            self._update_hotkey_hint(warn="pynput GlobalHotKeys 미사용")
            return

        toggle_key = self.config_data.get("hotkey_toggle", "<f1>")
        stop_key   = self.config_data.get("hotkey_stop", "<f12>")

        def on_toggle():
            self.root.after(0, self._on_toggle_clicked)

        def on_stop():
            self.root.after(0, self.engine.stop)

        try:
            listener = GlobalHotKeys({toggle_key: on_toggle, stop_key: on_stop})
            listener.start()
            self._hotkey_listener = listener
        except Exception as e:
            self._log_ui(f"⚠  단축키 등록 실패 — {e}", "warn")
        self._update_hotkey_hint()

    def _update_hotkey_hint(self, warn=None):
        if warn:
            self.hotkey_hint.config(text=f"({warn})")
            return
        t = self.config_data.get("hotkey_toggle", "<f1>")
        s = self.config_data.get("hotkey_stop", "<f12>")
        self.hotkey_hint.config(text=f"시작/정지 {t}    ·    비상 정지 {s}")

    # -------------------------------------------------
    # 종료
    # -------------------------------------------------
    def _on_close(self):
        try: self._overlay.close()
        except Exception: pass
        # shutdown 은 정지에 더해 캡처 핸들과 로그 파일까지 닫는다
        try: self.engine.shutdown()
        except Exception:
            try: self.engine.stop()
            except Exception: pass
        if self._hotkey_listener is not None:
            try: self._hotkey_listener.stop()
            except Exception: pass
        self.root.destroy()


# -----------------------------------------------------------
# Entry
# -----------------------------------------------------------
def main():
    root = tk.Tk()
    MacroApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
