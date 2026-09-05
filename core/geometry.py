# -*- coding: utf-8 -*-
"""
좌표계 — DPI 인식 선언과 창 기준 상대 좌표 변환.

이 프로그램은 세 개의 좌표계를 오간다.

  1. 화면 절대 (물리 픽셀)  — mss 캡처, pynput 입력이 쓰는 좌표
  2. 창 클라이언트 상대     — 템플릿·설정이 저장되는 좌표
  3. 캡처 프레임 상대       — ROI로 잘라낸 이미지 안의 좌표

DPI 인식을 선언하지 않으면 1번이 두 갈래로 갈라진다. Windows가 mss에는 물리
픽셀을, pynput에는 논리 픽셀을 주기 때문이다. 배율 125%에서 (1000, 500)을
캡처해 그 자리를 클릭하면 실제로는 (800, 400)이 눌린다. 선언은 프로세스당
한 번, 창을 만들기 전에 해야 한다.
"""
import ctypes
import sys

# 선언 결과 — 시작 로그에서 읽는다
DPI_MODE = "미적용"
DPI_OK = False


def declare_dpi_aware() -> str:
    """DPI 인식을 선언한다. 프로세스 시작 시 한 번, 창 생성 전에 호출.

    최신 API부터 시도하고 실패하면 구형으로 내려간다. 반환값은 어떤 방식이
    적용됐는지 나타내는 문자열이며 로그에 그대로 쓴다.
    """
    global DPI_MODE, DPI_OK

    if sys.platform != "win32":
        DPI_MODE = "해당 없음 (Windows 아님)"
        return DPI_MODE

    # 1순위: Per-Monitor V2 (Windows 10 1703+)
    #   모니터마다 배율이 다른 환경까지 정확히 처리한다.
    try:
        ctx = ctypes.c_void_p(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctx):
            DPI_MODE = "Per-Monitor V2"
            DPI_OK = True
            return DPI_MODE
    except (AttributeError, OSError):
        pass

    # 2순위: Per-Monitor (Windows 8.1+)
    try:
        # 0=Unaware, 1=System, 2=Per-Monitor
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            DPI_MODE = "Per-Monitor"
            DPI_OK = True
            return DPI_MODE
    except (AttributeError, OSError):
        pass

    # 3순위: System DPI (Vista+)
    #   모니터별 배율은 못 따라가지만 단일 모니터에서는 충분하다.
    try:
        if ctypes.windll.user32.SetProcessDPIAware():
            DPI_MODE = "System"
            DPI_OK = True
            return DPI_MODE
    except (AttributeError, OSError):
        pass

    DPI_MODE = "선언 실패"
    return DPI_MODE


def dpi_warning() -> str:
    """DPI 선언이 안 됐을 때 로그에 남길 경고. 정상이면 빈 문자열."""
    if DPI_OK:
        return ""
    if DPI_MODE == "해당 없음 (Windows 아님)":
        return ""
    return (
        f"⚠  DPI 인식 선언 실패 ({DPI_MODE}) — 화면 배율이 100%가 아니면 "
        f"클릭 좌표가 어긋납니다. 디스플레이 설정에서 배율을 100%로 맞추세요."
    )


# ---------------------------------------------------------------
# 타이머 해상도
# ---------------------------------------------------------------
_TIMER_RAISED = False


def raise_timer_resolution(ms: int = 1) -> bool:
    """윈도우 타이머 해상도를 올린다.

    기본 해상도는 15.6ms 라서 Event.wait(0.06) 이 60ms 가 아니라 62~78ms 로
    깨어난다. 줍기 키를 60ms 주기로 누르려는데 오차가 30% 나는 셈이다.
    timeBeginPeriod(1) 로 1ms 단위가 된다.

    프로세스 전역 설정이라 종료 시 되돌려야 한다 (restore_timer_resolution).
    """
    global _TIMER_RAISED
    if _TIMER_RAISED or sys.platform != "win32":
        return _TIMER_RAISED
    try:
        if ctypes.windll.winmm.timeBeginPeriod(ms) == 0:   # TIMERR_NOERROR
            _TIMER_RAISED = True
    except (AttributeError, OSError):
        pass
    return _TIMER_RAISED


def restore_timer_resolution(ms: int = 1):
    global _TIMER_RAISED
    if not _TIMER_RAISED:
        return
    try:
        ctypes.windll.winmm.timeEndPeriod(ms)
    except (AttributeError, OSError):
        pass
    _TIMER_RAISED = False


# ---------------------------------------------------------------
# 좌표 변환
# ---------------------------------------------------------------
class Frame:
    """캡처한 한 장의 프레임이 화면 어디를 담고 있는지.

    검출 결과는 프레임 안의 좌표로 나온다. 그걸 클릭하려면 화면 절대 좌표로
    돌려놔야 하는데, 그 환산에 필요한 정보를 프레임과 함께 들고 다닌다.
    분리해서 넘기면 어긋나기 딱 좋은 종류의 값이다.
    """

    __slots__ = ("left", "top", "width", "height", "scale")

    def __init__(self, left: int, top: int, width: int, height: int,
                 scale: float = 1.0):
        self.left = left
        self.top = top
        self.width = width
        self.height = height
        # 축소 캡처/피라미드 스캔에서 원본 대비 배율. 0.5면 절반 크기.
        self.scale = scale

    def to_screen(self, fx: float, fy: float) -> tuple:
        """프레임 안 좌표 → 화면 절대 좌표."""
        return (
            int(round(self.left + fx / self.scale)),
            int(round(self.top + fy / self.scale)),
        )

    def to_frame(self, sx: float, sy: float) -> tuple:
        """화면 절대 좌표 → 프레임 안 좌표."""
        return (
            int(round((sx - self.left) * self.scale)),
            int(round((sy - self.top) * self.scale)),
        )

    def contains_screen(self, sx: float, sy: float) -> bool:
        return (self.left <= sx < self.left + self.width and
                self.top <= sy < self.top + self.height)

    def as_monitor(self) -> dict:
        """mss가 받는 형식."""
        return {"left": self.left, "top": self.top,
                "width": self.width, "height": self.height}

    def __repr__(self):
        return (f"Frame({self.left},{self.top} {self.width}x{self.height} "
                f"@{self.scale:g})")


def clamp_rect(left, top, width, height, bounds) -> tuple:
    """사각형을 경계 안으로 밀어넣는다. bounds는 (l, t, w, h).

    ROI를 캐릭터 중심으로 잡으면 화면 가장자리에서 밖으로 삐져나간다.
    캡처 API에 그대로 넘기면 실패하거나 엉뚱한 영역이 잡히므로 미리 자른다.
    """
    bl, bt, bw, bh = bounds
    left = max(bl, min(left, bl + bw - 1))
    top = max(bt, min(top, bt + bh - 1))
    width = max(1, min(width, bl + bw - left))
    height = max(1, min(height, bt + bh - top))
    return (left, top, width, height)
