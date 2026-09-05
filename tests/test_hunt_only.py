# -*- coding: utf-8 -*-
"""사냥 모드가 정말 사냥만 하는지 + 시전 시간이 반영되는지."""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.combat import CombatPolicy, ATTACK, PICKUP, IDLE
from core.snapshot import WorldSnapshot, PlayerState, Detection
from core.tracking import Tracker

def scene(items=0, monsters=0, cfg=None):
    s = WorldSnapshot(); s.client_rect = (0,0,1920,1080)
    st = PlayerState(); st.hp, st.hp_max = 0.9, 1.0; st.alive = True
    s.player = st
    d = []
    for i in range(items):
        d.append(Detection(f"아이템{i}", .9, 300+i*40, 300, 20, 20, kind="item"))
    for i in range(monsters):
        d.append(Detection(f"몬스터{i}", .9, 1000+i*40, 500, 40, 40, kind="monster"))
    s.detections = d
    tr = Tracker(lambda: cfg); tr.update(s)
    return s, tr

BASE = {"combat_enabled": True, "hp_potion_key": "", "mp_potion_key": "",
        "hp_halt_percent": 0, "retry_gap_sec": 0, "attack_timeout_sec": 12,
        "attack_skills": [], "buff_enabled": False}

print("1) 사냥 프로그램 (pickup_enabled=False)")
cfg = dict(BASE, pickup_enabled=False)
pol = CombatPolicy(lambda: cfg)
s, tr = scene(items=3, monsters=1, cfg=cfg)
a = pol.decide(s, tr, (0,0))
print(f"   아이템3 + 몬스터1 -> {a.kind}  ({'PASS' if a.kind==ATTACK else 'FAIL'})")

pol.reset()
s, tr = scene(items=3, monsters=0, cfg=cfg)
a = pol.decide(s, tr, (0,0))
print(f"   아이템만 3개     -> {a.kind}  ({'PASS' if a.kind==IDLE else 'FAIL — 주우면 안 됨'})")

print("\n2) 줍기 프로그램 (pickup_enabled=True)")
cfg2 = dict(BASE, pickup_enabled=True, combat_enabled=False)
pol2 = CombatPolicy(lambda: cfg2)
s, tr = scene(items=3, monsters=1, cfg=cfg2)
a = pol2.decide(s, tr, (0,0))
print(f"   아이템3 + 몬스터1 -> {a.kind}  ({'PASS' if a.kind==PICKUP else 'FAIL'})")

print("\n3) 스킬 시전 시간이 쿨다운에 들어가는가")
import time
cfg3 = dict(BASE, pickup_enabled=False,
            attack_skills=[{"key":"q","cooldown":3.0}])
pol3 = CombatPolicy(lambda: cfg3)
pol3.note_skill("q", delay_sec=(1.0 + 1.8))   # 이동 1초 + 시전 1.8초
remain = pol3._last_skill["q"] + 3.0 - time.monotonic()
ok = 5.6 <= remain <= 6.0
print(f"   쿨다운3 + 이동1 + 시전1.8 -> 다음까지 {remain:.1f}초  "
      f"({'PASS' if ok else 'FAIL'}, 기대 5.8초)")
