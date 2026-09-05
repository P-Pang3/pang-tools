# -*- coding: utf-8 -*-
"""
파이프라인 — 계층을 서로 다른 스레드에 얹는다 (P1.5).

예전에는 한 스레드가 스캔·이동·키를 순서대로 처리했다. 스캔이 200ms 걸리면
그동안 키 타이머가 통째로 밀렸고, 60ms 주기 설정은 지켜진 적이 없다 (D-03).
30ms 폴링이 타이밍 하한이기도 했다 (D-10).

네 개의 루프로 나눈다. 기획서에는 셋으로 적었는데, 실제로 짜보니 감시가
행동 루프에 얹혀 있으면 행동이 막힐 때 감시도 같이 막혀 쓸모가 없었다.

  지각  perceive() 를 자기 주기로 돌려 최신 스냅샷 하나만 남긴다
  행동  스냅샷을 보고 대상을 골라 마우스를 옮기고 클릭한다
  키    줍기 키를 자기 주기로 누른다. 마우스와 독립이라 서로 막지 않는다
  감시  안전 판정·워치독·통계. 다른 루프가 멈춰도 이건 돈다

마우스와 키보드에 각각 HumanInput 을 준다. 컨트롤러를 스레드 간에 공유하지
않으려는 것이고, 덤으로 두 손의 피로도가 따로 흐른다.
"""
import random
import threading
import time

from .actuation import HumanInput
from .combat import (CombatPolicy, ATTACK, HALT, HEAL_HP, HEAL_MP,
                     IDLE, PICKUP)
from .geometry import (dpi_warning, raise_timer_resolution,
                       restore_timer_resolution)
from .safety import Guard, Watchdog, OK, PAUSE, STOP
from .telemetry import SessionLog, Stats
from .tracking import Tracker
from .window import GameWindow


