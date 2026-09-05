# -*- coding: utf-8 -*-
"""
WorldSnapshot — 지각 계층과 판단 계층 사이의 유일한 통로 (P1.2).

이 자료구조가 설계의 축이다. 화면 백엔드가 채우든 메모리 백엔드가 채우든
판단 계층이 보는 모양은 같다. 그래서 나중에 메모리 리딩을 붙일 때
판단 코드는 한 줄도 바뀌지 않는다.

여기에 OpenCV 나 Win32 관련 타입이 들어오면 그 목적이 깨진다.
순수 파이썬 값만 담는다.
"""
import time


class Detection:
    """화면에서 찾아낸 관심 대상 하나.

    아이템이든 몬스터든 같은 모양으로 다룬다 (P2 에서 몬스터가 들어올 자리).
    좌표는 화면 절대와 클라이언트 상대를 둘 다 들고 다닌다 — 클릭할 때는
    절대가, 기록·비교할 때는 창 위치와 무관한 상대가 필요하다.
    """

    __slots__ = ("name", "kind", "score", "x", "y", "w", "h", "cx", "cy", "extra")

    def __init__(self, name, score, x, y, w=0, h=0, kind="item",
                 cx=None, cy=None, extra=None):
        self.name = name          # 템플릿 이름
        self.kind = kind          # "item" | "monster" | "ui" ...
        self.score = score        # 0~1 신뢰도
        self.x = x                # 화면 절대 중심 X
        self.y = y                # 화면 절대 중심 Y
        self.w = w                # 검출 폭
        self.h = h                # 검출 높이
        self.cx = cx if cx is not None else x   # 클라이언트 상대 X
        self.cy = cy if cy is not None else y   # 클라이언트 상대 Y
        self.extra = extra or {}

    def dist_to(self, sx, sy) -> float:
        dx, dy = self.x - sx, self.y - sy
        return (dx * dx + dy * dy) ** 0.5

    def overlaps(self, other, tol: float = 0.0) -> bool:
        """두 검출이 같은 대상인지 — 사각형 겹침으로 판정."""
        return (abs(self.x - other.x) * 2 < (self.w + other.w) + tol and
                abs(self.y - other.y) * 2 < (self.h + other.h) + tol)

    def __repr__(self):
        return f"Detection({self.name} {self.score:.3f} @{self.x},{self.y})"


class WorldSnapshot:
    """한 시점의 세계 상태. 지각이 만들고 판단이 읽는다."""

    __slots__ = ("t", "detections", "window_ok", "foreground",
                 "client_rect", "scan_ms", "top_miss", "player", "backend")

    def __init__(self):
        self.t = time.monotonic()
        self.detections = []      # list[Detection] — 점수 내림차순
        self.window_ok = False    # 게임 창을 찾았는가
        self.foreground = False   # 활성 상태인가
        self.client_rect = None   # (l, t, w, h) 화면 절대
        self.scan_ms = 0.0        # 이 스냅샷을 만드는 데 걸린 시간
        self.top_miss = None      # (name, score, threshold) 임계 미달 최고점 — 진단용
        self.player = None        # PlayerState (P2 에서 채운다)
        self.backend = ""         # 어느 백엔드가 만들었는가

    @property
    def age(self) -> float:
        return time.monotonic() - self.t

    def best(self):
        return self.detections[0] if self.detections else None

    def of_kind(self, kind):
        return [d for d in self.detections if d.kind == kind]

    def __repr__(self):
        return (f"WorldSnapshot({len(self.detections)}개 검출, "
                f"{self.scan_ms:.1f}ms, {self.backend})")


class PlayerState:
    """캐릭터 상태 — P2 에서 채워진다. 지금은 자리만 잡아둔다.

    화면 백엔드는 HP 바의 색 픽셀 비율로, 메모리 백엔드는 엔티티 필드에서
    직접 읽는다. 판단 계층은 어느 쪽인지 모른다.
    """

    __slots__ = ("hp", "hp_max", "mp", "mp_max", "x", "y", "level",
                 "alive", "inventory_full")

    def __init__(self):
        self.hp = self.hp_max = None
        self.mp = self.mp_max = None
        self.x = self.y = None
        self.level = None
        self.alive = True
        self.inventory_full = False

    @property
    def hp_ratio(self):
        if not self.hp_max:
            return None
        return max(0.0, min(1.0, self.hp / self.hp_max))

    @property
    def mp_ratio(self):
        if not self.mp_max:
            return None
        return max(0.0, min(1.0, self.mp / self.mp_max))
