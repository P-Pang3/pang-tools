# -*- coding: utf-8 -*-
"""
실행 계층 — 행동을 실제 입력으로 바꾼다 (P1.6).

타이밍과 궤적에 관한 모든 것이 여기 모인다. 예전에는 지터가 엔진 루프에,
이동 곡선이 클릭 함수에, 유지 시간이 상수로 흩어져 있었다.

사람의 입력이 기계와 다른 지점은 네 가지다.
  - 지연 분포가 비대칭이다. 평균 근처가 많고 가끔 크게 늦는다(균등분포 아님)
  - 연속된 입력에 상관이 있다. 집중하면 계속 빠르고 지치면 계속 느리다
  - 이동 시간이 거리와 목표 크기에 좌우된다 (Fitts 의 법칙)
  - 목표를 한 번에 맞히지 않는다. 살짝 지나쳤다가 되돌아온다

넷 다 흉내 낸다. 마지막이 가장 특징적인데 예전 구현에는 아예 없었다.
"""
import math
import random
import time

from pynput.mouse import Button, Controller as MouseController
from pynput.keyboard import Controller as KeyController, Key


class HumanInput:
    """인간형 마우스·키보드 입력."""

    def __init__(self, config_getter, log=None):
        self._cfg = config_getter
        self._log = log or (lambda m: None)
        self.mouse = MouseController()
        self.keyboard = KeyController()

        # 피로도 — 0 근처를 떠도는 값. 지연에 곱해져 완만한 상관을 만든다.
        # 랜덤워크라 한번 느려지면 한동안 느리다.
        self._fatigue = 0.0
        # 매크로가 마지막으로 옮긴 커서 위치 — 사용자 개입 감지에 쓴다
        self.last_moved_to = None

    def _c(self, key, default):
        try:
            return (self._cfg() or {}).get(key, default)
        except Exception:
            return default

    # ------------------------------------------------------------------
    # 지연
    # ------------------------------------------------------------------
    def _step_fatigue(self):
        """피로도를 한 걸음 굴린다. -1 ~ +1 범위를 완만하게 떠돈다."""
        self._fatigue += random.gauss(0, 0.11)
        # 0 쪽으로 약하게 당겨 발산을 막는다. 계수가 클수록 오래 끌린다 —
        # 사람의 반응 시간 자기상관은 대략 0.1~0.3 이고 여기에 맞췄다.
        self._fatigue *= 0.97
        self._fatigue = max(-1.0, min(1.0, self._fatigue))
        return self._fatigue

    def jittered_ms(self, base_ms: float) -> float:
        """기준 간격에 사람다운 변동을 준다.

        로그정규를 쓰는 이유: 사람의 반응 간격은 왼쪽이 막혀 있고(0보다 빠를 수
        없다) 오른쪽으로 꼬리가 길다. 균등분포는 히스토그램만 봐도 기계다.
        """
        try:
            pct = float(self._c("jitter_percent", 17)) / 100.0
        except (TypeError, ValueError):
            pct = 0.17
        pct = max(0.0, min(0.95, pct))
        if pct <= 0:
            return float(base_ms)

        # sigma 를 지터 폭에 맞춘다. pct 가 산포의 대략적인 크기가 되도록.
        sigma = pct * 0.8
        mu = -0.5 * sigma * sigma          # 중앙값이 base 근처에 오도록 보정
        factor = math.exp(random.gauss(mu, sigma))

        # 피로도를 곱해 연속 입력에 상관을 준다
        factor *= 1.0 + self._step_fatigue() * pct * 1.4

        # 극단값을 자른다 — 10배 느려지면 사람이 아니라 멈춘 것이다
        factor = max(1.0 - pct * 1.6, min(1.0 + pct * 2.5, factor))
        return max(10.0, base_ms * factor)

    def sleep_ms(self, ms: float, stop_event=None) -> bool:
        """ms 만큼 쉰다. 정지 요청이 오면 즉시 True 를 돌려준다."""
        if ms <= 0:
            return False
        if stop_event is not None:
            return stop_event.wait(ms / 1000.0)
        time.sleep(ms / 1000.0)
        return False

    def hesitate(self, stop_event=None) -> bool:
        """가끔 반응이 늦는 순간 (P0.5)."""
        try:
            prob = float(self._c("hesitate_probability", 0.08))
        except (TypeError, ValueError):
            prob = 0.08
        if prob <= 0 or random.random() >= prob:
            return False
        lo = float(self._c("hesitate_ms_min", 180))
        hi = float(self._c("hesitate_ms_max", 650))
        return self.sleep_ms(random.uniform(lo, max(lo, hi)), stop_event)

    # ------------------------------------------------------------------
    # 이동
    # ------------------------------------------------------------------
    def _move_duration_ms(self, dist: float, target_w: float) -> float:
        """Fitts 의 법칙으로 이동 시간을 정한다.

            MT = a + b * log2(2D / W)

        먼 거리는 오래, 큰 목표는 짧게. 고정 120ms 로 300px 와 20px 를 똑같이
        움직이는 건 사람의 궤적이 아니다.
        """
        base = float(self._c("mouse_move_ms", 120))
        if base <= 0:
            return 0.0
        w = max(8.0, float(target_w or 24))
        d = max(1.0, dist)
        idx = math.log2(2.0 * d / w + 1.0)      # 난이도 지수
        a = base * 0.35
        b = base * 0.42
        ms = a + b * idx
        # 사람마다·순간마다 다르다
        ms *= random.uniform(0.85, 1.25) * (1.0 + self._fatigue * 0.12)
        return max(30.0, min(ms, base * 6.0))

    def _bezier_path(self, sx, sy, tx, ty, steps):
        """2차 베지어. 제어점을 수직으로 밀어 매번 다른 완만한 곡선을 만든다."""
        dist = math.hypot(tx - sx, ty - sy)
        nx = -(ty - sy) / dist
        ny = (tx - sx) / dist
        off = random.uniform(0.06, 0.22) * dist * random.choice((-1, 1))
        cx = (sx + tx) / 2.0 + nx * off
        cy = (sy + ty) / 2.0 + ny * off

        pts = []
        for i in range(1, steps + 1):
            t = i / steps
            te = t * t * (3.0 - 2.0 * t)        # smoothstep
            mt = 1.0 - te
            pts.append((
                mt * mt * sx + 2.0 * mt * te * cx + te * te * tx,
                mt * mt * sy + 2.0 * mt * te * cy + te * te * ty,
            ))
        return pts

    def move_to(self, tx, ty, target_w=24, stop_event=None) -> bool:
        """커서를 옮긴다. 정지 요청이 오면 중간에 끊고 True."""
        sx, sy = self.mouse.position
        dist = math.hypot(tx - sx, ty - sy)

        if dist < 2:
            self.mouse.position = (int(tx), int(ty))
            self.last_moved_to = (int(tx), int(ty))
            return False

        duration = self._move_duration_ms(dist, target_w)
        if duration <= 0:
            self.mouse.position = (int(tx), int(ty))
            self.last_moved_to = (int(tx), int(ty))
            return False

        # 오버슛 — 먼 거리에서만. 사람은 빠르게 움직일수록 목표를 지나친다.
        overshoot = (self._c("overshoot_enabled", True) and
                     dist > 90 and random.random() < 0.55)

        if overshoot:
            # 목표 너머로 살짝 지나간 지점을 먼저 찍는다
            over = random.uniform(0.04, 0.11) * dist
            ang = math.atan2(ty - sy, tx - sx) + random.uniform(-0.35, 0.35)
            ox = tx + math.cos(ang) * over
            oy = ty + math.sin(ang) * over
            if self._glide(sx, sy, ox, oy, duration * 0.78, stop_event):
                return True
            # 짧게 멈췄다가 되돌아온다 — 눈이 오차를 확인하는 시간
            if self.sleep_ms(random.uniform(18, 55), stop_event):
                return True
            cx, cy = self.mouse.position
            return self._glide(cx, cy, tx, ty, duration * 0.34, stop_event)

        return self._glide(sx, sy, tx, ty, duration, stop_event)

    def _glide(self, sx, sy, tx, ty, duration_ms, stop_event) -> bool:
        if math.hypot(tx - sx, ty - sy) < 1:
            return False
        steps = max(6, int(duration_ms / 9))
        pts = self._bezier_path(sx, sy, tx, ty, steps)
        gap = (duration_ms / 1000.0) / steps
        for x, y in pts:
            self.mouse.position = (int(round(x)), int(round(y)))
            if stop_event is not None and stop_event.wait(gap):
                self.last_moved_to = self.mouse.position
                return True
            if stop_event is None:
                time.sleep(gap)
        self.last_moved_to = (int(round(tx)), int(round(ty)))
        return False

    def micro_drift(self, stop_event=None) -> bool:
        """클릭 직전 아주 작게 흔들린다. 사람 손은 완전히 정지하지 않는다."""
        if not self._c("micro_drift", True):
            return False
        if random.random() > 0.45:
            return False
        x, y = self.mouse.position
        self.mouse.position = (x + random.choice((-1, 0, 1)),
                               y + random.choice((-1, 0, 1)))
        self.last_moved_to = self.mouse.position
        return self.sleep_ms(random.uniform(8, 26), stop_event)

    # ------------------------------------------------------------------
    # 클릭 / 키
    # ------------------------------------------------------------------
    def click(self, stop_event=None) -> bool:
        """좌클릭. 누르고 있는 시간을 매번 다르게 한다 (예전엔 40ms 고정)."""
        hold = random.uniform(
            float(self._c("click_hold_min_ms", 42)),
            float(self._c("click_hold_max_ms", 96)))
        self.mouse.press(Button.left)
        stopped = self.sleep_ms(hold, stop_event)
        self.mouse.release(Button.left)
        return stopped

    def press_key(self, raw: str, stop_event=None) -> bool:
        """지정 키를 한 번 누른다. 유지 시간은 변동."""
        raw = (raw or "z").strip().lower()
        if len(raw) == 1:
            key = raw
        else:
            key = getattr(Key, raw, None)
            if key is None:
                self._log(f"⚠  알 수 없는 키 이름: {raw}")
                return False
        hold = random.uniform(
            float(self._c("key_hold_min_ms", 28)),
            float(self._c("key_hold_max_ms", 72)))
        self.keyboard.press(key)
        stopped = self.sleep_ms(hold, stop_event)
        self.keyboard.release(key)
        return stopped

    # ------------------------------------------------------------------
    def cursor(self):
        return self.mouse.position
