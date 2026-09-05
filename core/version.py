# -*- coding: utf-8 -*-
"""
버전과 업데이트 대상 저장소.

배포본에는 `app/version.json` 이 함께 들어간다. 그 파일이 있으면 그걸 쓰고,
없으면(= 개발 중 소스에서 바로 실행) 아래 기본값을 쓴다.
"""
import json
from pathlib import Path

# 릴리스할 때 올린다. GitHub 태그도 이 값과 맞춘다 (v 접두어는 붙여도 된다).
VERSION = "1.1.2"

# 업데이트를 받아올 곳. 비워두면 업데이트 기능이 꺼진다.
GITHUB_OWNER = "P-Pang3"
GITHUB_REPO = "pang-tools"

# 이 배포본이 어떤 프로그램인지 — 릴리스 asset 이름을 고르는 데 쓴다
APP_ID = "dev"          # pickup | hunt | autoclick | dev

_LOADED = False


def _load_once():
    """배포본에 심긴 version.json 을 읽는다. 한 번만."""
    global VERSION, GITHUB_OWNER, GITHUB_REPO, APP_ID, _LOADED
    if _LOADED:
        return
    _LOADED = True
    here = Path(__file__).resolve().parent.parent   # app/ 또는 저장소 루트
    for name in ("version.json",):
        p = here / name
        if not p.exists():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            VERSION = str(d.get("version", VERSION))
            GITHUB_OWNER = str(d.get("owner", GITHUB_OWNER))
            GITHUB_REPO = str(d.get("repo", GITHUB_REPO))
            APP_ID = str(d.get("app", APP_ID))
        except Exception:
            pass
        break


def info() -> dict:
    _load_once()
    return {"version": VERSION, "owner": GITHUB_OWNER,
            "repo": GITHUB_REPO, "app": APP_ID}


def current() -> str:
    _load_once()
    return VERSION


def update_enabled() -> bool:
    _load_once()
    return bool(GITHUB_OWNER and GITHUB_REPO)


def parse(v: str):
    """'v1.2.3' -> (1, 2, 3). 비교용. 못 읽으면 (0,)."""
    v = str(v or "").strip().lstrip("vV")
    parts = []
    for chunk in v.split(".")[:4]:
        num = ""
        for ch in chunk:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    return tuple(parts) if parts else (0,)


def is_newer(remote: str, local: str = None) -> bool:
    """remote 가 local 보다 새 버전인가."""
    if local is None:
        local = current()
    return parse(remote) > parse(local)
