# -*- coding: utf-8 -*-
"""
배포본 만들기 — 프로그램마다 독립 폴더와 zip 을 뽑는다.

    python build.py                 세 개 다
    python build.py autoclick       하나만
    python build.py --version 1.1.0 버전 지정

개발 소스는 한 곳에 둔다. core 를 프로그램마다 복사해두면 고칠 때마다
세 곳을 고쳐야 하고, 언젠가 한 곳을 빠뜨린다. 대신 여기서 각 프로그램에
**실제로 필요한 모듈만** 골라 담는다.

배포본 구조:

    오토 클릭/
      오토클릭 실행.bat
      app/                ← 업데이트가 통째로 갈아끼우는 곳
        autoclick.py
        core/...
        version.json
      data/               ← 사용자 것. 업데이트가 건드리지 않는다
      읽어보세요.txt
"""
import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"

# 프로그램마다 필요한 것만. 의존성 분석으로 확인한 목록이다.
CORE_COMMON = ["__init__.py", "geometry.py", "paths.py", "window.py",
               "actuation.py", "keycapture.py", "version.py", "updater.py",
               "updateui.py"]
CORE_MACRO = CORE_COMMON + [
    "snapshot.py", "tracking.py", "safety.py", "telemetry.py",
    "pipeline.py", "combat.py", "vitals.py", "profiles.py", "overlay.py",
    "perception/__init__.py", "perception/base.py", "perception/screen.py",
]

APPS = {
    "pickup": {
        "title": "줍기 도우미",
        "launcher": "줍기 도우미 실행.bat",
        "entry": "main.py",
        "args": "--pickup",
        "files": ["main.py", "engine.py"],
        "core": CORE_MACRO,
        "requires": ["pynput>=1.7.6", "opencv-python>=4.8", "mss>=9.0",
                     "numpy>=1.24", "Pillow>=10.0"],
        "desc": "화면에서 지정한 이미지를 찾아 자동으로 클릭합니다.",
    },
    "hunt": {
        "title": "사냥 도우미",
        "launcher": "사냥 도우미 실행.bat",
        "entry": "main.py",
        "args": "--hunt",
        "files": ["main.py", "engine.py"],
        "core": CORE_MACRO,
        "requires": ["pynput>=1.7.6", "opencv-python>=4.8", "mss>=9.0",
                     "numpy>=1.24", "Pillow>=10.0"],
        "desc": "대상을 공격하고 체력이 낮으면 회복 키를 씁니다.",
    },
    "autoclick": {
        "title": "오토 클릭",
        "launcher": "오토클릭 실행.bat",
        "entry": "autoclick.py",
        "args": "",
        "files": ["autoclick.py"],
        "core": CORE_COMMON,
        # 화면을 보지 않으므로 OpenCV 가 필요 없다. 설치가 훨씬 가볍다.
        "requires": ["pynput>=1.7.6"],
        "desc": "정해진 간격으로 마우스나 키를 반복 입력합니다.",
    },
}

