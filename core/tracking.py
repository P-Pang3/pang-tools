# -*- coding: utf-8 -*-
"""
대상 추적기 (P1.4).

검출은 프레임마다 새로 나온다. 그것만 보면 "방금 클릭한 그 아이템"과
"옆에 있는 다른 아이템"을 구분할 수 없다. 그래서 검출에 ID 를 붙여
프레임 사이를 이어붙이고, 시도 이력을 기억한다.

이게 없으면 두 가지가 망가진다.
  - 줍기에 실패한 아이템(벽 너머, 다른 사람 소유)을 영원히 다시 클릭한다
  - 화면에 아이템이 여러 개여도 매번 같은 하나만 고른다

성공 판정은 "클릭한 자리에서 사라졌는가"로 한다. 서버 응답을 볼 수 없으므로
이게 화면만으로 얻을 수 있는 가장 확실한 신호다.
"""
import itertools
import time

_ids = itertools.count(1)

PENDING = "대기"
TRIED = "시도함"
BLOCKED = "제외됨"


class Track:
    __slots__ = ("id", "name", "kind", "x", "y", "w", "h", "score",
                 "first_seen", "last_seen", "attempts", "last_attempt",
                 "blocked_until", "state")

    def __init__(self, det):
        self.id = next(_ids)
        self.name = det.name
        self.kind = det.kind
        self.x, self.y = det.x, det.y
        self.w, self.h = det.w, det.h
        self.score = det.score
        now = time.monotonic()
        self.first_seen = now
        self.last_seen = now
        self.attempts = 0
        self.last_attempt = 0.0
        self.blocked_until = 0.0
        self.state = PENDING

    def refresh(self, det):
        self.x, self.y = det.x, det.y
        self.score = det.score
        self.last_seen = time.monotonic()

    @property
    def age(self):
        return time.monotonic() - self.first_seen

    def is_blocked(self):
        return time.monotonic() < self.blocked_until

    def dist_to(self, x, y):
        dx, dy = self.x - x, self.y - y
        return (dx * dx + dy * dy) ** 0.5

    def __repr__(self):
        return f"Track#{self.id}({self.name} @{self.x},{self.y} {self.state})"


class Tracker:
    """검출 목록을 받아 트랙으로 유지하고, 다음에 처리할 대상을 고른다."""

    def __init__(self, config_getter, log=None):
        self._cfg = config_getter
        self._log = log or (lambda m: None)
        self.tracks = []
        # 통계
        self.picked = 0        # 사라짐 = 성공으로 본 횟수
        self.failed = 0        # 시도했는데 계속 남아 있어 포기한 횟수

    def _c(self, key, default):
        try:
            return (self._cfg() or {}).get(key, default)
        except Exception:
            return default

    def reset(self):
        self.tracks.clear()
        self.picked = 0
        self.failed = 0

    # ------------------------------------------------------------------
    def update(self, snapshot):
        """스냅샷의 검출로 트랙을 갱신한다. 사라진 트랙은 결과를 판정하고 버린다."""
        now = time.monotonic()
        match_px = float(self._c("track_match_px", 28))
        lost_after = float(self._c("track_lost_sec", 1.2))
        max_attempts = int(self._c("max_attempts", 3))
        block_sec = float(self._c("block_sec", 20))

        unmatched = list(snapshot.detections)

        # 1) 기존 트랙에 이번 검출을 이어붙인다 (가장 가까운 것끼리)
        for tr in self.tracks:
            best, bd = None, match_px
            for det in unmatched:
                if det.name != tr.name:
                    continue
                d = tr.dist_to(det.x, det.y)
                if d < bd:
                    best, bd = det, d
            if best is not None:
                tr.refresh(best)
                unmatched.remove(best)

        # 2) 이어붙지 못한 검출은 새 트랙
        for det in unmatched:
            self.tracks.append(Track(det))

        # 3) 오래 안 보인 트랙 정리 — 여기서 성공/실패를 판정한다
        alive = []
        for tr in self.tracks:
            if (now - tr.last_seen) <= lost_after:
                alive.append(tr)
                continue
            # 사라졌다
            if tr.attempts > 0:
                # 시도한 뒤 사라졌다 = 주웠다
                self.picked += 1
                self._log(f"✔  주움 [{tr.name}] #{tr.id} "
                          f"(시도 {tr.attempts}회)")
            # 시도한 적 없이 사라진 건 남이 주웠거나 오검출 — 조용히 버린다
        self.tracks = alive

        # 4) 시도 한도를 넘긴 트랙은 일정 시간 제외
        for tr in self.tracks:
            if tr.state == BLOCKED:
                continue
            if tr.attempts >= max_attempts:
                tr.state = BLOCKED
                tr.blocked_until = now + block_sec
                self.failed += 1
                self._log(f"⊘  포기 [{tr.name}] #{tr.id} — "
                          f"{tr.attempts}회 시도해도 남아 있음. "
                          f"{block_sec:.0f}초간 제외")

    # ------------------------------------------------------------------
    def next_target(self, from_x=None, from_y=None):
        """다음에 처리할 트랙. 없으면 None.

        가까운 것부터 — 사람이 줍는 순서이자 이동 시간이 짧은 순서다.
        커서 위치를 모르면 점수가 높은 것부터.
        """
        now = time.monotonic()
        retry_gap = float(self._c("retry_gap_sec", 1.0))

        cands = []
        for tr in self.tracks:
            if tr.is_blocked() or tr.state == BLOCKED:
                continue
            if tr.attempts > 0 and (now - tr.last_attempt) < retry_gap:
                continue     # 방금 클릭했다 — 결과를 기다린다
            cands.append(tr)

        if not cands:
            return None
        if from_x is None:
            return max(cands, key=lambda t: t.score)
        return min(cands, key=lambda t: t.dist_to(from_x, from_y))

    def mark_attempt(self, track):
        track.attempts += 1
        track.last_attempt = time.monotonic()
        track.state = TRIED

    # ------------------------------------------------------------------
    def summary(self) -> str:
        active = sum(1 for t in self.tracks if not t.is_blocked())
        blocked = len(self.tracks) - active
        return (f"추적 {active}개" + (f" (제외 {blocked})" if blocked else "") +
                f" · 주움 {self.picked} · 포기 {self.failed}")
