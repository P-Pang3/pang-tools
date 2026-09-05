# -*- coding: utf-8 -*-
"""
HP/MP 바 판독 (P2.1).

사냥의 절반은 "지금 내가 얼마나 위험한가"를 아는 것이다. 이걸 모르면
전투 루프는 그냥 클릭 반복일 뿐이고, 죽어도 계속 때린다.

판독 방식은 템플릿 매칭이 아니라 **색 픽셀 비율**이다. 이유가 있다.
  - 바는 계속 길이가 변하므로 고정 이미지로 매칭할 수 없다
  - 숫자 OCR 은 폰트·배경에 민감하고 느리다
  - 색 비율은 바 한 줄만 읽으면 끝나고, 0~1 연속값이 바로 나온다

바 색은 사용자가 고르지 않는다. 영역을 지정하면 그 안에서 가장 두드러진
채도 높은 색을 스스로 찾아 기준으로 삼는다.
"""
try:
    import cv2 as _cv2
    import numpy as _np
    HAS_CV = True
except ImportError:
    HAS_CV = False


class BarSpec:
    """바 하나의 판독 규칙. 설정에 저장된다.

    rect 는 게임 창 클라이언트 영역 기준 상대 좌표다. 창을 옮겨도
    그대로 유효하도록 (P1.1 의 좌표계 정규화가 여기서 값을 한다).
    """

    __slots__ = ("rect", "hsv_lo", "hsv_hi", "vertical", "reversed_")

    def __init__(self, rect=None, hsv_lo=None, hsv_hi=None,
                 vertical=False, reversed_=False):
        self.rect = tuple(rect) if rect else None    # (x, y, w, h) 클라이언트 상대
        self.hsv_lo = tuple(hsv_lo) if hsv_lo else None
        self.hsv_hi = tuple(hsv_hi) if hsv_hi else None
        self.vertical = vertical      # 세로 바인가
        self.reversed_ = reversed_    # 오른쪽(아래)부터 차오르는가

    def valid(self) -> bool:
        return bool(self.rect and self.hsv_lo and self.hsv_hi)

    def to_config(self) -> dict:
        return {
            "rect": list(self.rect) if self.rect else None,
            "hsv_lo": list(self.hsv_lo) if self.hsv_lo else None,
            "hsv_hi": list(self.hsv_hi) if self.hsv_hi else None,
            "vertical": self.vertical,
            "reversed": self.reversed_,
        }

    @classmethod
    def from_config(cls, d):
        if not isinstance(d, dict):
            return cls()
        return cls(d.get("rect"), d.get("hsv_lo"), d.get("hsv_hi"),
                   bool(d.get("vertical", False)),
                   bool(d.get("reversed", False)))


def learn_color(bgr_patch, tolerance=(10, 70, 70)):
    """바 이미지에서 '채워진 부분'의 색 범위를 스스로 찾는다.

    바에는 채워진 색, 빈 배경, 테두리가 섞여 있다. 그중 채워진 색은
    보통 가장 채도가 높고 넓은 면적을 차지한다. 채도 상위 픽셀들의
    색상(Hue) 중앙값을 기준으로 범위를 잡는다.

    반환: (hsv_lo, hsv_hi) 또는 실패 시 (None, None)
    """
    if not HAS_CV or bgr_patch is None or bgr_patch.size == 0:
        return (None, None)

    hsv = _cv2.cvtColor(bgr_patch, _cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]

    # 무채색(테두리·배경)과 너무 어두운 픽셀을 뺀다
    mask = (s > 70) & (v > 60)
    if mask.sum() < 12:
        # 채도가 낮은 바(회색조)라면 밝기만으로 판단한다
        return ((0, 0, 110), (180, 255, 255))

    hues = h[mask]
    # 색상은 원형이라 평균이 위험하다 (0 과 179 가 이웃).
    # 히스토그램에서 가장 많은 구간을 고른다.
    hist = _np.bincount(hues.ravel(), minlength=180)
    peak = int(hist.argmax())

    dh, ds, dv = tolerance
    lo_h = (peak - dh) % 180
    hi_h = (peak + dh) % 180
    s_lo = max(40, int(_np.percentile(s[mask], 10)) - ds)
    v_lo = max(40, int(_np.percentile(v[mask], 10)) - dv)

    # 색상이 0 을 넘어가면 두 구간으로 갈라야 하는데, 그건 read() 에서
    # 처리하도록 lo > hi 인 상태 그대로 넘긴다.
    return ((lo_h, s_lo, v_lo), (hi_h, 255, 255))


