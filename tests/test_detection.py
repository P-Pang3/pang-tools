# -*- coding: utf-8 -*-
"""D-01 이 새 구조(ScreenBackend)에서도 없는지 확인.

A: 점수 낮음 · 임계 통과   → 검출되어야 한다
B: 점수 높음 · 임계 미통과 → 검출 목록에 없어야 하고 이름을 가로채도 안 된다
"""
import sys, os, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import cv2, numpy as np
from core.perception.screen import ScreenBackend

rng = np.random.default_rng(42)
W, H = 600, 400
screen = rng.integers(0, 90, (H, W, 3), dtype=np.uint8)
pat_a = rng.integers(0, 255, (24, 24, 3), dtype=np.uint8)
pat_b = rng.integers(0, 255, (24, 24, 3), dtype=np.uint8)
POS_A, POS_B = (50, 100), (400, 300)

def degrade(p, amt, seed):
    r = np.random.default_rng(seed)
    return np.clip(p.astype(np.int16) + r.integers(-amt, amt+1, p.shape), 0, 255).astype(np.uint8)

screen[POS_A[1]:POS_A[1]+24, POS_A[0]:POS_A[0]+24] = degrade(pat_a, 90, 1)
screen[POS_B[1]:POS_B[1]+24, POS_B[0]:POS_B[0]+24] = degrade(pat_b, 25, 2)

def score(t):
    r = cv2.matchTemplate(screen, t, cv2.TM_CCOEFF_NORMED)
    _, mv, _, _ = cv2.minMaxLoc(r); return mv
sa, sb = score(pat_a), score(pat_b)
assert sb > sa, "버그 조건 불성립"
thr_a, thr_b = sa - 0.05, sb + 0.02
print(f"A 점수 {sa:.3f} / 임계 {thr_a:.3f} (통과)")
print(f"B 점수 {sb:.3f} / 임계 {thr_b:.3f} (미통과, A 보다 높은 점수)")

d = tempfile.mkdtemp()
cv2.imwrite(os.path.join(d, "a.png"), pat_a)
cv2.imwrite(os.path.join(d, "b.png"), pat_b)

class Shot:
    def __init__(self, b): self._a = cv2.cvtColor(b, cv2.COLOR_BGR2BGRA)
    def __array__(self, dtype=None): return self._a if dtype is None else self._a.astype(dtype)
class Sct:
    def grab(self, m):
        l,t,w,h = m["left"],m["top"],m["width"],m["height"]
        return Shot(screen[t:t+h, l:l+w])
class Win:
    def exists(self): return True
    def is_foreground(self): return True
    def client_rect(self): return (0,0,W,H)
    def monitor_rect(self): return (0,0,W,H)
    def capture_rect(self): return (0,0,W,H)

CFG = {"coarse_scale":0.5,"coarse_margin":0.22,"fast_reject":False,
       "max_detections":12,"scan_radius_px":0}
be = ScreenBackend(Win(), lambda: CFG, log=lambda m: None)
be._sct = Sct()
be.load_templates(d, [
    {"name":"아이템_A","file":"a.png","threshold":thr_a,"enabled":True},
    {"name":"아이템_B","file":"b.png","threshold":thr_b,"enabled":True}])

snap = be.perceive()
print(f"\n검출 {len(snap.detections)}개")
for det in snap.detections:
    print(f"  {det.name}  {det.score:.3f}  @({det.x},{det.y})")

names = [x.name for x in snap.detections]
exp = (POS_A[0]+12, POS_A[1]+12)
ok_one  = len(snap.detections) == 1
ok_name = names == ["아이템_A"]
ok_pos  = ok_one and abs(snap.detections[0].x-exp[0]) <= 2 and abs(snap.detections[0].y-exp[1]) <= 2
print(f"\nA 만 검출됨 : {ok_one and ok_name}")
print(f"좌표 일치   : {ok_pos}  (기대 {exp})")
print("결과:", "PASS" if (ok_one and ok_name and ok_pos) else "FAIL")
