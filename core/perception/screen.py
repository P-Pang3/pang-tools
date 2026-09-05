# -*- coding: utf-8 -*-
"""
화면 지각 백엔드 — 검출 파이프라인 (P1.2 / P1.3).

네 단계를 쌓는다. 각 단계가 다음 단계의 입력을 줄이는 구조라서,
아이템이 화면에 없는 대부분의 시간에는 1~2단계에서 끝난다.

  1. ROI 제한   창 클라이언트 영역만, 옵션으로 캐릭터 중심 반경만
  2. 빠른 거부  템플릿의 대표 색이 화면에 아예 없으면 매칭을 통째로 건너뛴다
  3. 2단 피라미드  1/2 축소본에서 후보를 잡고, 그 주변만 원본으로 정밀 매칭
  4. 다중 검출  임계값 이상을 전부 모으고 비최대 억제로 중복을 합친다

예전 구현은 매 주기 모니터 전체를 템플릿 수만큼 전수 매칭했다 (진단 D-04).
"""
import time
from pathlib import Path

from ..geometry import Frame, clamp_rect
from ..snapshot import Detection, PlayerState, WorldSnapshot
from ..vitals import VitalsReader
from .base import PerceptionBackend, TemplateSpec

try:
    import mss as _mss
    import cv2 as _cv2
    import numpy as _np
    HAS_CV = True
except ImportError:
    HAS_CV = False


def imread_unicode(path):
    """한글이 든 경로에서도 이미지를 읽는다.

    cv2.imread 는 내부적으로 ANSI 파일 API 를 쓰기 때문에 경로에 비ASCII
    문자가 있으면 조용히 None 을 돌려준다. 예외도 안 나고 로그도 없다.
    이 프로젝트의 경로에는 '트릭스터 개발' 이 들어 있어서 실제로 템플릿이
    하나도 로드되지 않았다. 파일을 직접 읽어 메모리에서 디코드하면 우회된다.
    """
    try:
        buf = _np.fromfile(str(path), dtype=_np.uint8)
        if buf.size == 0:
            return None
        return _cv2.imdecode(buf, _cv2.IMREAD_COLOR)
    except Exception:
        return None


class _Template:
    """로드된 템플릿 하나 — 원본, 축소본, 그리고 빠른 거부용 색 통계."""

    __slots__ = ("name", "kind", "threshold", "img", "small", "gray", "w", "h",
                 "hsv_lo", "hsv_hi", "min_pixels", "usable_small")

    def __init__(self, name, kind, threshold, img, coarse_scale):
        self.name = name
        self.kind = kind
        self.threshold = threshold
        self.img = img
        self.h, self.w = img.shape[:2]

        # 축소본 — 너무 작아지면 매칭이 불안정해지므로 최소 크기를 지킨다.
        sw, sh = int(self.w * coarse_scale), int(self.h * coarse_scale)
        self.usable_small = sw >= 8 and sh >= 8
        self.small = (_cv2.resize(img, (sw, sh), interpolation=_cv2.INTER_AREA)
                      if self.usable_small else None)
        # 1차 스캔은 그레이스케일로 한다 — 실측 3배 빠르고 위치 오차는 0이었다.
        # 색 판별은 빠른 거부 단계(HSV)와 정밀 매칭(컬러)이 맡는다.
        self.gray = (_cv2.cvtColor(self.small, _cv2.COLOR_BGR2GRAY)
                     if self.small is not None else None)

        # 빠른 거부용 색 범위 — 템플릿 픽셀의 HSV 분포에서 뽑는다.
        # 여유를 넉넉히 준다. 여기서 거르는 건 '확실히 없을 때'뿐이어야 한다.
        hsv = _cv2.cvtColor(img, _cv2.COLOR_BGR2HSV)
        flat = hsv.reshape(-1, 3).astype(_np.int16)
        lo = _np.percentile(flat, 5, axis=0)
        hi = _np.percentile(flat, 95, axis=0)
        pad = _np.array([12, 60, 60])
        self.hsv_lo = _np.clip(lo - pad, 0, 255).astype(_np.uint8)
        self.hsv_hi = _np.clip(hi + pad, 0, 255).astype(_np.uint8)
        # 템플릿 넓이의 일부라도 그 색이 있어야 매칭할 가치가 있다
        self.min_pixels = max(6, int(self.w * self.h * coarse_scale ** 2 * 0.15))


