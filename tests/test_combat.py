# -*- coding: utf-8 -*-
"""P2 검증 — HP 바 판독과 전투 우선순위.

우선순위(생존 > 전투 > 줍기)는 협상 대상이 아니다. HP 가 바닥인데
아이템을 주우러 가면 죽는다. 여기서 그게 실제로 지켜지는지 본다.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import cv2

from core.vitals import BarSpec, learn_color, read_ratio
from core.combat import (CombatPolicy, ATTACK, HALT, HEAL_HP, HEAL_MP,
                         IDLE, PICKUP)
from core.snapshot import PlayerState, WorldSnapshot, Detection
from core.tracking import Tracker

results = []


def check(label, ok, extra=""):
    results.append(ok)
    print(f"  {label:<44} {'PASS' if ok else 'FAIL'}  {extra}")


# ==================================================================
print("1) HP 바 판독 — 채워진 비율을 읽는가")
# ==================================================================
def make_bar(fill_ratio, w=200, h=14, color=(40, 40, 220), bg=(35, 35, 40)):
    """왼쪽부터 채워지는 가로 바를 만든다 (BGR)."""
    img = np.full((h, w, 3), bg, np.uint8)
    n = int(w * fill_ratio)
    if n > 0:
        img[:, :n] = color
        # 광택 — 실제 게임 바처럼 위쪽을 밝게
        img[:3, :n] = np.clip(np.array(color) + 45, 0, 255)
    return img


full = make_bar(1.0)
lo, hi = learn_color(full)
check("색 자동 학습", lo is not None, f"HSV {lo} ~ {hi}")

spec = BarSpec((0, 0, 200, 14), lo, hi)
for want in (1.0, 0.75, 0.5, 0.25, 0.0):
    got = read_ratio(make_bar(want), spec)
    ok = got is not None and abs(got - want) <= 0.03
    check(f"  {want*100:3.0f}% 판독", ok,
          f"-> {got*100:.0f}%" if got is not None else "-> None")

# 빨간 바 (색상 0 을 감싸는 경우 — 흔한 함정)
red_full = make_bar(1.0, color=(40, 40, 220))
rlo, rhi = learn_color(red_full)
rspec = BarSpec((0, 0, 200, 14), rlo, rhi)
got = read_ratio(make_bar(0.6, color=(40, 40, 220)), rspec)
check("빨강 계열 (Hue 0 근처)", got is not None and abs(got - 0.6) <= 0.05,
      f"-> {got*100:.0f}%" if got is not None else "-> None")


# ==================================================================
print("\n2) 전투 우선순위 — 생존 > 전투 > 줍기")
# ==================================================================
CFG = {
    "combat_enabled": True,
    "hp_potion_key": "1", "hp_potion_percent": 50,
    "mp_potion_key": "2", "mp_potion_percent": 30,
    "hp_halt_percent": 15, "potion_cooldown_sec": 0.0,
    "attack_timeout_sec": 12, "retry_gap_sec": 0.0,
}


def scene(hp=None, mp=None, items=0, monsters=0, alive=True):
    """스냅샷 + 추적기를 만든다."""
    snap = WorldSnapshot()
    snap.client_rect = (0, 0, 1024, 768)
    if hp is not None or mp is not None:
        st = PlayerState()
        if hp is not None:
            st.hp, st.hp_max = hp, 1.0
        if mp is not None:
            st.mp, st.mp_max = mp, 1.0
        st.alive = alive
        snap.player = st
    dets = []
    for i in range(items):
        dets.append(Detection(f"아이템{i}", 0.9, 300 + i * 40, 300, 20, 20,
                              kind="item"))
    for i in range(monsters):
        dets.append(Detection(f"몬스터{i}", 0.9, 600 + i * 40, 400, 40, 40,
                              kind="monster"))
    snap.detections = dets
    tr = Tracker(lambda: CFG)
    tr.update(snap)
    return snap, tr


pol = CombatPolicy(lambda: CFG)

snap, tr = scene(hp=0.9, items=1, monsters=1)
a = pol.decide(snap, tr, (0, 0))
check("HP 충분 + 몬스터 있음 -> 공격", a.kind == ATTACK, f"({a.kind})")

pol.reset()
snap, tr = scene(hp=0.4, items=1, monsters=1)
a = pol.decide(snap, tr, (0, 0))
check("HP 40% -> 물약이 전투보다 먼저", a.kind == HEAL_HP, f"({a.kind})")

pol.reset()
snap, tr = scene(hp=0.1, items=1, monsters=1)
a = pol.decide(snap, tr, (0, 0))
check("HP 10% -> 위험 정지", a.kind == HALT, f"({a.reason})")

pol.reset()
snap, tr = scene(hp=0.9, mp=0.2, monsters=1)
a = pol.decide(snap, tr, (0, 0))
check("MP 20% -> MP 물약", a.kind == HEAL_MP, f"({a.kind})")

pol.reset()
snap, tr = scene(hp=0.9, items=2, monsters=0)
a = pol.decide(snap, tr, (0, 0))
check("몬스터 없음 -> 줍기", a.kind == PICKUP, f"({a.kind})")

pol.reset()
snap, tr = scene(hp=0.9, alive=False, items=1, monsters=1)
a = pol.decide(snap, tr, (0, 0))
check("사망 -> 정지", a.kind == HALT, f"({a.reason})")

# 사냥 끄면 몬스터가 있어도 줍기만
pol.reset()
CFG["combat_enabled"] = False
snap, tr = scene(hp=0.9, items=1, monsters=1)
a = pol.decide(snap, tr, (0, 0))
check("사냥 OFF -> 몬스터 무시하고 줍기", a.kind == PICKUP, f"({a.kind})")
CFG["combat_enabled"] = True


# ==================================================================
print("\n3) 교전 유지 — 한 대상을 끝까지 때리는가")
# ==================================================================
pol.reset()
snap, tr = scene(hp=0.9, monsters=3)
first = pol.decide(snap, tr, (0, 0))
same = 0
for _ in range(5):
    tr.update(snap)                      # 같은 장면이 계속 보인다
    a = pol.decide(snap, tr, (0, 0))
    if a.kind == ATTACK and a.target is not None and \
            a.target.id == first.target.id:
        same += 1
check("같은 대상을 계속 공격", same == 5, f"{same}/5")

# 물약 쿨다운
CFG["potion_cooldown_sec"] = 5.0
pol.reset()
snap, tr = scene(hp=0.4, monsters=1)
a1 = pol.decide(snap, tr, (0, 0))
pol.note_heal(a1.key)
a2 = pol.decide(snap, tr, (0, 0))
check("물약 쿨다운 중에는 재사용 안 함",
      a1.kind == HEAL_HP and a2.kind != HEAL_HP, f"({a1.kind} -> {a2.kind})")

print("\n" + "=" * 62)
print(f"P2 전투: {sum(results)}/{len(results)} PASS")


# ==================================================================
print("\n4) 스킬 공격 — 스킬키를 누른 뒤 클릭한다")
# ==================================================================
CFG["attack_skills"] = [
    {"key": "q", "cooldown": 0.0},
    {"key": "w", "cooldown": 0.0},
]
pol.reset()
snap, tr = scene(hp=0.9, monsters=1)
a = pol.decide(snap, tr, (0, 0))
check("공격에 스킬이 실린다", a.kind == ATTACK and a.skill in ("q", "w"),
      f"skill={a.skill}")

# 순환 — 같은 스킬만 반복하지 않는다
pol.reset()
used = []
for _ in range(4):
    tr.update(snap)
    a = pol.decide(snap, tr, (0, 0))
    if a.kind == ATTACK:
        used.append(a.skill)
        pol.note_skill(a.skill)
check("두 스킬을 번갈아 쓴다", used[:4] == ["q", "w", "q", "w"], f"{used}")

# 쿨다운 — 다 돌면 평타
CFG["attack_skills"] = [{"key": "q", "cooldown": 60.0}]
pol.reset()
tr.update(snap)
a1 = pol.decide(snap, tr, (0, 0))
pol.note_skill(a1.skill)
tr.update(snap)
a2 = pol.decide(snap, tr, (0, 0))
check("쿨다운 중이면 평타(스킬 없음)",
      a1.skill == "q" and a2.skill is None, f"{a1.skill} -> {a2.skill}")

# 스킬 미설정이면 평타
CFG["attack_skills"] = []
pol.reset()
tr.update(snap)
a = pol.decide(snap, tr, (0, 0))
check("스킬 미설정 -> 평타", a.kind == ATTACK and a.skill is None,
      f"skill={a.skill}")

print("\n" + "=" * 62)
print(f"전체: {sum(results)}/{len(results)} PASS")


# ==================================================================
print("\n5) 버프 자동 유지")
# ==================================================================
from core.combat import BUFF

CFG["attack_skills"] = []
CFG["buff_enabled"] = True
CFG["buff_skills"] = [{"key": "f1", "duration": 300},
                      {"key": "f2", "duration": 600}]
CFG["buff_margin_sec"] = 5

pol.reset()
snap, tr = scene(hp=0.9, monsters=1)
a = pol.decide(snap, tr, (0, 0))
check("시작하면 먼저 버프를 건다", a.kind == BUFF and a.key == "f1",
      f"{a.kind} {a.key}")
pol.note_buff("f1")

a = pol.decide(snap, tr, (0, 0))
check("두 번째 버프도 건다", a.kind == BUFF and a.key == "f2", f"{a.key}")
pol.note_buff("f2")

tr.update(snap)
a = pol.decide(snap, tr, (0, 0))
check("버프가 다 걸리면 전투로", a.kind == ATTACK, f"{a.kind}")

# 지속 시간이 지나면 다시
pol._last_buff["f1"] = time.monotonic() - 296   # 300 - margin 5 = 295 경과
tr.update(snap)
a = pol.decide(snap, tr, (0, 0))
check("지속 시간 끝나기 전에 다시 건다", a.kind == BUFF and a.key == "f1",
      f"{a.kind} {a.key}")

# 생존이 버프보다 우선
pol.reset()
snap, tr = scene(hp=0.3, monsters=1)
a = pol.decide(snap, tr, (0, 0))
check("HP 낮으면 버프보다 물약이 먼저", a.kind == HEAL_HP, f"{a.kind}")

# 버프를 끄면 무시
pol.reset()
CFG["buff_enabled"] = False
snap, tr = scene(hp=0.9, monsters=1)
a = pol.decide(snap, tr, (0, 0))
check("버프 끄면 바로 전투", a.kind == ATTACK, f"{a.kind}")
CFG["buff_enabled"] = False
CFG["buff_skills"] = []

print("\n" + "=" * 62)
print(f"전체: {sum(results)}/{len(results)} PASS")
