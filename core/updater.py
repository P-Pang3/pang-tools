# -*- coding: utf-8 -*-
"""
GitHub 릴리스로 자동 업데이트 (확인 → 승인 → 적용).

배포본은 이렇게 생겼다.

    프로그램폴더/
      실행.bat
      app/          ← 코드. 업데이트가 통째로 갈아끼운다
        version.json
      data/         ← 설정·템플릿·로그. 절대 건드리지 않는다

**코드와 데이터를 나눈 것이 핵심이다.** 이게 없으면 업데이트할 때마다
사용자가 만든 템플릿과 설정이 날아간다.

교체는 앱이 직접 하지 않는다. 실행 중인 폴더를 스스로 지울 수 없으므로,
작은 배치 파일을 만들어 넘기고 앱은 종료한다. 배치가 앱이 끝나기를 기다렸다가
폴더를 바꾸고 다시 띄운다. 윈도우에서 자기 갱신의 표준 방법이다.

표준 라이브러리만 쓴다 (urllib). 업데이트하려고 requests 를 설치하게 만드는
것은 앞뒤가 바뀐 일이다.
"""
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from . import version as _ver

_API = "https://api.github.com/repos/{owner}/{repo}/releases/latest"
_UA = "trickster-macro-updater"
_TIMEOUT = 8


class UpdateInfo:
    __slots__ = ("version", "url", "notes", "size", "name")

    def __init__(self, version, url, notes="", size=0, name=""):
        self.version = version
        self.url = url
        self.notes = notes
        self.size = size
        self.name = name

    def size_text(self):
        if self.size <= 0:
            return ""
        if self.size < 1024 * 1024:
            return f"{self.size/1024:.0f} KB"
        return f"{self.size/1024/1024:.1f} MB"


