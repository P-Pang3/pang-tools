# -*- coding: utf-8 -*-
"""
지각 백엔드 인터페이스 (P1.2).

구현체는 두 가지를 약속한다.
  - available() : 지금 이 백엔드를 쓸 수 있는가
  - perceive()  : WorldSnapshot 하나를 만들어 돌려준다

판단 계층은 이 인터페이스만 안다. 화면 백엔드를 메모리 백엔드로 바꾸는 일이
'객체 하나 교체'로 끝나는 이유다.
"""


class TemplateSpec:
    """설정에 저장되는 템플릿 한 줄. 로드된 이미지는 백엔드가 따로 들고 있다."""

    __slots__ = ("name", "file", "threshold", "enabled", "kind")

    def __init__(self, name, file, threshold=0.85, enabled=True, kind="item"):
        self.name = name
        self.file = file
        self.threshold = threshold
        self.enabled = enabled
        self.kind = kind

    @classmethod
    def from_config(cls, d: dict, default_threshold=0.85):
        return cls(
            name=d.get("name", d.get("file", "?")),
            file=d.get("file", ""),
            threshold=float(d.get("threshold", default_threshold)),
            enabled=bool(d.get("enabled", True)),
            kind=d.get("kind", "item"),
        )


class PerceptionBackend:
    """지각 백엔드가 지켜야 할 약속."""

    name = "base"

    def available(self) -> bool:
        """지금 이 백엔드로 관측이 가능한가."""
        return False

    def perceive(self):
        """WorldSnapshot 을 만들어 반환한다. 실패해도 예외를 던지지 않고
        window_ok=False 인 빈 스냅샷을 돌려준다 — 판단 계층이 매번
        try 로 감싸지 않아도 되게."""
        raise NotImplementedError

    def load_templates(self, data_dir, specs):
        """템플릿을 다시 읽는다. 화면 백엔드만 의미가 있다."""
        pass

    def close(self):
        """자원 정리."""
        pass

    def diagnostics(self) -> list:
        """시작 시 로그에 남길 진단 문구 목록."""
        return []