LAUNCHER = """@echo off
REM Pang Tools - {app_id} (ASCII-only launcher)
setlocal
cd /d "%~dp0"

REM -----------------------------------------------------------
REM 1) Python check. This must run BEFORE the admin elevation:
REM    a per-user install done from an elevated shell lands in the
REM    administrator's profile, where the normal account cannot see it.
REM -----------------------------------------------------------
REM Ask Python to run something trivial. This is the only reliable test:
REM "where python" can list several paths (a real install plus the Windows
REM Store alias), and only the first one actually runs.
python -c "import sys; sys.exit(0)" >nul 2>&1
if not errorlevel 1 goto :have_python

REM Python did not run. Work out why so the message is useful.
where python >nul 2>&1
if errorlevel 1 goto :get_python
for /f "delims=" %%p in ('where python 2^>nul') do (
    echo %%p | findstr /i "WindowsApps" >nul && goto :store_stub
    goto :get_python
)
goto :get_python

:have_python
python -c "import pynput" >nul 2>&1
if errorlevel 1 goto :install_deps

REM -----------------------------------------------------------
REM 2) Elevate. Some games run elevated and Windows blocks input from
REM    lower-privilege processes (cursor moves but clicks do nothing).
REM    Cancelling is fine - we just carry on without it.
REM -----------------------------------------------------------
net session >nul 2>&1
if not errorlevel 1 goto :run
if "%ELEVATED%"=="1" goto :run
set "ELEVATED=1"
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs" >nul 2>&1
if not errorlevel 1 exit /b 0

:run
where pythonw >nul 2>&1
if errorlevel 1 goto :run_console
start "" pythonw "app\\{entry}" {args}
goto :eof
:run_console
start "" python "app\\{entry}" {args}
goto :eof

REM -----------------------------------------------------------
REM Dependencies
REM -----------------------------------------------------------
:install_deps
echo.
echo   Installing required packages. This runs only once.
echo.
python -m pip install --upgrade pip
python -m pip install -r "app\\requirements.txt"
if errorlevel 1 goto :install_fail
goto :have_python

REM -----------------------------------------------------------
REM Python auto-install
REM -----------------------------------------------------------
:get_python
if exist "%TEMP%\\pangtools_py.tmp" goto :python_manual

echo.
echo   Python was not found. Installing it automatically.
echo   About 25 MB will be downloaded. This runs only once.
echo.

curl --version >nul 2>&1
if errorlevel 1 goto :python_manual

echo   Downloading Python 3.12.9 ...
curl -L --progress-bar -o "%TEMP%\\python_setup.exe" "https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe"
if errorlevel 1 goto :python_manual

echo.
echo   Installing (no administrator rights needed) ...
"%TEMP%\\python_setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=0
if errorlevel 1 goto :python_manual

del "%TEMP%\\python_setup.exe" >nul 2>&1
echo 1 > "%TEMP%\\pangtools_py.tmp"

echo.
echo   Done. Restarting ...
echo.
start "" "%~f0"
exit /b 0

:store_stub
echo.
echo   Windows is redirecting "python" to the Microsoft Store.
echo.
echo   Fix it like this:
echo     Settings ^> Apps ^> Advanced app settings
echo       ^> App execution aliases
echo     Turn OFF "python.exe" and "python3.exe".
echo.
echo   Then run this file again.
echo.
pause
goto :eof

:python_manual
del "%TEMP%\\pangtools_py.tmp" >nul 2>&1
echo.
echo   Could not install Python automatically.
echo.
echo   Please install it yourself:
echo     https://www.python.org/downloads/
echo.
echo   IMPORTANT: tick "Add python.exe to PATH" during setup,
echo   then run this file again.
echo.
pause
goto :eof

:install_fail
echo.
echo   Package install failed. Check your internet connection
echo   and run this file again.
echo.
pause
goto :eof
"""

README = """{title}
{bar}

{desc}

■ 실행 방법
   "{launcher}" 를 두 번 누르면 끝입니다.

   처음 한 번은 준비 작업을 합니다 (인터넷 연결 필요).
   Python 이 없으면 자동으로 받아서 설치하고 (약 25MB),
   필요한 패키지도 알아서 깔린 뒤 프로그램이 뜹니다.
   설치가 끝나면 창이 한 번 다시 열립니다 - 정상입니다.

   검은 창이 잠깐 보였다 사라지는 것도 정상입니다.

■ 폴더 설명
   app\\     프로그램 코드입니다. 직접 고치지 마세요.
             업데이트할 때 이 폴더만 통째로 바뀝니다.
   data\\    설정과 템플릿이 들어갑니다. 업데이트해도 그대로 남습니다.
             다른 PC 로 옮길 때는 이 폴더만 복사하면 됩니다.

■ 업데이트
   시작할 때 새 버전이 있는지 확인하고, 있으면 화면에 알려줍니다.
   받을지 말지는 직접 고르시면 됩니다.

■ 안전 장치
   급할 때는 마우스를 화면 왼쪽 위 모서리로 보내세요. 즉시 멈춥니다.
   F12 는 비상 정지입니다.

버전 {version}
"""