class Updater:
    """확인 → 다운로드 → 적용. 각 단계가 실패해도 프로그램은 계속 돌아야 한다."""

    def __init__(self, app_dir=None, log=None):
        # app_dir = 코드가 있는 폴더. 여기를 통째로 교체한다.
        self.app_dir = Path(app_dir or Path(__file__).resolve().parent.parent)
        self.root = self.app_dir.parent          # 프로그램 폴더
        self._log = log or (lambda m: None)
        self.latest = None
        self._checking = False

    # ------------------------------------------------------------------
    def enabled(self) -> bool:
        return _ver.update_enabled()

    def current(self) -> str:
        return _ver.current()

    # ------------------------------------------------------------------
    def check_async(self, on_done):
        """백그라운드로 확인한다. on_done(UpdateInfo 또는 None) 을 부른다.

        시작할 때 부르므로 절대 GUI 를 막으면 안 된다.
        """
        if self._checking or not self.enabled():
            return
        self._checking = True

        def work():
            info = None
            try:
                info = self.check()
            except Exception:
                info = None          # 네트워크가 없어도 조용히 넘어간다
            finally:
                self._checking = False
            try:
                on_done(info)
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def check(self):
        """최신 릴리스를 확인한다. 새 버전이 있으면 UpdateInfo, 없으면 None."""
        if not self.enabled():
            return None
        meta = _ver.info()
        url = _API.format(owner=meta["owner"], repo=meta["repo"])
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA,
            "Accept": "application/vnd.github+json",
        })
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=ctx) as r:
            data = json.loads(r.read().decode("utf-8"))

        tag = str(data.get("tag_name") or "")
        if not tag or not _ver.is_newer(tag):
            return None

        # 이 프로그램에 맞는 asset 을 고른다 (pickup.zip / hunt.zip / ...)
        want = f"{meta['app']}.zip".lower()
        asset = None
        for a in data.get("assets") or []:
            if str(a.get("name", "")).lower() == want:
                asset = a
                break
        if asset is None:
            # 이름이 안 맞으면 zip 중 아무거나 — 단일 배포일 수 있다
            for a in data.get("assets") or []:
                if str(a.get("name", "")).lower().endswith(".zip"):
                    asset = a
                    break
        if asset is None:
            return None

        self.latest = UpdateInfo(
            version=tag,
            url=asset.get("browser_download_url", ""),
            notes=str(data.get("body") or "").strip(),
            size=int(asset.get("size") or 0),
            name=str(asset.get("name") or ""),
        )
        return self.latest

    # ------------------------------------------------------------------
    def download(self, info, progress=None) -> Path:
        """zip 을 임시 폴더에 받는다. 실패하면 예외."""
        tmp = Path(tempfile.mkdtemp(prefix="tkmacro_up_"))
        dest = tmp / (info.name or "update.zip")
        req = urllib.request.Request(info.url, headers={"User-Agent": _UA})
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r, \
                open(dest, "wb") as f:
            total = int(r.headers.get("Content-Length") or info.size or 0)
            got = 0
            while True:
                chunk = r.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if progress and total:
                    try:
                        progress(got / total)
                    except Exception:
                        pass

        if not zipfile.is_zipfile(dest):
            raise RuntimeError("받은 파일이 zip 이 아닙니다")
        return dest

    def stage(self, zip_path: Path) -> Path:
        """zip 을 풀어 새 app 폴더를 만든다. 경로는 그 폴더."""
        work = zip_path.parent / "staged"
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path) as z:
            # zip slip 방어 — 압축 안의 경로가 밖으로 나가면 안 된다
            base = work.resolve()
            for m in z.namelist():
                p = (base / m).resolve()
                if not str(p).startswith(str(base)):
                    raise RuntimeError(f"압축 파일 경로가 이상합니다: {m}")
            z.extractall(work)

        # zip 안이 프로그램폴더/app/... 인지, 바로 app/... 인지 맞춰준다
        cand = work / "app"
        if cand.is_dir():
            return cand
        subs = [p for p in work.iterdir() if p.is_dir()]
        if len(subs) == 1 and (subs[0] / "app").is_dir():
            return subs[0] / "app"
        if (work / "core").is_dir():
            return work          # app 내용이 곧바로 들어 있다
        if len(subs) == 1:
            return subs[0]
        raise RuntimeError("업데이트 파일 구조를 알 수 없습니다")

    # ------------------------------------------------------------------
    def apply_and_restart(self, staged_app: Path, relaunch: str = None):
        """교체 배치를 만들어 실행하고 이 프로그램을 끝낸다.

        실행 중인 폴더는 스스로 지울 수 없으므로 배치에 맡긴다.
        """
        if os.name != "nt":
            raise RuntimeError("이 업데이트 방식은 Windows 전용입니다")

        launcher = relaunch or self._guess_launcher()
        bat = Path(tempfile.gettempdir()) / f"tkmacro_apply_{os.getpid()}.bat"
        old = self.app_dir
        backup = self.root / "app_old"

        # ASCII 로만 쓴다 — cmd 가 CP949 로 읽어도 깨지지 않게
        lines = [
            "@echo off",
            "setlocal",
            f'set "PID={os.getpid()}"',
            f'set "ROOT={self.root}"',
            f'set "NEWAPP={staged_app}"',
            f'set "OLDAPP={old}"',
            f'set "BACKUP={backup}"',
            "",
            "REM wait for the app to exit (max ~30s)",
            "set /a N=0",
            ":wait",
            'tasklist /fi "PID eq %PID%" 2>nul | find "%PID%" >nul',
            "if errorlevel 1 goto ready",
            "set /a N+=1",
            "if %N% GTR 60 goto ready",
            "ping -n 2 127.0.0.1 >nul",
            "goto wait",
            "",
            ":ready",
            'if exist "%BACKUP%" rmdir /s /q "%BACKUP%"',
            'if exist "%OLDAPP%" move "%OLDAPP%" "%BACKUP%" >nul',
            'move "%NEWAPP%" "%OLDAPP%" >nul',
            "if errorlevel 1 goto rollback",
            'if exist "%BACKUP%" rmdir /s /q "%BACKUP%"',
            "goto done",
            "",
            ":rollback",
            'if exist "%BACKUP%" move "%BACKUP%" "%OLDAPP%" >nul',
            "",
            ":done",
            f'cd /d "%ROOT%"',
            f'start "" "{launcher}"',
            'del "%~f0"',
        ]
        bat.write_text("\r\n".join(lines), encoding="ascii", errors="ignore")

        self._log("업데이트를 적용합니다. 프로그램이 다시 시작됩니다.")
        subprocess.Popen(["cmd", "/c", str(bat)],
                         creationflags=0x00000008)   # DETACHED_PROCESS
        time.sleep(0.3)
        return True

    def _guess_launcher(self) -> str:
        """프로그램 폴더의 .bat 중 하나를 재실행 대상으로 고른다."""
        for p in sorted(self.root.glob("*.bat")):
            if "apply" in p.name.lower():
                continue
            return str(p)
        return str(self.root / "run.bat")