class Pipeline:
    def __init__(self, log_dir=None):
        self.config = {}
        self._log_cb = None
        self._status_cb = None
        self._phase_cb = None

        self._running = False
        self._stop_event = threading.Event()
        self._threads = []

        # 계층
        self.window = GameWindow()
        self.hands = HumanInput(self._cfg, self._log)      # 마우스
        self.keyhand = HumanInput(self._cfg, self._log)    # 키보드
        self.tracker = Tracker(self._cfg, self._log)
        self.policy = CombatPolicy(self._cfg, self._log)
        self.guard = Guard(self.window, self.hands, self._cfg, self._log)
        self.watchdog = Watchdog(15.0, on_dead=self.stop, log=self._log)
        self.stats = Stats()
        self.backend = None
        self.filelog = SessionLog(log_dir) if log_dir else None

        # 공유 상태
        self._snap_lock = threading.Lock()
        self._snapshot = None
        self._phase = "work"
        self._phase_end = float("inf")
        self._pause_reason = ""
        self._last_pause_log = 0.0
        self._miss_next = 0.0

    # ------------------------------------------------------------------
    # 외부 API — 기존 MacroEngine 과 같은 모양을 유지한다
    # ------------------------------------------------------------------
    def _cfg(self):
        return self.config

    def set_config(self, cfg: dict):
        self.config = cfg or {}
        lock = self.config.get("window_lock", True)
        self.window.set_filter(
            self.config.get("window_title", "") if lock else "",
            self.config.get("window_process", "") if lock else "")

    def set_backend(self, backend):
        self.backend = backend

    def set_callbacks(self, log=None, status=None, phase=None):
        self._log_cb = log
        self._status_cb = status
        self._phase_cb = phase

    def is_running(self) -> bool:
        return self._running

    def phase_remaining(self) -> tuple:
        if not self.config.get("rest_cycle_enabled", True):
            return ("work", None)
        return (self._phase, max(0.0, self._phase_end - time.monotonic()))

    def pause_reason(self) -> str:
        return self._pause_reason

    # ------------------------------------------------------------------
    def _log(self, msg: str):
        if self.filelog:
            self.filelog.write(msg)
        if self._log_cb:
            try:
                self._log_cb(msg)
            except Exception:
                pass

    def _c(self, key, default):
        v = self.config.get(key, default)
        return default if v is None else v

    def _cf(self, key, default):
        try:
            return float(self._c(key, default))
        except (TypeError, ValueError):
            return float(default)

    def _ci(self, key, default):
        try:
            return int(self._c(key, default))
        except (TypeError, ValueError):
            return int(default)

    # ------------------------------------------------------------------
    def start(self):
        if self._running:
            return
        if self.backend is None:
            self._log("⚠  지각 백엔드가 없습니다.")
            return

        self._running = True
        self._stop_event.clear()
        self.stats.reset()
        self.tracker.reset()
        self.policy.reset()
        self.guard.reset()
        self.watchdog.beat()
        self._pause_reason = ""
        self._snapshot = None

        scan_ms = self._ci("scan_interval_ms", 250)
        click_ms = self._ci("click_interval_ms", 1200)
        key_ms = self._ci("key_interval_ms", 200)
        key = str(self._c("pickup_key", "z")).strip().upper()

        self._log(f"▶  시작 — 스캔 {scan_ms}ms · 클릭 {click_ms}ms · '{key}' {key_ms}ms")
        for d in self.backend.diagnostics():
            self._log(d)
        w = dpi_warning()
        if w:
            self._log(w)
        if self.config.get("window_lock", True):
            title = self.config.get("window_title", "") or "(빈값)"
            found = self.window.title()
            self._log(f"🪟  창 필터 '{title}' — " +
                      (f"찾음: {found}" if found else "아직 못 찾음"))
        else:
            self._log("🪟  창 필터 OFF")
        if self.config.get("combat_enabled", False):
            hp_key = str(self._c("hp_potion_key", "")).strip()
            tail = (f" \u00b7 HP \ubb3c\uc57d '{hp_key.upper()}'" if hp_key
                    else " \u00b7 \u26a0 HP \ubb3c\uc57d \ud0a4\uac00 \ube44\uc5b4 \uc788\uc2b5\ub2c8\ub2e4")
            self._log("\u2694  \uc0ac\ub0e5 \ubaa8\ub4dc ON" + tail)
        if self.config.get("failsafe_corner", True):
            self._log("🛟  페일세이프 ON — 커서를 화면 좌상단 모서리로 보내면 즉시 정지")

        # 타이머 해상도를 1ms 로 — 기본 15.6ms 에서는 짧은 주기가 지켜지지 않는다
        raise_timer_resolution(1)

        self._begin_work_phase(initial=True)
        if self._status_cb:
            self._status_cb(True)

        self._threads = [
            threading.Thread(target=self._perception_loop, daemon=True,
                             name="perception"),
            threading.Thread(target=self._action_loop, daemon=True,
                             name="action"),
            threading.Thread(target=self._key_loop, daemon=True, name="key"),
            threading.Thread(target=self._guard_loop, daemon=True, name="guard"),
        ]
        for t in self._threads:
            t.start()

    def stop(self):
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        restore_timer_resolution(1)
        self._log("■  정지\n     " + self.stats.report())
        if self._status_cb:
            self._status_cb(False)

    def toggle(self):
        self.stop() if self._running else self.start()

    def shutdown(self):
        self.stop()
        if self.backend:
            self.backend.close()
        if self.filelog:
            self.filelog.close()

    # ------------------------------------------------------------------
    # 루프 1 — 지각
    # ------------------------------------------------------------------
    def _perception_loop(self):
        while self._alive():
            if self._resting():
                if self._stop_event.wait(0.2):
                    return
                continue
            t0 = time.monotonic()
            try:
                snap = self.backend.perceive()
                with self._snap_lock:
                    self._snapshot = snap      # 최신 하나만 — 밀린 프레임은 버린다
                self.stats.note_scan(snap.scan_ms, bool(snap.detections))
                self.tracker.update(snap)
            except Exception as e:
                self._log(f"⚠  지각 오류: {e}")

            gap = self._cf("scan_interval_ms", 250) / 1000.0
            remain = gap - (time.monotonic() - t0)
            if remain > 0 and self._stop_event.wait(remain):
                return

    def _latest(self, max_age=None):
        with self._snap_lock:
            snap = self._snapshot
        if snap is None:
            return None
        if max_age is not None and snap.age > max_age:
            return None
        return snap

    # ------------------------------------------------------------------
    # 루프 2 — 행동 (판단 + 마우스)
    # ------------------------------------------------------------------
    def _action_loop(self):
        next_at = time.monotonic()
        while self._alive():
            self.watchdog.beat()

            if self._resting() or self._blocked():
                if self._stop_event.wait(0.15):
                    return
                next_at = time.monotonic()
                continue

            now = time.monotonic()
            if now < next_at:
                # 기한까지 한 번에 잔다 — 폴링 하한이 사라진다 (D-10)
                if self._stop_event.wait(min(next_at - now, 0.25)):
                    return
                continue

            try:
                nxt = self._act_once()
            except Exception as e:
                nxt = None
                self._log(f"⚠  행동 오류: {e}")
                self.guard.note_failure()

            # 행동마다 알맞은 간격이 다르다 (공격은 짧게, 물약은 더 짧게)
            base = nxt if nxt else self._cf("click_interval_ms", 1200)
            next_at = time.monotonic() + self.hands.jittered_ms(base) / 1000.0

    def _act_once(self):
        """다음 행동 하나를 실행하고, 다음 호출까지 기다릴 시간(ms)을 돌려준다."""
        max_age = self._cf("max_snapshot_age_sec", 1.5)
        snap = self._latest(max_age)
        combat = bool(self._c("combat_enabled", False))

        # 템플릿이 없고 사냥도 아니면 예전처럼 커서 자리에 클릭한다
        if self.backend.template_count() == 0 and not combat:
            if self.hands.hesitate(self._stop_event):
                return None
            if not self.hands.click(self._stop_event):
                self.stats.note_click()
                self.guard.note_success()
            return None

        if snap is None:
            return None

        cursor = self.hands.cursor()
        action = self.policy.decide(snap, self.tracker, cursor)

        if action.kind == IDLE:
            if snap.top_miss:
                self._log_miss(snap.top_miss)
            return None

        # ── 위험 — 스스로 멈춘다 ──
        if action.kind == HALT:
            self._log(f"\u26d4  {action.reason}")
            self.stop()
            return None

        # ── 회복 ──
        if action.kind in (HEAL_HP, HEAL_MP):
            what = "HP" if action.kind == HEAL_HP else "MP"
            self._log(f"\U0001F9EA  {what} \ubb3c\uc57d "
                      f"'{action.key.upper()}' \u2014 {action.reason}")
            if not self.hands.press_key(action.key, self._stop_event):
                self.policy.note_heal(action.key)
                self.stats.note_key()
            return self._cf("potion_gap_ms", 350)

        # ── 공격 / 줍기 — 둘 다 '옮겨서 클릭' 이다 ──
        t = action.target
        if t is None:
            return None

        self.tracker.mark_attempt(t)
        verb = "\u2694" if action.kind == ATTACK else "\U0001F3AF"
        skill_txt = (f"  [{action.skill.upper()}]"
                     if getattr(action, "skill", None) else "")
        self._log(f"{verb}  [{t.name}] #{t.id} {t.score:.3f} "
                  f"\u2192 ({t.x}, {t.y})"
                  + (f"  {t.attempts}\ubc88\uc9f8" if t.attempts > 1 else "")
                  + skill_txt
                  + (f"  {action.reason}" if action.reason else ""))

        t0 = time.monotonic()
        if self.hands.hesitate(self._stop_event):
            return None

        # 스킬 공격은 '스킬키 -> 대상 클릭' 순서다. 클릭부터 하면
        # 스킬이 아니라 평타가 나가거나 대상만 선택되고 만다.
        if action.kind == ATTACK and action.skill:
            if self.hands.press_key(action.skill, self._stop_event):
                return None
            self.policy.note_skill(action.skill)
            self.stats.note_key()
            gap = self._cf("skill_click_gap_ms", 90)
            if gap > 0 and self.hands.sleep_ms(gap, self._stop_event):
                return None

        if self.hands.move_to(t.x, t.y, max(t.w, t.h), self._stop_event):
            return None
        if self.hands.micro_drift(self._stop_event):
            return None
        pre = self._cf("pre_move_delay_ms", 20)
        if pre > 0 and self.hands.sleep_ms(pre, self._stop_event):
            return None
        if self.hands.click(self._stop_event):
            return None

        self.stats.note_click((time.monotonic() - t0) * 1000.0)
        self.guard.note_success()

        if action.kind == ATTACK:
            return self._cf("attack_interval_ms", 1500)
        return None

    def _log_miss(self, miss):
        now = time.monotonic()
        if now < self._miss_next:
            return
        self._miss_next = now + 5.0
        name, score, thr = miss
        hint = ("임계값을 낮춰보세요." if score > 0.5
                else "화면에 아이템이 없습니다.")
        self._log(f"🔍  미발견 — 최고 {score:.3f} [{name}] "
                  f"(임계값 {thr:.2f}). {hint}")

    # ------------------------------------------------------------------
    # 루프 3 — 줍기 키
    # ------------------------------------------------------------------
    def _key_loop(self):
        next_at = time.monotonic()
        while self._alive():
            if self._resting() or self._blocked():
                if self._stop_event.wait(0.15):
                    return
                next_at = time.monotonic()
                continue

            now = time.monotonic()
            if now < next_at:
                if self._stop_event.wait(min(next_at - now, 0.25)):
                    return
                continue

            try:
                if not self.keyhand.press_key(
                        str(self._c("pickup_key", "z")), self._stop_event):
                    self.stats.note_key()
            except Exception as e:
                self._log(f"⚠  키 입력 실패: {e}")

            base = self._cf("key_interval_ms", 200)
            next_at = time.monotonic() + self.keyhand.jittered_ms(base) / 1000.0

    # ------------------------------------------------------------------
    # 루프 4 — 감시
    # ------------------------------------------------------------------
    def _guard_loop(self):
        stats_next = time.monotonic() + 30.0
        while self._alive():
            # 워치독 — 행동 루프가 조용히 멈췄는지 본다
            self.watchdog.check()

            v = self.guard.check()
            if v.level == STOP:
                self._log(f"⛔  {v.reason}")
                self.stop()
                return
            if v.level == PAUSE:
                if v.reason != self._pause_reason:
                    self._log(f"⏸  {v.reason}")
                    self._pause_reason = v.reason
                    self._last_pause_log = time.monotonic()
            elif self._pause_reason:
                self._log("▶  재개")
                self._pause_reason = ""

            # 페이즈 전환
            if self.config.get("rest_cycle_enabled", True):
                if time.monotonic() >= self._phase_end:
                    if self._phase == "work":
                        self._begin_rest_phase()
                    else:
                        self._begin_work_phase()

            now = time.monotonic()
            if now >= stats_next:
                self._log("⌛  " + self.stats.brief() + " · " +
                          self.tracker.summary())
                stats_next = now + 30.0

            if self._stop_event.wait(0.2):
                return

    # ------------------------------------------------------------------
    def _alive(self) -> bool:
        return self._running and not self._stop_event.is_set()

    def _blocked(self) -> bool:
        return bool(self._pause_reason)

    def _resting(self) -> bool:
        return (self.config.get("rest_cycle_enabled", True) and
                self._phase == "rest")

    # ------------------------------------------------------------------
    def _rand_minutes(self, lo_key, hi_key, lo_def, hi_def):
        lo = max(0.5, self._cf(lo_key, lo_def))
        hi = max(lo, self._cf(hi_key, hi_def))
        return random.uniform(lo, hi)

    def _begin_work_phase(self, initial=False):
        if not self.config.get("rest_cycle_enabled", True):
            self._phase = "work"
            self._phase_end = float("inf")
            if self._phase_cb:
                try: self._phase_cb("work", None)
                except Exception: pass
            return
        mins = self._rand_minutes("work_min_minutes", "work_max_minutes", 25, 50)
        self._phase = "work"
        self._phase_end = time.monotonic() + mins * 60.0
        if self._phase_cb:
            try: self._phase_cb("work", mins)
            except Exception: pass
        self._log(f"⏱  {'작업 구간 시작' if initial else '작업 재개'} — "
                  f"{mins:.1f}분 후 휴식")

    def _begin_rest_phase(self):
        mins = self._rand_minutes("rest_min_minutes", "rest_max_minutes", 4, 12)
        self._phase = "rest"
        self._phase_end = time.monotonic() + mins * 60.0
        self.stats.rest_sec += mins * 60.0
        if self._phase_cb:
            try: self._phase_cb("rest", mins)
            except Exception: pass
        self._log(f"💤  휴식 — {mins:.1f}분 정지")