def copy_app(app_id: str, spec: dict, version: str, owner: str, repo: str,
             out_root: Path) -> Path:
    prog = out_root / spec["title"]
    if prog.exists():
        shutil.rmtree(prog)
    app = prog / "app"
    app.mkdir(parents=True)

    for f in spec["files"]:
        shutil.copy2(ROOT / f, app / f)

    for rel in spec["core"]:
        src = ROOT / "core" / rel
        dst = app / "core" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    (app / "requirements.txt").write_text(
        "\n".join(spec["requires"]) + "\n", encoding="utf-8")

    (app / "version.json").write_text(json.dumps({
        "version": version, "owner": owner, "repo": repo, "app": app_id,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # 런처는 cmd 가 읽으므로 ASCII 로만
    (prog / spec["launcher"]).write_text(
        LAUNCHER.format(app_id=app_id, entry=spec["entry"],
                        args=spec["args"]),
        encoding="ascii", errors="ignore")

    (prog / "읽어보세요.txt").write_text(
        README.format(title=spec["title"], bar="=" * 40, desc=spec["desc"],
                      launcher=spec["launcher"], version=version),
        encoding="utf-8")

    (prog / "data").mkdir(exist_ok=True)
    (prog / "data" / ".keep").write_text("", encoding="utf-8")
    return prog


def make_zip(prog_dir: Path, app_id: str, out_root: Path) -> Path:
    """릴리스에 올릴 zip. 업데이터가 받는 것과 같은 형식이다.

    app/ 만 담는다 — data/ 를 담으면 업데이트할 때 사용자 설정을 덮는다.
    """
    zpath = out_root / f"{app_id}.zip"
    if zpath.exists():
        zpath.unlink()
    app = prog_dir / "app"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(app.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                z.write(p, Path("app") / p.relative_to(app))
    return zpath


def make_full_zip(prog_dir: Path, app_id: str, out_root: Path) -> Path:
    """처음 받는 사람용 — 폴더 통째로."""
    zpath = out_root / f"{app_id}-full.zip"
    if zpath.exists():
        zpath.unlink()
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(prog_dir.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                z.write(p, Path(prog_dir.name) / p.relative_to(prog_dir))
    return zpath


def main():
    ap = argparse.ArgumentParser(description="배포본 생성")
    ap.add_argument("apps", nargs="*", default=None,
                    help="pickup / hunt / autoclick (없으면 전부)")
    ap.add_argument("--version", default=None, help="예: 1.1.0")
    ap.add_argument("--owner", default="", help="GitHub 사용자명")
    ap.add_argument("--repo", default="", help="GitHub 저장소명")
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT))
    from core import version as ver
    v = args.version or ver.VERSION
    owner = args.owner or ver.GITHUB_OWNER
    repo = args.repo or ver.GITHUB_REPO

    targets = args.apps or list(APPS)
    unknown = [t for t in targets if t not in APPS]
    if unknown:
        print(f"모르는 프로그램: {', '.join(unknown)}")
        print(f"쓸 수 있는 것: {', '.join(APPS)}")
        return 1

    DIST.mkdir(exist_ok=True)
    print(f"버전 {v}" + (f" · {owner}/{repo}" if owner and repo
                         else "  (저장소 미지정 — 업데이트 기능 꺼짐)"))
    print("=" * 58)

    for app_id in targets:
        spec = APPS[app_id]
        prog = copy_app(app_id, spec, v, owner, repo, DIST)
        z = make_zip(prog, app_id, DIST)
        fz = make_full_zip(prog, app_id, DIST)
        n = sum(1 for p in (prog / "app").rglob("*") if p.is_file())
        size = sum(p.stat().st_size for p in prog.rglob("*") if p.is_file())
        print(f"\n{spec['title']}")
        print(f"  폴더      dist/{prog.name}/")
        print(f"  파일 {n}개 · {size/1024:.0f} KB")
        print(f"  업데이트용 {z.name} ({z.stat().st_size/1024:.0f} KB)")
        print(f"  최초설치용 {fz.name} ({fz.stat().st_size/1024:.0f} KB)")

    print("\n" + "=" * 58)
    print("완료. dist/ 폴더를 확인하세요.")
    if not (owner and repo):
        print("\n업데이트를 쓰려면 저장소를 지정해 다시 빌드하세요:")
        print("  python build.py --owner 내계정 --repo 저장소이름")
    return 0


if __name__ == "__main__":
    sys.exit(main())
