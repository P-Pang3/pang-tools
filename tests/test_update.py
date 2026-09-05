# -*- coding: utf-8 -*-
"""업데이트 로직 검증 — 네트워크 없이 확인 가능한 부분만.

실제 다운로드는 GitHub 저장소가 있어야 하므로, 여기서는
버전 비교 · zip 구조 인식 · 경로 분리 · 안전장치를 본다.
"""
import sys, os, json, tempfile, zipfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import version as V
from core.updater import Updater
from core import paths

results = []
def check(label, ok, extra=""):
    results.append(ok)
    print(f"  {label:<44} {'PASS' if ok else 'FAIL'}  {extra}")

print("1) 버전 비교")
cases = [
    ("1.0.1", "1.0.0", True), ("v1.1.0", "1.0.9", True),
    ("1.0.0", "1.0.0", False), ("0.9.9", "1.0.0", False),
    ("v2.0", "1.9.9", True),   ("1.0.0-beta", "1.0.0", False),
]
for remote, local, want in cases:
    got = V.is_newer(remote, local)
    check(f"  {remote} > {local}", got == want, f"-> {got}")

print("\n2) 코드와 데이터 분리 (업데이트가 설정을 지키는가)")
tmp = Path(tempfile.mkdtemp())
prog = tmp / "프로그램"
(prog / "app" / "core").mkdir(parents=True)
(prog / "data").mkdir()
fake = prog / "app" / "main.py"
fake.write_text("# x", encoding="utf-8")
d = paths.data_dir(fake)
check("배포본에서 data 는 app 의 형제", d == prog / "data", str(d.name))
check("program_dir 은 런처가 있는 곳", paths.program_dir(fake) == prog)
check("is_packaged 판정", paths.is_packaged(fake) is True)
# 개발 중 배치
devroot = tmp / "dev"
(devroot).mkdir()
devfile = devroot / "main.py"
devfile.write_text("# x", encoding="utf-8")
check("개발 중에는 data 가 코드 옆", paths.data_dir(devfile) == devroot / "data")

print("\n3) 업데이트 zip 구조 인식")
up = Updater(app_dir=prog / "app")
def make_zip(layout):
    z = tmp / "u.zip"
    if z.exists(): z.unlink()
    with zipfile.ZipFile(z, "w") as f:
        for name in layout:
            f.writestr(name, "# x")
    return z

for label, layout, ok_name in (
    ("app/ 로 감싼 형태", ["app/main.py", "app/core/__init__.py"], "app"),
    ("내용이 바로 들어간 형태", ["main.py", "core/__init__.py"], None),
):
    z = make_zip(layout)
    try:
        staged = up.stage(z)
        good = staged.exists() and (staged / "core").exists()
        check(label, good, str(staged.name))
    except Exception as e:
        check(label, False, str(e))

print("\n4) 안전장치")
# zip slip — 압축 안에서 밖으로 나가려는 경로
z = tmp / "evil.zip"
with zipfile.ZipFile(z, "w") as f:
    f.writestr("../../evil.py", "# bad")
try:
    up.stage(z)
    check("압축 경로 탈출 차단", False, "막지 못함")
except RuntimeError:
    check("압축 경로 탈출 차단", True)
except Exception as e:
    check("압축 경로 탈출 차단", "경로" in str(e), str(e)[:30])

# 저장소 미지정이면 업데이트 자체가 꺼진다
check("저장소 없으면 확인 안 함", up.check() is None if not V.update_enabled() else True)
check("update_enabled 판정", V.update_enabled() == bool(V.info()["owner"] and V.info()["repo"]))

print("\n" + "=" * 62)
print(f"업데이트: {sum(results)}/{len(results)} PASS")
