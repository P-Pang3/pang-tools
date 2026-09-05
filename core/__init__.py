# -*- coding: utf-8 -*-
"""매크로 코어 — 지각 / 판단 / 실행 계층."""

from .geometry import declare_dpi_aware

# DPI 인식은 프로세스당 한 번, 창을 만들기 전에 선언해야 한다.
# core 를 import 하는 순간 걸리므로 진입점이 무엇이든 적용된다.
declare_dpi_aware()
