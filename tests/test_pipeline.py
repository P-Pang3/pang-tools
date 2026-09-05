# -*- coding: utf-8 -*-
"""파이프라인 통합 검증 — 실제 입력은 주입하지 않는다.

핵심 질문: 스캔이 느려도 키 입력이 주기를 지키는가 (D-03 해소).
옛 구조는 한 스레드가 스캔·이동·키를 순서대로 처리했으므로 지켰을 리가 없다.
"""
import sys, statistics, threading, time
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.pipeline import Pipeline
from core.snapshot import Detection, WorldSnapshot

SCAN_COST_MS = 200      # 아주 느린 지각 — 옛 구조라면 키가 이만큼 밀린다
KEY_INTERVAL = 100
RUN_SEC = 6.0


class SlowBackend:
    """느린 지각 백엔드. 검출을 하나 만들어 행동 루프도 계속 일하게 한다."""
    name = "slow-fake"
    def __init__(self): self.scans = 0
    def available(self): return True
    def diagnostics(self): return ["🧪  테스트 백엔드"]
    def close(self): pass
    def template_count(self): return 1
    def load_templates(self, d, s): pass
    def perceive(self):
        time.sleep(SCAN_COST_MS / 1000.0)      # 무거운 스캔을 흉내
        self.scans += 1
        s = WorldSnapshot()
        s.backend = self.name
        s.window_ok = True
        s.foreground = True
        s.client_rect = (0, 0, 1024, 768)
        s.scan_ms = SCAN_COST_MS
        # 매번 새 위치의 아이템 — 추적기가 계속 일감을 갖도록
        s.detections = [Detection("테스트", 0.95,
                                  500 + (self.scans % 7) * 13,
                                  400 + (self.scans % 5) * 11, 20, 20)]
        return s


key_times = []
click_times = []
move_calls = []


class FakeHand:
    """입력을 실제로 내보내지 않고 시각만 기록한다."""
    def __init__(self, kind):
        self.kind = kind
        self.last_moved_to = (500, 400)
        self._pos = (500, 400)
    def jittered_ms(self, base): return base
    def sleep_ms(self, ms, ev=None):
        return ev.wait(ms / 1000.0) if ev is not None else False
    def hesitate(self, ev=None): return False
    def cursor(self): return self._pos
    def move_to(self, x, y, w=24, ev=None):
        move_calls.append(time.monotonic())
        self._pos = (int(x), int(y))
        self.last_moved_to = self._pos
        return ev.wait(0.09) if ev is not None else False   # 90ms 이동
    def micro_drift(self, ev=None): return False
    def click(self, ev=None):
        click_times.append(time.monotonic()); return False
    def press_key(self, raw, ev=None):
        key_times.append(time.monotonic()); return False


pipe = Pipeline(log_dir=None)
logs = []
pipe.set_callbacks(log=lambda m: logs.append(m))
pipe.set_config({
    "window_lock": False, "rest_cycle_enabled": False,
    "scan_interval_ms": 50, "click_interval_ms": 300,
    "key_interval_ms": KEY_INTERVAL, "pickup_key": "z",
    "failsafe_corner": False, "pause_on_user_input": False,
    "stop_when_window_gone": False, "jitter_percent": 0,
    "max_snapshot_age_sec": 5.0, "track_lost_sec": 0.4,
    "max_attempts": 2, "retry_gap_sec": 0.3,
})
pipe.set_backend(SlowBackend())
pipe.hands = FakeHand("mouse")
pipe.keyhand = FakeHand("key")
pipe.guard._human = pipe.hands

print(f"스캔 비용 {SCAN_COST_MS}ms · 키 주기 {KEY_INTERVAL}ms · {RUN_SEC}초 실행")
pipe.start()
time.sleep(RUN_SEC)
pipe.stop()
time.sleep(0.4)

gaps = [(b - a) * 1000 for a, b in zip(key_times, key_times[1:])]
print()
print("=" * 60)
if gaps:
    med = statistics.median(gaps)
    print(f"키 입력 {len(key_times)}회")
    print(f"  간격 중앙값 {med:6.1f}ms   (설정 {KEY_INTERVAL}ms)")
    print(f"  표준편차    {statistics.pstdev(gaps):6.1f}ms")
    print(f"  최대 간격   {max(gaps):6.1f}ms")
    over = [g for g in gaps if g > KEY_INTERVAL * 1.8]
    print(f"  1.8배 넘게 밀린 횟수: {len(over)} / {len(gaps)}")
    ok_key = abs(med - KEY_INTERVAL) < KEY_INTERVAL * 0.25 and len(over) <= 1
else:
    ok_key = False
    print("키 입력이 한 번도 발생하지 않음")

print(f"\n클릭 {len(click_times)}회 · 이동 {len(move_calls)}회")
print(f"스레드 정리됨: {not any(t.is_alive() for t in pipe._threads)}")
print()
print(f"판정 — 스캔 {SCAN_COST_MS}ms 부하에도 키가 {KEY_INTERVAL}ms 주기를 지킴: "
      f"{'PASS' if ok_key else 'FAIL'}")
print("=" * 60)
print("\n로그 일부:")
for l in logs[:6]:
    print("  ", l.replace("\n", " "))
