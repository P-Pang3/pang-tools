# -*- coding: utf-8 -*-
"""버프가 설정한 간격을 두고 나가는지 시간으로 확인한다.

버프는 누르는 즉시 걸리지 않는다. 시전이 끝나기 전에 다음 입력이
들어가면 끊기므로, 간격이 실제로 지켜지는지가 중요하다.
반환값으로 넘기면 지터가 붙어 짧아지므로 파이프라인이 직접 기다린다.
"""
import sys, os, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.pipeline import Pipeline
from core.snapshot import WorldSnapshot, PlayerState, Detection

GAP = 0.6      # 테스트는 0.6초로 (실사용 기본은 2초)

class Backend:
    name = "t"
    def available(self): return True
    def diagnostics(self): return []
    def close(self): pass
    def template_count(self): return 1
    def perceive(self):
        s = WorldSnapshot()
        s.window_ok = s.foreground = True
        s.client_rect = (0,0,800,600)
        st = PlayerState(); st.hp, st.hp_max = 0.9, 1.0; st.alive = True
        s.player = st
        s.detections = [Detection("몬", 0.95, 400, 300, 40, 40, kind="monster")]
        return s

events = []
class Hand:
    def __init__(self): self.last_moved_to=(0,0); self._p=(0,0)
    def jittered_ms(self, b): return b
    def sleep_ms(self, ms, ev=None):
        return ev.wait(ms/1000.0) if ev is not None else False
    def hesitate(self, ev=None): return False
    def cursor(self): return self._p
    def move_to(self,x,y,w=24,ev=None):
        self._p=(int(x),int(y)); self.last_moved_to=self._p; return False
    def micro_drift(self, ev=None): return False
    def click(self, ev=None):
        events.append(("click", time.monotonic())); return False
    def press_key(self, k, ev=None):
        events.append((k, time.monotonic())); return False

p = Pipeline(log_dir=None)
p.set_callbacks(log=lambda m: None)
p.set_config({
    "window_lock": False, "rest_cycle_enabled": False, "failsafe_corner": False,
    "pause_on_user_input": False, "stop_when_window_gone": False,
    "jitter_percent": 0, "scan_interval_ms": 50, "click_interval_ms": 200,
    "key_interval_ms": 100000, "combat_enabled": True,
    "buff_enabled": True, "buff_gap_ms": int(GAP*1000),
    "buff_skills": [{"key":"f1","duration":300},
                    {"key":"f2","duration":300},
                    {"key":"f3","duration":300}],
    "attack_skills": [], "hp_potion_key": "", "mp_potion_key": "",
    "hp_halt_percent": 0, "max_snapshot_age_sec": 5,
})
p.set_backend(Backend())
p.hands = Hand(); p.keyhand = Hand()
p.guard._human = p.hands

p.start()
time.sleep(4.0)
p.stop()
time.sleep(0.3)

buffs = [(k,t) for k,t in events if k in ("f1","f2","f3")]
print(f"설정 간격 {GAP}초 · 버프 3개")
print()
if len(buffs) >= 3:
    t0 = buffs[0][1]
    for i,(k,t) in enumerate(buffs[:3]):
        print(f"  {k}  +{t-t0:.2f}초")
    gaps = [buffs[i+1][1]-buffs[i][1] for i in range(2)]
    ok = all(GAP*0.9 <= g <= GAP*1.9 for g in gaps)
    print()
    print(f"  버프 사이 간격: {gaps[0]:.2f}초, {gaps[1]:.2f}초")
    print(f"  결과: {'PASS' if ok else 'FAIL'}  (기대 {GAP}초 이상)")
else:
    print(f"  버프가 {len(buffs)}번만 발생 — FAIL")
first_click = next((t for k,t in events if k=="click"), None)
if first_click and buffs:
    print(f"  첫 공격은 버프 3개 뒤: {first_click > buffs[-1][1]}")
