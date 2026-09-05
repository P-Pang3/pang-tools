# -*- coding: utf-8 -*-
"""거리에 따라 대기가 늘어나는지 확인."""
import sys, os, math
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.pipeline import Pipeline
from core.snapshot import WorldSnapshot

class T:
    def __init__(self, x, y): self.x, self.y = x, y; self.w = self.h = 40

p = Pipeline(log_dir=None)
p.set_config({"char_travel_enabled": True, "char_speed_px_sec": 300,
              "char_travel_max_ms": 4000, "attack_interval_ms": 1500})
# 화면 1920x1080, 캐릭터는 중앙 (960, 540)
s = WorldSnapshot(); s.client_rect = (0, 0, 1920, 1080)
p._snapshot = s

print("캐릭터는 화면 중앙 (960, 540) · 이동 속도 300 px/초")
print()
print(f"{'대상 위치':<16} {'거리':>7} {'이동 시간':>10} {'다음 공격까지':>14}")
print("-" * 52)
for pos in ((960, 540), (1060, 540), (1260, 540), (1600, 540), (1900, 1050)):
    t = T(*pos)
    dist = math.hypot(pos[0]-960, pos[1]-540)
    travel = p._travel_ms(t)
    total = 1500 + travel
    print(f"  ({pos[0]:4d},{pos[1]:4d})   {dist:7.0f}px {travel:8.0f}ms {total:12.0f}ms")

print()
p.set_config({"char_travel_enabled": False, "char_speed_px_sec": 300,
              "attack_interval_ms": 1500})
p._snapshot = s
print(f"  기능 끄면: {p._travel_ms(T(1900,1050)):.0f}ms (거리 무관)")

# 쿨다운 시작이 밀리는지
from core.combat import CombatPolicy
import time
CFG = {"attack_skills":[{"key":"q","cooldown":3.0}]}
pol = CombatPolicy(lambda: CFG)
pol.note_skill("q", delay_sec=2.0)      # 2초 걸어간 뒤 시전
remain = pol._last_skill["q"] + 3.0 - time.monotonic()
print()
print(f"  쿨다운 3초 스킬 + 이동 2초 -> 다음 사용까지 {remain:.1f}초 (기대 5초)")
print(f"  결과: {'PASS' if 4.8 <= remain <= 5.2 else 'FAIL'}")
