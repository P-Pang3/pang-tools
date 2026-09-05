# -*- coding: utf-8 -*-
"""실제 mss 캡처를 포함한 창 크기별 스캔 비용."""
import sys, time
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.perception.screen import ScreenBackend

import tempfile
import cv2, numpy as np

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

# 실제 아이템 PNG 대신 합성 템플릿을 임시 폴더에 만들어 쓴다
DATA = tempfile.mkdtemp(prefix="bench_")
cv2.imwrite(os.path.join(DATA, "tpl.png"), make_template())
SPEC = [{"name": "아이템_1", "file": "tpl.png", "threshold": 0.85, "enabled": True}]

class Win:
    def __init__(self, w, h): self.r = (0, 0, w, h)
    def exists(self): return True
    def is_foreground(self): return True
    def client_rect(self): return self.r
    def monitor_rect(self): return self.r
    def capture_rect(self): return self.r

CFG = {"coarse_scale": 0.5, "coarse_margin": 0.22, "fast_reject": True,
       "max_detections": 12, "scan_radius_px": 0, "default_threshold": 0.85}

print(f"{'게임 창 크기':<18} {'스캔 중앙값':>12} {'최대':>9}   판정")
print("-" * 56)
for (w, h, label) in ((1024, 768, "1024x768"), (1280, 720, "1280x720"),
                      (1600, 900, "1600x900"), (1920, 1080, "1920x1080"),
                      (2560, 1440, "2560x1440 전체")):
    be = ScreenBackend(Win(w, h), lambda: CFG, log=lambda m: None)
    be.load_templates(DATA, SPEC)
    be.perceive()
    xs = []
    for _ in range(14):
        t0 = time.perf_counter(); be.perceive(); xs.append((time.perf_counter()-t0)*1000)
    xs.sort()
    med, mx = xs[len(xs)//2], xs[-1]
    be.close()
    print(f"{label:<18} {med:9.1f}ms {mx:8.1f}ms   {'PASS' if med <= 15 else 'FAIL'}")

# ROI 를 쓰면 얼마나 더 줄어드는지
print()
CFG2 = dict(CFG, scan_radius_px=400)
be = ScreenBackend(Win(2560, 1440), lambda: CFG2, log=lambda m: None)
be.load_templates(DATA, SPEC)
be.perceive()
xs = []
for _ in range(14):
    t0 = time.perf_counter(); be.perceive(); xs.append((time.perf_counter()-t0)*1000)
xs.sort()
print(f"{'2560x1440 + ROI 800px':<26} {xs[len(xs)//2]:6.1f}ms   "
      f"{'PASS' if xs[len(xs)//2] <= 15 else 'FAIL'}")
be.close()