class ScreenBackend(PerceptionBackend):
    name = "screen"

    def __init__(self, window, config_getter, log=None):
        """
        window        : core.window.GameWindow
        config_getter : 설정 dict 를 돌려주는 호출가능 객체 (실시간 반영용)
        """
        self._win = window
        self._cfg = config_getter
        self._log = log or (lambda m: None)
        self._templates = []
        self._sct = None
        self._last_scan_ms = 0.0
        self._vitals = VitalsReader(config_getter, log)

    # ------------------------------------------------------------------
    def available(self) -> bool:
        return HAS_CV

    def diagnostics(self) -> list:
        out = []
        if not HAS_CV:
            out.append("⚠  opencv/mss 없음 — 템플릿 스캔 불가. "
                       "pip install opencv-python mss numpy")
        if not self._templates and HAS_CV:
            out.append("⚠  로드된 템플릿이 없습니다 — 템플릿 탭에서 추가하세요.")
        return out

    def close(self):
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                pass
            self._sct = None

    # ------------------------------------------------------------------
    def _c(self, key, default):
        try:
            return (self._cfg() or {}).get(key, default)
        except Exception:
            return default

    def _get_sct(self):
        """mss 인스턴스를 재사용한다 (P0.3). 지각 스레드 전용이라 락이 필요 없다."""
        if self._sct is None:
            self._sct = _mss.mss()
        return self._sct

    # ------------------------------------------------------------------
    def load_templates(self, data_dir, specs):
        if not HAS_CV:
            self._templates = []
            return
        coarse = float(self._c("coarse_scale", 0.5))
        loaded = []
        for sp in specs:
            if isinstance(sp, dict):
                sp = TemplateSpec.from_config(
                    sp, float(self._c("default_threshold", 0.85)))
            if not sp.enabled:
                continue
            path = Path(data_dir) / sp.file
            if not path.exists():
                self._log(f"⚠  템플릿 파일 없음: {path.name}")
                continue
            img = imread_unicode(path)
            if img is None:
                self._log(f"⚠  템플릿 로드 실패: {path.name}")
                continue
            thr = max(0.30, min(1.0, float(sp.threshold)))
            try:
                loaded.append(_Template(sp.name, sp.kind, thr, img, coarse))
            except Exception as e:
                self._log(f"⚠  템플릿 준비 실패 [{sp.name}]: {e}")
        self._templates = loaded
        if loaded:
            small_off = [t.name for t in loaded if not t.usable_small]
            msg = f"📌  템플릿 {len(loaded)}개 로드"
            if small_off:
                msg += f" (작아서 정밀 매칭만: {', '.join(small_off)})"
            self._log(msg)

    def template_count(self) -> int:
        return len(self._templates)

    # ------------------------------------------------------------------
    # 1단계 — ROI
    # ------------------------------------------------------------------
    def _scan_rect(self):
        """이번에 캡처할 화면 영역. 없으면 None."""
        base = self._win.capture_rect()
        if not base:
            return None
        radius = int(self._c("scan_radius_px", 0))
        if radius <= 0:
            return base
        # 캐릭터 중심 반경만 — 화면 중앙을 캐릭터 위치로 본다.
        # (메모리 백엔드가 붙으면 실제 좌표로 바꾼다)
        l, t, w, h = base
        cx, cy = l + w // 2, t + h // 2
        off_x = int(self._c("scan_center_dx", 0))
        off_y = int(self._c("scan_center_dy", 0))
        return clamp_rect(cx + off_x - radius, cy + off_y - radius,
                          radius * 2, radius * 2, base)

    def _grab(self, rect):
        sct = self._get_sct()
        mon = {"left": rect[0], "top": rect[1],
               "width": rect[2], "height": rect[3]}
        shot = sct.grab(mon)
        return _cv2.cvtColor(_np.asarray(shot), _cv2.COLOR_BGRA2BGR)

    # ------------------------------------------------------------------
    # 2단계 — 빠른 거부
    # ------------------------------------------------------------------
    @staticmethod
    def _color_present(hsv_img, tpl) -> bool:
        mask = _cv2.inRange(hsv_img, tpl.hsv_lo, tpl.hsv_hi)
        return _cv2.countNonZero(mask) >= tpl.min_pixels

    # ------------------------------------------------------------------
    # 3·4단계 — 피라미드 + 다중 검출
    # ------------------------------------------------------------------
    def _match_template(self, full, small, small_gray, tpl, coarse, margin):
        """한 템플릿의 검출 목록을 만든다. 좌표는 full(원본 ROI) 기준."""
        hits = []
        top = -1.0

        use_pyramid = (tpl.usable_small and small_gray is not None and
                       small_gray.shape[0] >= tpl.gray.shape[0] and
                       small_gray.shape[1] >= tpl.gray.shape[1])

        if use_pyramid:
            res = _cv2.matchTemplate(small_gray, tpl.gray, _cv2.TM_CCOEFF_NORMED)
            if res.size:
                top = float(res.max())
            # 축소본은 정보가 줄어 점수가 낮게 나온다. 여유를 두고 후보를 넓게 잡고,
            # 진짜 판정은 원본 정밀 매칭에 맡긴다.
            coarse_thr = max(0.20, tpl.threshold - margin)
            ys, xs = _np.where(res >= coarse_thr)
            if len(xs) == 0:
                return hits, top

            # 후보가 너무 많으면 상위 몇 개만 — 노이즈 화면에서 폭주 방지
            cand = list(zip(xs.tolist(), ys.tolist()))
            if len(cand) > 60:
                cand.sort(key=lambda p: -res[p[1], p[0]])
                cand = cand[:60]

            pad = 4
            seen = set()
            for sx, sy in cand:
                # 축소 좌표 → 원본 좌표, 주변만 잘라 정밀 매칭
                ox, oy = int(sx / coarse), int(sy / coarse)
                key = (ox // 8, oy // 8)      # 인접 후보 중복 제거
                if key in seen:
                    continue
                seen.add(key)

                x0 = max(0, ox - pad)
                y0 = max(0, oy - pad)
                x1 = min(full.shape[1], ox + tpl.w + pad)
                y1 = min(full.shape[0], oy + tpl.h + pad)
                if x1 - x0 < tpl.w or y1 - y0 < tpl.h:
                    continue
                sub = full[y0:y1, x0:x1]
                r2 = _cv2.matchTemplate(sub, tpl.img, _cv2.TM_CCOEFF_NORMED)
                if not r2.size:
                    continue
                _, mv, _, ml = _cv2.minMaxLoc(r2)
                if mv > top:
                    top = float(mv)
                if mv >= tpl.threshold:
                    hits.append((float(mv), x0 + ml[0], y0 + ml[1]))
        else:
            # 축소가 불가능한 작은 템플릿 — 원본에서 바로 전수 매칭
            if (full.shape[0] < tpl.h or full.shape[1] < tpl.w):
                return hits, top
            res = _cv2.matchTemplate(full, tpl.img, _cv2.TM_CCOEFF_NORMED)
            if res.size:
                top = float(res.max())
            ys, xs = _np.where(res >= tpl.threshold)
            for x, y in zip(xs.tolist(), ys.tolist()):
                hits.append((float(res[y, x]), x, y))

        return hits, top

    @staticmethod
    def _nms(dets, iou_tol=0.0):
        """비최대 억제 — 같은 대상에 겹쳐 잡힌 검출을 하나로 합친다."""
        dets.sort(key=lambda d: -d.score)
        kept = []
        for d in dets:
            if not any(d.overlaps(k, iou_tol) for k in kept):
                kept.append(d)
        return kept

    # ------------------------------------------------------------------
    def perceive(self) -> WorldSnapshot:
        snap = WorldSnapshot()
        snap.backend = self.name
        t0 = time.perf_counter()

        if not HAS_CV:
            return snap

        try:
            snap.window_ok = self._win.exists()
            snap.foreground = self._win.is_foreground()
            snap.client_rect = self._win.client_rect()

            cr_pre = snap.client_rect
            rect = self._scan_rect()
            if rect is None or (not self._templates
                                and not self._vitals.enabled()):
                snap.scan_ms = (time.perf_counter() - t0) * 1000.0
                return snap

            full = self._grab(rect)

            # 상태 판독 — 캡처한 프레임을 그대로 재사용한다.
            # 바를 따로 캡처하면 화면이 한 번 더 굳어 시점이 어긋난다.
            if self._vitals.enabled() and cr_pre:
                st = PlayerState()
                hp, mp = self._vitals.read(full, cr_pre, rect)
                if hp is not None:
                    st.hp, st.hp_max = hp, 1.0
                if mp is not None:
                    st.mp, st.mp_max = mp, 1.0
                if hp is not None:
                    st.alive = hp > float(self._c("death_hp_percent", 0)) / 100.0
                snap.player = st

            coarse = float(self._c("coarse_scale", 0.5))
            margin = float(self._c("coarse_margin", 0.22))
            fast_reject = bool(self._c("fast_reject", True))
            max_hits = int(self._c("max_detections", 12))

            small = small_gray = None
            if coarse < 1.0:
                small = _cv2.resize(full, None, fx=coarse, fy=coarse,
                                    interpolation=_cv2.INTER_AREA)
                small_gray = _cv2.cvtColor(small, _cv2.COLOR_BGR2GRAY)

            hsv_small = None
            if fast_reject:
                src = small if small is not None else full
                hsv_small = _cv2.cvtColor(src, _cv2.COLOR_BGR2HSV)

            if not self._templates:
                snap.scan_ms = (time.perf_counter() - t0) * 1000.0
                return snap

            frame = Frame(rect[0], rect[1], rect[2], rect[3], 1.0)
            cr = snap.client_rect
            dets = []
            best_miss = None

            for tpl in self._templates:
                # 2단계 — 색이 아예 없으면 이 템플릿은 건너뛴다
                if fast_reject and hsv_small is not None:
                    if not self._color_present(hsv_small, tpl):
                        continue

                hits, top = self._match_template(
                    full, small, small_gray, tpl, coarse, margin)

                if not hits:
                    if best_miss is None or top > best_miss[1]:
                        best_miss = (tpl.name, top, tpl.threshold)
                    continue

                for score, hx, hy in hits:
                    sx, sy = frame.to_screen(hx + tpl.w / 2.0, hy + tpl.h / 2.0)
                    if cr:
                        cxr, cyr = sx - cr[0], sy - cr[1]
                    else:
                        cxr, cyr = sx, sy
                    dets.append(Detection(
                        name=tpl.name, score=score, x=sx, y=sy,
                        w=tpl.w, h=tpl.h, kind=tpl.kind, cx=cxr, cy=cyr))

            snap.detections = self._nms(dets)[:max_hits]
            if not snap.detections:
                snap.top_miss = best_miss

        except Exception as e:
            self._log(f"⚠  스캔 오류: {e}")

        snap.scan_ms = (time.perf_counter() - t0) * 1000.0
        self._last_scan_ms = snap.scan_ms
        return snap
