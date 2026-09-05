# -*- coding: utf-8 -*-
"""
경로 해석 — 개발 중일 때와 배포본일 때가 다르다.

    개발 중                      배포본
    trickster_macro/            트릭스터 줍기 매크로/
      main.py                     app/
      core/                         main.py
      data/        ← 옆            core/
                                  data/     ← app 의 형제

**코드와 데이터를 갈라놓은 것이 업데이트의 전제다.** 업데이트는 app/ 을
통째로 갈아끼우므로, data/ 가 그 안에 있으면 사용자가 만든 템플릿과 설정이
매번 날아간다.

여기서 그 차이를 한 곳에 가둔다. 각 프로그램은 `data_dir()` 만 부르면 된다.
"""
from pathlib import Path


def app_dir(module_file) -> Path:
    """실행 중인 코드가 있는 폴더."""
    return Path(module_file).resolve().parent


def is_packaged(module_file) -> bool:
    """배포본으로 실행 중인가 (app/ 안에 있는가)."""
    return app_dir(module_file).name == "app"


def data_dir(module_file) -> Path:
    """설정·템플릿·로그가 들어갈 폴더. 없으면 만든다."""
    here = app_dir(module_file)
    d = here.parent / "data" if here.name == "app" else here / "data"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def program_dir(module_file) -> Path:
    """사용자가 보는 프로그램 폴더 (런처가 있는 곳)."""
    here = app_dir(module_file)
    return here.parent if here.name == "app" else here
