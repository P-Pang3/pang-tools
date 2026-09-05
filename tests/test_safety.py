# -*- coding: utf-8 -*-
"""P1.7 안전 계층 검증 — 각 정지 경로가 실제로 걸리는가."""
import sys, time
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.safety import Guard, Watchdog, OK, PAUSE, STOP

class Win:
    def __init__(self): self.ok = True; self.fg = True
    def exists(self): return self.ok
    def is_foreground(self): return self.fg

class Hand:
    def __init__(self): self.pos = (500, 500); self.last_moved_to = (500, 500)
    def cursor(self): return self.pos

CFG = {"failsafe_corner": True, "failsafe_margin_px": 3,
       "pause_on_user_input": True, "user_move_tolerance_px": 6,
       "user_pause_sec": 1, "stop_when_window_gone": True,
       "window_gone_grace_sec": 1, "window_lock": True,
       "max_consecutive_failures": 3}

win, hand = Win(), Hand()
g = Guard(win, hand, lambda: CFG, log=lambda m: None)
results = []

def check(label, expect):
    v = g.check()
    ok = v.level == expect
    results.append(ok)
    print(f"  {label:<38} {v.level:<6} {'PASS' if ok else 'FAIL (기대 '+expect+')'}"
          + (f"   [{v.reason}]" if v.reason else ""))

print("1) 정상 상태")
check("아무 문제 없음", OK)

print("\n2) 페일세이프 — 커서를 좌상단 모서리로")
hand.pos = (1, 1); hand.last_moved_to = (1, 1)
check("커서가 (1,1)", STOP)
hand.pos = (500, 500); hand.last_moved_to = (500, 500)
g.reset()

print("\n3) 사용자 개입 — 매크로가 옮기지 않은 커서 이동")
hand.pos = (800, 620)                     # last_moved_to 와 다르다
check("사람이 마우스를 만짐", PAUSE)
check("대기 중에는 계속 PAUSE", PAUSE)
time.sleep(1.1)
check("1초 뒤 자동 재개", OK)

print("\n4) 게임 창이 사라짐")
win.ok = False
check("사라진 직후 (유예 중)", PAUSE)
time.sleep(1.1)
check("유예 시간 초과", STOP)
win.ok = True; g.reset()

print("\n5) 창이 활성이 아님")
win.fg = False
check("다른 창이 활성", PAUSE)
win.fg = True

print("\n6) 연속 실패 누적")
for _ in range(3):
    g.note_failure()
check("3회 연속 실패", STOP)
g.note_success()
check("성공하면 초기화", OK)

print("\n7) 워치독")
fired = []
wd = Watchdog(0.5, on_dead=lambda: fired.append(1), log=lambda m: None)
wd.beat()
alive1 = wd.check()
time.sleep(0.6)
alive2 = wd.check()
ok = alive1 and not alive2 and len(fired) == 1
results.append(ok)
print(f"  {'무응답 0.5초 뒤 발동':<38} {'PASS' if ok else 'FAIL'}"
      f"   (직후 살아있음={alive1}, 이후={not alive2}, 콜백={len(fired)}회)")

print("\n" + "=" * 62)
print(f"안전 계층: {sum(results)}/{len(results)} PASS")
