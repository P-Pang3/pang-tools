# -*- coding: utf-8 -*-
"""
기록과 통계 (P1.8).

예전에는 로그가 GUI 창에만 있어서 창을 닫으면 사라졌다. 무엇이 언제
잘못됐는지 되짚을 방법이 없었다 (진단 D-12).

여기서 만드는 세션 리포트는 회귀 판정 기준이기도 하다. 계층을 갈아엎은 뒤
시간당 줍기 수가 떨어졌다면 무언가 깨진 것이다.
"""
import time
from collections import deque
from datetime import datetime
from pathlib import Path


class SessionLog:
    """파일 로그 — 날짜별로 나누고 오래된 것은 지운다."""

    def __init__(self, log_dir, keep_days=7):
        self.dir = Path(log_dir)
        self.keep_days = keep_days
        self._fp = None
        self._day = None
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._rotate()
            self._prune()
        except Exception:
            self._fp = None      # 로그를 못 써도 매크로는 돌아야 한다

    def _rotate(self):
        day = datetime.now().strftime("%Y%m%d")
        if day == self._day and self._fp:
            return
        if self._fp:
            try:
                self._fp.close()
            except Exception:
                pass
        self._day = day
        self._fp = open(self.dir / f"macro_{day}.log", "a", encoding="utf-8")

    def _prune(self):
        cutoff = time.time() - self.keep_days * 86400
        for p in self.dir.glob("macro_*.log"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
            except Exception:
                pass

    def write(self, msg: str):
        if self._fp is None:
            return
        try:
            self._rotate()
            stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            self._fp.write(f"[{stamp}] {msg}\n")
            self._fp.flush()
        except Exception:
            pass

    def close(self):
        if self._fp:
            try:
                self._fp.close()
            except Exception:
                pass
            self._fp = None


class Stats:
    """세션 통계. 회귀를 눈으로 확인하는 수단이다."""

    def __init__(self, window=120):
        self.started = time.monotonic()
        self.clicks = 0
        self.keys = 0
        self.picked = 0
        self.given_up = 0
        self.scans = 0
        self.scans_with_hit = 0
        self._scan_ms = deque(maxlen=window)
        self._react_ms = deque(maxlen=window)
        self.paused_sec = 0.0
        self.rest_sec = 0.0

    def reset(self):
        self.__init__()

    # --- 기록 ---
    def note_scan(self, ms, hit):
        self.scans += 1
        if hit:
            self.scans_with_hit += 1
        self._scan_ms.append(ms)

    def note_click(self, react_ms=None):
        self.clicks += 1
        if react_ms is not None:
            self._react_ms.append(react_ms)

    def note_key(self):
        self.keys += 1

    # --- 조회 ---
    @property
    def elapsed(self):
        return max(1e-6, time.monotonic() - self.started)

    @property
    def active_sec(self):
        return max(1e-6, self.elapsed - self.rest_sec - self.paused_sec)

    @property
    def scan_avg_ms(self):
        return sum(self._scan_ms) / len(self._scan_ms) if self._scan_ms else 0.0

    @property
    def scan_max_ms(self):
        return max(self._scan_ms) if self._scan_ms else 0.0

    @property
    def react_avg_ms(self):
        return sum(self._react_ms) / len(self._react_ms) if self._react_ms else 0.0

    @property
    def hit_rate(self):
        return self.scans_with_hit / self.scans if self.scans else 0.0

    @property
    def picks_per_hour(self):
        return self.picked * 3600.0 / self.active_sec

    def report(self) -> str:
        h = int(self.elapsed // 3600)
        m = int(self.elapsed % 3600 // 60)
        s = int(self.elapsed % 60)
        return (
            f"가동 {h:02d}:{m:02d}:{s:02d} · "
            f"주움 {self.picked}개 ({self.picks_per_hour:.1f}/시간) · "
            f"클릭 {self.clicks} · 키 {self.keys}\n"
            f"     스캔 {self.scans}회 · 평균 {self.scan_avg_ms:.1f}ms "
            f"(최대 {self.scan_max_ms:.1f}ms) · 발견율 {self.hit_rate*100:.0f}% · "
            f"평균 반응 {self.react_avg_ms:.0f}ms"
        )

    def brief(self) -> str:
        return (f"주움 {self.picked} · 클릭 {self.clicks} · 키 {self.keys} · "
                f"스캔 {self.scan_avg_ms:.1f}ms · 발견율 {self.hit_rate*100:.0f}%")
