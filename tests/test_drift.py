# -*- coding: utf-8 -*-
"""이동 중에 감시해도 오탐이 없는지 확인 (양성 대조 포함)."""
import sys, os, threading, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.actuation import HumanInput
from core.safety import Guard, PAUSE, OK

CFG = {"jitter_percent": 0, "mouse_move_ms": 300, "overshoot_enabled": False,
       "micro_drift": False, "failsafe_corner": False, "window_lock": False,
       "stop_when_window_gone": False, "pause_on_user_input": True,
       "user_move_tolerance_px": 25, "user_move_hits": 2, "user_pause_sec": 1}

class FakeMouse:
    def __init__(self): self.position = (0, 0)
class Win:
    def exists(self): return True
    def is_foreground(self): return True

def run(label, glide_updates):
    h = HumanInput(lambda: CFG)
    h.mouse = FakeMouse()
    g = Guard(Win(), h, lambda: CFG, log=lambda m: None)
    h.mouse.position = (100, 100)
    h.last_moved_to = (100, 100)

    hits = {"pause": 0, "checks": 0}
    stop = threading.Event()

    def watch():
        while not stop.is_set():
            v = g.check()
            hits["checks"] += 1
            if v.level == PAUSE:
                hits["pause"] += 1
            stop.wait(0.02)

    t = threading.Thread(target=watch, daemon=True)
    t.start()
    # 멀리 이동 — 실제 사냥에서 몬스터로 커서를 옮기는 상황
    for _ in range(4):
        h.move_to(900, 700)
        h.move_to(150, 150)
    stop.set(); t.join(timeout=1)
    print(f"  {label}: 검사 {hits['checks']}회 중 오탐 {hits['pause']}회")
    return hits["pause"]

# 지금 코드 (매 스텝 갱신)
now = run("수정 후 (매 스텝 갱신)", True)

# 옛 동작 재현 — 이동이 끝나야 갱신
import core.actuation as A
_orig = A.HumanInput._glide
def old_glide(self, sx, sy, tx, ty, duration_ms, stop_event):
    import math, time as _t
    if math.hypot(tx-sx, ty-sy) < 1: return False
    steps = max(6, int(duration_ms/9))
    pts = self._bezier_path(sx, sy, tx, ty, steps)
    gap = (duration_ms/1000.0)/steps
    for x, y in pts:
        self.mouse.position = (int(round(x)), int(round(y)))
        _t.sleep(gap)                    # 기준점 갱신 없음 = 옛 동작
    self.last_moved_to = (int(round(tx)), int(round(ty)))
    return False
A.HumanInput._glide = old_glide
before = run("수정 전 (끝나야 갱신)", False)
A.HumanInput._glide = _orig

print()
print(f"결과: {'PASS' if now == 0 and before > 0 else 'FAIL'}"
      f"   (수정 전 {before}회 -> 수정 후 {now}회)")
