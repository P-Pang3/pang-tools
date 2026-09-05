# -*- coding: utf-8 -*-
"""
게임 창 추적 — 좌표계의 기준점 (P1.1).

모든 좌표를 창 클라이언트 영역 기준으로 다루기 위한 토대다. 창을 옮기거나
크기를 바꿔도 템플릿과 설정이 그대로 유효해진다.

pygetwindow 는 제목으로 창을 찾아주지만 클라이언트 영역(테두리·제목표시줄을
뺀 실제 그리기 영역)은 알려주지 않는다. 캡처는 클라이언트 영역만 잡아야
제목표시줄이 템플릿 매칭을 오염시키지 않으므로 Win32 API 를 직접 쓴다.
"""
import ctypes
import ctypes.wintypes as wt
import sys
import time

_IS_WIN = sys.platform == "win32"

if _IS_WIN:
    _u32 = ctypes.windll.user32
    _k32 = ctypes.windll.kernel32


class RECT(ctypes.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG),
                ("right", wt.LONG), ("bottom", wt.LONG)]


class POINT(ctypes.Structure):
    _fields_ = [("x", wt.LONG), ("y", wt.LONG)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", RECT),
                ("rcWork", RECT), ("dwFlags", wt.DWORD)]


_ENUM_PROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


