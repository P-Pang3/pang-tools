# -*- coding: utf-8 -*-
"""P1.3 검출 파이프라인 성능·정확도 측정.

옛 방식(모니터 전체 전수 매칭)과 새 방식(ROI+빠른거부+피라미드+다중검출)을
같은 입력으로 비교한다. 완료 기준은 스캔 1회 15ms 이하.
"""
import sys, time
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cv2, numpy as np
from core.perception.screen import ScreenBackend, imread_unicode
from core.snapshot import WorldSnapshot


def make_template(seed=7, w=35, h=29):
    """벤치마크용 합성 템플릿.

    실제 아이템 PNG 에 기대면 그 파일이 없는 사람은 실행할 수 없다
    (data/ 는 저장소에 올리지 않는다). 구조가 있는 무작위 패턴이면
    매칭 특성은 실제와 비슷하고 아무 데서나 돌아간다.
    """
    r = np.random.default_rng(seed)
    img = r.integers(40, 220, (h, w, 3), dtype=np.uint8)
    img[2:h-2, 2:w-2] = r.integers(0, 255, (h-4, w-4, 3), dtype=np.uint8)
    return img

TPL = make_template()
TH, TW = TPL.shape[:2]

# ---- 2560x1440 게임 화면을 흉내 낸 합성 배경 ----
rng = np.random.default_rng(3)
SCREEN_W, SCREEN_H = 2560, 1440
screen = rng.integers(20, 70, (SCREEN_H, SCREEN_W, 3), dtype=np.uint8)
# 지형처럼 보이도록 큰 얼룩을 얹는다 (균일 노이즈보다 현실적인 매칭 부하)
blob = rng.integers(0, 255, (45, 80, 3), dtype=np.uint8)
blob = cv2.resize(blob, (SCREEN_W, SCREEN_H), interpolation=cv2.INTER_LINEAR)
screen = cv2.addWeighted(screen, 0.5, blob, 0.5, 0)

# 아이템 5개를 서로 다른 위치에 심는다
PLACED = [(300, 250), (900, 640), (1500, 400), (2000, 1100), (700, 1200)]
for (px, py) in PLACED:
    screen[py:py+TH, px:px+TW] = TPL

class FakeShot:
    def __init__(self, bgr): self._a = cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA)
    def __array__(self, dtype=None):
        return self._a if dtype is None else self._a.astype(dtype)

class FakeSct:
    def grab(self, mon):
        l, t, w, h = mon["left"], mon["top"], mon["width"], mon["height"]
        return FakeShot(screen[t:t+h, l:l+w])

class FakeWin:
    def exists(self): return True
    def is_foreground(self): return True
    def client_rect(self): return (0, 0, SCREEN_W, SCREEN_H)
    def monitor_rect(self): return (0, 0, SCREEN_W, SCREEN_H)
    def capture_rect(self): return (0, 0, SCREEN_W, SCREEN_H)

CFG = {
    "coarse_scale": 0.5, "coarse_margin": 0.22, "fast_reject": True,
    "max_detections": 12, "scan_radius_px": 0, "default_threshold": 0.85,
}

be = ScreenBackend(FakeWin(), lambda: CFG, log=lambda m: print("  bk:", m))
be._sct = FakeSct()
import tempfile
_tmpdir = tempfile.mkdtemp(prefix="bench_")
cv2.imwrite(os.path.join(_tmpdir, "tpl.png"), TPL)
be.load_templates(_tmpdir,
    [{"name": "아이템_1", "file": "tpl.png", "threshold": 0.85, "enabled": True}])

def bench(fn, n=12):
    fn()                       # 워밍업
    ts = []
    for _ in range(n):
        t0 = time.perf_counter(); fn(); ts.append((time.perf_counter()-t0)*1000)
    ts.sort()
    return ts[len(ts)//2], min(ts), max(ts)

# ---- 옛 방식: 모니터 전체를 그대로 matchTemplate ----
def old_way():
    shot = FakeSct().grab({"left":0,"top":0,"width":SCREEN_W,"height":SCREEN_H})
    bgr = cv2.cvtColor(np.asarray(shot), cv2.COLOR_BGRA2BGR)
    res = cv2.matchTemplate(bgr, TPL, cv2.TM_CCOEFF_NORMED)
    _, mv, _, ml = cv2.minMaxLoc(res)
    return mv, ml

print("=" * 66)
print("아이템 5개가 있는 화면")
med_o, min_o, max_o = bench(old_way)
print(f"  옛 방식 (전체 전수)  중앙값 {med_o:6.1f}ms  최소 {min_o:6.1f}  최대 {max_o:6.1f}")

snap = be.perceive()
med_n, min_n, max_n = bench(be.perceive)
print(f"  새 방식 (파이프라인) 중앙값 {med_n:6.1f}ms  최소 {min_n:6.1f}  최대 {max_n:6.1f}")
print(f"  → {med_o/med_n:.1f}배 빠름" if med_n > 0 else "")

print(f"\n  검출 개수: {len(snap.detections)}개 (심은 것 {len(PLACED)}개)")
found = sorted((d.x - TW//2, d.y - TH//2) for d in snap.detections)
print(f"  검출 좌표: {found}")
print(f"  심은 좌표: {sorted(PLACED)}")
ok_all = all(min(abs(fx-px)+abs(fy-py) for (fx,fy) in found) <= 2 for (px,py) in PLACED) and len(found)==len(PLACED)
print(f"  전부 정확히 찾음: {ok_all}")

# ---- 아이템이 없을 때 (실사용 시간의 대부분) ----
print("\n" + "=" * 66)
print("아이템이 없는 화면 — 실사용에서 대부분의 시간")
for (px, py) in PLACED:
    screen[py:py+TH, px:px+TW] = cv2.resize(
        blob[py:py+TH, px:px+TW], (TW, TH))
med_o2, _, _ = bench(old_way)
med_n2, _, _ = bench(be.perceive)
snap2 = be.perceive()
print(f"  옛 방식  중앙값 {med_o2:6.1f}ms")
print(f"  새 방식  중앙값 {med_n2:6.1f}ms   (검출 {len(snap2.detections)}개)")
print(f"  → {med_o2/med_n2:.1f}배 빠름" if med_n2 > 0 else "")

print("\n" + "=" * 66)
print(f"완료 기준 (스캔 15ms 이하): "
      f"아이템 있음 {med_n:.1f}ms {'PASS' if med_n <= 15 else 'FAIL'} / "
      f"없음 {med_n2:.1f}ms {'PASS' if med_n2 <= 15 else 'FAIL'}")
print(f"다중 검출 (5개 동시): {'PASS' if ok_all else 'FAIL'}")