def _in_range(hsv, lo, hi):
    """색상이 0 을 감싸는 경우까지 처리하는 inRange."""
    lo = _np.array(lo, _np.uint8)
    hi = _np.array(hi, _np.uint8)
    if lo[0] <= hi[0]:
        return _cv2.inRange(hsv, lo, hi)
    # 빨강처럼 0 을 넘나드는 색 — 두 구간을 합친다
    a = _cv2.inRange(hsv, _np.array([0, lo[1], lo[2]], _np.uint8),
                     _np.array([hi[0], hi[1], hi[2]], _np.uint8))
    b = _cv2.inRange(hsv, _np.array([lo[0], lo[1], lo[2]], _np.uint8),
                     _np.array([179, hi[1], hi[2]], _np.uint8))
    return _cv2.bitwise_or(a, b)


def read_ratio(bgr_patch, spec: BarSpec):
    """바 이미지에서 채워진 비율(0.0~1.0)을 읽는다. 실패하면 None.

    '채워진 열의 개수'를 센다. 픽셀 총량이 아니라 열 단위로 세는 이유는,
    바 안에 광택·무늬가 있어도 열 하나가 조금이라도 차 있으면 그 열은
    채워진 것으로 봐야 하기 때문이다.
    """
    if not HAS_CV or bgr_patch is None or bgr_patch.size == 0:
        return None
    if not spec.hsv_lo or not spec.hsv_hi:
        return None

    hsv = _cv2.cvtColor(bgr_patch, _cv2.COLOR_BGR2HSV)
    mask = _in_range(hsv, spec.hsv_lo, spec.hsv_hi)

    # 세로 바면 돌려서 같은 코드로 처리한다
    if spec.vertical:
        mask = mask.T

    rows, cols = mask.shape
    if cols == 0 or rows == 0:
        return None

    # 각 열에서 채워진 픽셀이 30% 이상이면 그 열은 채워진 것
    filled = (mask > 0).sum(axis=0) >= max(1, rows * 0.3)
    if spec.reversed_:
        filled = filled[::-1]

    # 왼쪽부터 연속으로 채워진 길이 — 중간에 끊긴 뒤의 잔여물은 무시한다
    run = 0
    for f in filled:
        if not f:
            break
        run += 1

    # 연속 구간이 거의 없는데 전체적으로는 차 있으면 (무늬가 심한 바)
    # 전체 비율로 대체한다
    total = int(filled.sum())
    if run == 0 and total > cols * 0.5:
        run = total

    return max(0.0, min(1.0, run / float(cols)))


class VitalsReader:
    """HP/MP 바를 읽어 PlayerState 를 채운다."""

    def __init__(self, config_getter, log=None):
        self._cfg = config_getter
        self._log = log or (lambda m: None)
        self._warned = False

    def _c(self, key, default):
        try:
            return (self._cfg() or {}).get(key, default)
        except Exception:
            return default

    def specs(self):
        return (BarSpec.from_config(self._c("hp_bar", None)),
                BarSpec.from_config(self._c("mp_bar", None)))

    def enabled(self) -> bool:
        hp, _ = self.specs()
        return hp.valid()

    def read(self, frame_bgr, client_rect, frame_rect):
        """캡처된 프레임에서 HP/MP 비율을 읽는다.

        frame_bgr   : 캡처 이미지
        client_rect : 게임 창 클라이언트 영역 (화면 절대)
        frame_rect  : 이 프레임이 담고 있는 화면 영역 (l, t, w, h)

        반환: (hp_ratio, mp_ratio) — 못 읽으면 각각 None
        """
        if not HAS_CV or frame_bgr is None or not client_rect:
            return (None, None)

        out = []
        for spec in self.specs():
            out.append(self._read_one(spec, frame_bgr, client_rect, frame_rect))
        return tuple(out)

    def _read_one(self, spec, frame_bgr, client_rect, frame_rect):
        if not spec.valid():
            return None
        x, y, w, h = spec.rect
        # 클라이언트 상대 → 화면 절대 → 프레임 안 좌표
        sx = client_rect[0] + x
        sy = client_rect[1] + y
        fx = sx - frame_rect[0]
        fy = sy - frame_rect[1]
        H, W = frame_bgr.shape[:2]
        if fx < 0 or fy < 0 or fx + w > W or fy + h > H:
            # 스캔 ROI 가 바를 포함하지 않는다 — 반경 스캔을 켜면 생긴다
            if not self._warned:
                self._log("⚠  HP/MP 바가 스캔 영역 밖입니다. "
                          "스캔 반경을 0(창 전체)으로 두세요.")
                self._warned = True
            return None
        patch = frame_bgr[fy:fy + h, fx:fx + w]
        return read_ratio(patch, spec)
