# -*- coding: utf-8 -*-
"""
프로필 (P1.9).

사냥터마다 필요한 것이 다르다. 어떤 맵은 아이템이 어두운 배경에 떨어져서
임계값을 낮춰야 하고, 어떤 맵은 화면이 밝아 반대다. 템플릿도 다르다.

설정 한 벌을 통째로 저장해두고 이름으로 꺼내 쓴다. 템플릿 PNG 파일 자체는
data/ 에 그대로 두고 목록만 프로필에 담는다 — 같은 템플릿을 여러 프로필에서
공유하기 위해서다.
"""
import json
import re
from pathlib import Path

# 프로필에 담지 않는 것 — 사냥터와 무관하게 사람이 한 번 정하는 값들
_GLOBAL_KEYS = {
    "hotkey_toggle", "hotkey_stop",
    "failsafe_corner", "failsafe_margin_px",
    "pause_on_user_input", "user_move_tolerance_px", "user_pause_sec",
    "stop_when_window_gone", "window_gone_grace_sec",
    "max_consecutive_failures",
}

_SAFE_NAME = re.compile(r"[^\w가-힣 _\-.]", re.UNICODE)


class ProfileStore:
    def __init__(self, base_dir):
        self.dir = Path(base_dir)
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    @staticmethod
    def safe_name(name: str) -> str:
        name = _SAFE_NAME.sub("", (name or "").strip())
        return name[:40] or "이름없음"

    def path_for(self, name: str) -> Path:
        return self.dir / f"{self.safe_name(name)}.json"

    def list(self) -> list:
        try:
            return sorted(p.stem for p in self.dir.glob("*.json"))
        except Exception:
            return []

    def exists(self, name: str) -> bool:
        return self.path_for(name).exists()

    def save(self, name: str, config: dict) -> str:
        """현재 설정을 프로필로 저장한다. 전역 설정은 빼고 담는다."""
        data = {k: v for k, v in (config or {}).items() if k not in _GLOBAL_KEYS}
        p = self.path_for(name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return p.stem

    def load(self, name: str) -> dict:
        """프로필을 읽는다. 없으면 빈 dict."""
        p = self.path_for(name)
        if not p.exists():
            return {}
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def delete(self, name: str) -> bool:
        p = self.path_for(name)
        try:
            if p.exists():
                p.unlink()
                return True
        except Exception:
            pass
        return False

    def apply(self, name: str, config: dict) -> int:
        """프로필을 현재 설정 위에 덮어쓴다. 반영된 키 개수를 돌려준다.

        config 를 새 dict 로 바꾸지 않고 제자리에서 갱신한다 —
        엔진이 같은 객체를 참조하고 있기 때문이다.
        """
        data = self.load(name)
        if not data:
            return 0
        n = 0
        for k, v in data.items():
            if k in _GLOBAL_KEYS:
                continue
            config[k] = v
            n += 1
        return n
