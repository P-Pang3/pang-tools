# -*- coding: utf-8 -*-
"""
안전 계층 (P1.7).

단축키 하나에만 의존하던 정지 경로를 여러 겹으로 만든다. 단축키 등록이
실패하거나 게임이 키를 삼키면 예전에는 GUI 창을 직접 찾아 누르는 것 외에
멈출 방법이 없었다 (진단 D-11).

판정은 세 등급이다.
  OK    — 계속
  PAUSE — 잠시 멈춤. 조건이 풀리면 스스로 재개한다
  STOP  — 정지. 사람이 다시 켜야 한다
"""
import time

OK = "ok"
PAUSE = "pause"
STOP = "stop"


class Verdict:
    __slots__ = ("level", "reason")

    def __init__(self, level=OK, reason=""):
        self.level = level
        self.reason = reason

    def __bool__(self):
        return self.level == OK

    def __repr__(self):
        return f"Verdict({self.level}: {self.reason})"


_OK = Verdict()


class Guard:
    """실행 전에 물어보는 감시자. 각 검사는 독립이고 하나라도 걸리면 막는다."""

    def __init__(self, window, human, config_getter, log=None):
        self._win = window
        self._human = human
        self._cfg = config_getter
        self._log = log or (lambda m: None)

        self._screen_w = 0
        self._screen_h = 0
        self._user_touch_until = 0.0
        self._window_gone_since = 0.0
        self._consec_fail = 0
        self._last_verdict = OK

    def _c(self, key, default):
        try:
            return (self._cfg() or {}).get(key, default)
        except Exception:
            return default

    def bind_screen(self, w, h):
        self._screen_w, self._screen_h = w, h

    def reset(self):
        self._user_touch_until = 0.0
        self._window_gone_since = 0.0
        self._consec_fail = 0
        self._last_verdict = OK

    # ------------------------------------------------------------------
    def note_failure(self):
        """행동이 실패했다. 연속 실패가 쌓이면 전제가 깨진 것으로 본다."""
        self._consec_fail += 1

    def note_success(self):
        self._consec_fail = 0

    # ------------------------------------------------------------------
    def _check_failsafe_corner(self) -> Verdict:
        """커서를 화면 모서리로 던지면 즉시 정지.

        어떤 상황에서도 손이 닿는 정지 수단이다. 단축키가 죽어도,
        게임이 포커스를 붙들고 있어도 마우스는 언제나 움직일 수 있다.
        """
        if not self._c("failsafe_corner", True):
            return _OK
        try:
            x, y = self._human.cursor()
        except Exception:
            return _OK
        m = int(self._c("failsafe_margin_px", 3))
        if x <= m and y <= m:
            return Verdict(STOP, "페일세이프 — 커서가 좌상단 모서리에 닿음")
        return _OK

    def _check_user_intervention(self) -> Verdict:
        """매크로가 옮기지 않은 커서 이동이 있으면 사람이 개입한 것.

        게임을 하다가 매크로가 갑자기 커서를 낚아채는 상황을 막는다.
        일정 시간 조용히 물러났다가 스스로 돌아온다.
        """
        if not self._c("pause_on_user_input", True):
            return _OK

        now = time.monotonic()
        if now < self._user_touch_until:
            remain = self._user_touch_until - now
            return Verdict(PAUSE, f"사용자 조작 감지 — {remain:.0f}초 후 재개")

        expected = self._human.last_moved_to
        if expected is None:
            return _OK
        try:
            x, y = self._human.cursor()
        except Exception:
            return _OK

        tol = float(self._c("user_move_tolerance_px", 6))
        if abs(x - expected[0]) > tol or abs(y - expected[1]) > tol:
            hold = float(self._c("user_pause_sec", 4))
            self._user_touch_until = now + hold
            # 기준점을 현재 위치로 옮겨 같은 이동으로 두 번 걸리지 않게 한다
            self._human.last_moved_to = (x, y)
            return Verdict(PAUSE, f"사용자 조작 감지 — {hold:.0f}초 대기")
        return _OK

    def _check_window(self) -> Verdict:
        """게임 창이 사라졌는가. 잠깐 없어지는 것과 종료를 구분한다."""
        if not self._c("stop_when_window_gone", True):
            return _OK
        if not self._c("window_lock", True):
            return _OK       # 창을 특정하지 않는 모드 — 감시할 대상이 없다
        if self._win.exists():
            self._window_gone_since = 0.0
            return _OK

        now = time.monotonic()
        if self._window_gone_since == 0.0:
            self._window_gone_since = now
            return Verdict(PAUSE, "게임 창을 찾을 수 없음")

        grace = float(self._c("window_gone_grace_sec", 5))
        if (now - self._window_gone_since) >= grace:
            return Verdict(STOP, f"게임 창이 {grace:.0f}초 넘게 사라짐 — 종료로 판단")
        return Verdict(PAUSE, "게임 창을 찾을 수 없음")

    def _check_foreground(self) -> Verdict:
        if not self._c("window_lock", True):
            return _OK
        if self._win.is_foreground():
            return _OK
        return Verdict(PAUSE, "게임 창이 활성 상태가 아님")

    def _check_failures(self) -> Verdict:
        limit = int(self._c("max_consecutive_failures", 25))
        if limit > 0 and self._consec_fail >= limit:
            return Verdict(STOP, f"연속 {self._consec_fail}회 실패 — 전제가 깨진 상태")
        return _OK

    # ------------------------------------------------------------------
    def check(self) -> Verdict:
        """모든 검사를 돌린다. STOP 이 PAUSE 보다 우선."""
        checks = (
            self._check_failsafe_corner,
            self._check_failures,
            self._check_window,
            self._check_user_intervention,
            self._check_foreground,
        )
        worst = _OK
        for fn in checks:
            v = fn()
            if v.level == STOP:
                return v
            if v.level == PAUSE and worst.level == OK:
                worst = v
        return worst


class Watchdog:
    """판단 스레드가 살아 있는지 지켜본다.

    스레드가 예외 없이 멈추는 경우(교착, 무한 대기)는 로그에도 안 남는다.
    심장박동이 끊기면 알린다.
    """

    def __init__(self, timeout_sec=15.0, on_dead=None, log=None):
        self.timeout = timeout_sec
        self._beat = time.monotonic()
        self._on_dead = on_dead
        self._log = log or (lambda m: None)
        self._fired = False

    def beat(self):
        self._beat = time.monotonic()
        self._fired = False

    def check(self) -> bool:
        """살아 있으면 True. 죽었다고 판단하면 콜백을 한 번만 부른다."""
        if self._fired:
            return False
        silent = time.monotonic() - self._beat
        if silent < self.timeout:
            return True
        self._fired = True
        self._log(f"⚠  워치독 — 판단 스레드가 {silent:.0f}초간 응답 없음. 정지합니다.")
        if self._on_dead:
            try:
                self._on_dead()
            except Exception:
                pass
        return False
