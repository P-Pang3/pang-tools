# -*- coding: utf-8 -*-
"""
MacroEngine — GUI 와 코어 계층 사이의 얇은 어댑터.

v4 에서 실제 동작은 core/ 아래로 옮겨갔다. 이 파일은 기존 GUI 가 알던
이름과 호출 방식을 그대로 유지해 main.py 를 흔들지 않기 위해 남는다.

  core.pipeline    네 개의 루프 (지각 / 행동 / 키 / 감시)
  core.perception  화면 백엔드 — ROI · 빠른 거부 · 피라미드 · 다중 검출
  core.tracking    대상 추적 — 시도 이력과 성공 판정
  core.actuation   인간형 입력 — 지연 분포 · Fitts 이동 · 오버슛
  core.safety      페일세이프 · 사용자 개입 감지 · 워치독
  core.telemetry   파일 로그 · 세션 통계
"""
from pathlib import Path

from core import geometry, paths
from core.perception.screen import ScreenBackend, HAS_CV
from core.pipeline import Pipeline

# DPI 인식은 창을 만들기 전에 선언해야 한다. 이 모듈은 GUI 보다 먼저
# 로드되므로 여기서 걸어두면 진입점이 무엇이든 적용된다.
geometry.declare_dpi_aware()


class MacroEngine:
    def __init__(self, log_dir=None):
        if log_dir is None:
            log_dir = paths.data_dir(__file__) / "logs"
        self._pipe = Pipeline(log_dir=log_dir)
        self._backend = ScreenBackend(
            self._pipe.window, self._pipe._cfg, self._pipe._log)
        self._pipe.set_backend(self._backend)
        self._data_dir = None
        self._specs = []

    # ---------------- 기존 API ----------------
    def set_config(self, cfg: dict):
        self._pipe.set_config(cfg)

    def set_callbacks(self, log=None, status=None, phase=None):
        self._pipe.set_callbacks(log=log, status=status, phase=phase)

    def is_running(self) -> bool:
        return self._pipe.is_running()

    def load_templates(self, data_dir, template_configs: list):
        self._data_dir = data_dir
        self._specs = template_configs or []
        self._backend.load_templates(data_dir, self._specs)

    def start(self):
        self._pipe.start()

    def stop(self):
        self._pipe.stop()

    def toggle(self):
        self._pipe.toggle()

    def phase_remaining(self) -> tuple:
        return self._pipe.phase_remaining()

    # ---------------- v4 에서 추가 ----------------
    def shutdown(self):
        self._pipe.shutdown()

    def pause_reason(self) -> str:
        return self._pipe.pause_reason()

    @property
    def stats(self):
        return self._pipe.stats

    @property
    def tracker(self):
        return self._pipe.tracker

    @property
    def window(self):
        return self._pipe.window

    @property
    def backend(self):
        return self._backend

    def snapshot(self):
        """최신 관측. 디버그 오버레이가 쓴다."""
        return self._pipe._latest()

    def report(self) -> str:
        return self._pipe.stats.report()