class GameWindow:
    """제목으로 게임 창을 찾아 클라이언트 영역과 소속 모니터를 추적한다.

    창 핸들을 캐시하되 유효성을 매번 확인한다. 게임을 껐다 켜면 핸들이 바뀌므로
    캐시만 믿으면 사라진 창을 계속 가리키게 된다.
    """

    def __init__(self, title_filter: str = "", process_filter: str = ""):
        self.title_filter = (title_filter or "").strip().lower()
        # 제목만으로는 엉뚱한 창이 걸린다. 실제로 필터 'Trickster' 에
        # 'trickster_macro - 파일 탐색기' 가 매칭돼 탐색기에 입력이 갈 뻔했다.
        self.process_filter = (process_filter or "").strip().lower()
        self._hwnd = 0
        self._last_find = 0.0
        self._find_interval = 1.0   # 창을 다시 찾는 최소 간격(초)

    # ---------------- 창 찾기 ----------------
    def set_filter(self, title_filter: str, process_filter: str = None):
        tf = (title_filter or "").strip().lower()
        changed = tf != self.title_filter
        self.title_filter = tf
        if process_filter is not None:
            pf = (process_filter or "").strip().lower()
            changed = changed or pf != self.process_filter
            self.process_filter = pf
        if changed:
            self._hwnd = 0          # 필터가 바뀌면 캐시 폐기

    def _title_of(self, hwnd) -> str:
        n = _u32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(n + 1)
        _u32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def _exe_of(self, hwnd) -> str:
        """창을 소유한 프로세스의 실행 파일 이름 (소문자). 못 얻으면 빈 문자열."""
        try:
            pid = wt.DWORD()
            _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                return ""
            PROCESS_QUERY_LIMITED = 0x1000
            hp = _k32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid.value)
            if not hp:
                return ""
            try:
                size = wt.DWORD(260)
                buf = ctypes.create_unicode_buffer(size.value)
                if _k32.QueryFullProcessImageNameW(
                        hp, 0, buf, ctypes.byref(size)):
                    return buf.value.rsplit("\\", 1)[-1].lower()
            finally:
                _k32.CloseHandle(hp)
        except Exception:
            pass
        return ""

    def _is_valid(self, hwnd) -> bool:
        if not hwnd or not _u32.IsWindow(hwnd):
            return False
        if not _u32.IsWindowVisible(hwnd):
            return False
        if self.title_filter:
            if self.title_filter not in self._title_of(hwnd).lower():
                return False
        # 제목이 맞아도 프로세스가 다르면 남의 창이다.
        # 'Trickster' 필터에 'trickster_macro - 파일 탐색기' 가 걸리던 문제.
        if self.process_filter:
            exe = self._exe_of(hwnd)
            if exe and self.process_filter not in exe:
                return False
        return bool(self.title_filter or self.process_filter)

    def hwnd(self, force: bool = False):
        """게임 창 핸들. 없으면 0."""
        if not _IS_WIN:
            return 0
        if self._is_valid(self._hwnd) and not force:
            return self._hwnd

        now = time.monotonic()
        if not force and (now - self._last_find) < self._find_interval:
            return 0            # 방금 찾아봤는데 없었다 — 매 프레임 훑지 않는다
        self._last_find = now

        found = []

        def _cb(h, _lp):
            if self._is_valid(h):
                found.append(h)
                return False    # 첫 번째로 끝낸다
            return True

        try:
            _u32.EnumWindows(_ENUM_PROC(_cb), 0)
        except Exception:
            return 0

        self._hwnd = found[0] if found else 0
        return self._hwnd

    def exists(self) -> bool:
        return self.hwnd() != 0

    def title(self) -> str:
        """창 제목. 공백과 개행을 정리해서 준다.

        이 게임은 창 제목 끝에 개행을 붙인다. 그대로 라벨에 넣으면 두 줄이
        되어 UI 가 깨진다 — 실제로 상태 줄이 접히는 원인이었다.
        """
        h = self.hwnd()
        if not h:
            return ""
        return " ".join(self._title_of(h).split())

    def is_foreground(self) -> bool:
        """게임 창이 활성 상태인가. 자식 창(대화상자)에 포커스가 있어도 참."""
        if not _IS_WIN:
            return True
        h = self.hwnd()
        if not h:
            return False
        fg = _u32.GetForegroundWindow()
        if fg == h:
            return True
        # 게임이 띄운 모달 대화상자가 포커스를 가진 경우까지 활성으로 본다
        try:
            root = _u32.GetAncestor(fg, 2)   # GA_ROOT
            return root == h
        except Exception:
            return False

    # ---------------- 영역 ----------------
    def client_rect(self):
        """클라이언트 영역의 화면 절대 좌표 (left, top, width, height). 없으면 None.

        GetClientRect 는 (0,0,w,h) 를 주므로 ClientToScreen 으로 원점을 화면
        좌표로 옮긴다. GetWindowRect 를 쓰면 테두리와 제목표시줄이 섞여
        템플릿 좌표가 창 스타일에 따라 달라진다.
        """
        h = self.hwnd()
        if not h:
            return None
        r = RECT()
        if not _u32.GetClientRect(h, ctypes.byref(r)):
            return None
        w, ht = r.right - r.left, r.bottom - r.top
        if w <= 0 or ht <= 0:
            return None            # 최소화된 창
        p = POINT(0, 0)
        if not _u32.ClientToScreen(h, ctypes.byref(p)):
            return None
        return (p.x, p.y, w, ht)

    def monitor_rect(self):
        """창이 올라가 있는 모니터의 화면 영역. 창이 없으면 주 모니터.

        주 모니터를 고정으로 쓰면 게임이 보조 모니터에 있을 때 무조건 실패한다
        (진단 D-12). 창을 기준으로 매번 찾는다.
        """
        if not _IS_WIN:
            return None
        h = self.hwnd()
        try:
            if h:
                hmon = _u32.MonitorFromWindow(h, 2)      # NEAREST
            else:
                hmon = _u32.MonitorFromPoint(POINT(0, 0), 1)  # PRIMARY
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if _u32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                m = mi.rcMonitor
                return (m.left, m.top, m.right - m.left, m.bottom - m.top)
        except Exception:
            pass
        return None

    def capture_rect(self):
        """캡처 대상 영역. 클라이언트 영역을 우선하고, 없으면 모니터 전체."""
        return self.client_rect() or self.monitor_rect()

    # ---------------- 좌표 변환 ----------------
    def to_client(self, sx, sy):
        """화면 절대 → 클라이언트 상대. 창이 없으면 그대로 돌려준다."""
        cr = self.client_rect()
        if not cr:
            return (sx, sy)
        return (sx - cr[0], sy - cr[1])

    def to_screen(self, cx, cy):
        """클라이언트 상대 → 화면 절대."""
        cr = self.client_rect()
        if not cr:
            return (cx, cy)
        return (cx + cr[0], cy + cr[1])

    def process_alive(self) -> bool:
        """창이 속한 프로세스가 살아 있는가.

        창이 사라지는 것과 프로세스가 죽는 것은 다르다. 로딩 중 창을 다시
        만드는 게임도 있어서, 프로세스가 살아 있으면 잠깐 기다려볼 수 있다.
        """
        if not _IS_WIN:
            return True
        h = self.hwnd()
        if not h:
            return False
        pid = wt.DWORD()
        _u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if not pid.value:
            return False
        PROCESS_QUERY_LIMITED = 0x1000
        hp = _k32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid.value)
        if not hp:
            return False
        try:
            code = wt.DWORD()
            if _k32.GetExitCodeProcess(hp, ctypes.byref(code)):
                return code.value == 259      # STILL_ACTIVE
            return False
        finally:
            _k32.CloseHandle(hp)
