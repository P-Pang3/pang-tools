# -*- coding: utf-8 -*-
"""
릴리스 — 버전 올리고, 빌드하고, GitHub 에 올린다.

    python release.py 1.1.0 -m "이동 속도 조정"

이 한 줄이면 사용자들의 프로그램이 다음 실행 때 업데이트 알림을 받는다.

하는 일:
  1. core/version.py 의 VERSION 을 새 값으로
  2. build.py 로 세 프로그램 배포본 생성
  3. gh 로 릴리스를 만들고 zip 을 올린다 (태그 = v1.1.0)

`gh auth login` 이 한 번 되어 있어야 한다.
"""
import argparse
import io
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VER_FILE = ROOT / "core" / "version.py"
DIST = ROOT / "dist"

ASSETS = ["pickup.zip", "hunt.zip", "autoclick.zip",
          "pickup-full.zip", "hunt-full.zip", "autoclick-full.zip"]


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, text=True, encoding="utf-8", **kw)


def read_meta():
    s = VER_FILE.read_text(encoding="utf-8")
    def grab(name, default=""):
        m = re.search(rf'^{name}\s*=\s*"([^"]*)"', s, re.M)
        return m.group(1) if m else default
    return grab("VERSION", "0.0.0"), grab("GITHUB_OWNER"), grab("GITHUB_REPO")


def write_meta(version=None, owner=None, repo=None):
    s = VER_FILE.read_text(encoding="utf-8")
    if version:
        s = re.sub(r'^VERSION\s*=\s*"[^"]*"', f'VERSION = "{version}"',
                   s, count=1, flags=re.M)
    if owner is not None:
        s = re.sub(r'^GITHUB_OWNER\s*=\s*"[^"]*"',
                   f'GITHUB_OWNER = "{owner}"', s, count=1, flags=re.M)
    if repo is not None:
        s = re.sub(r'^GITHUB_REPO\s*=\s*"[^"]*"',
                   f'GITHUB_REPO = "{repo}"', s, count=1, flags=re.M)
    VER_FILE.write_text(s, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="릴리스 만들기")
    ap.add_argument("version", help="예: 1.1.0")
    ap.add_argument("-m", "--notes", default="", help="변경 내용")
    ap.add_argument("--owner", default=None, help="처음 한 번만 지정하면 된다")
    ap.add_argument("--repo", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="빌드까지만 하고 업로드는 안 함")
    args = ap.parse_args()

    if not re.match(r"^\d+\.\d+(\.\d+)?$", args.version):
        print(f"버전 형식이 이상합니다: {args.version}  (예: 1.1.0)")
        return 1

    cur, owner, repo = read_meta()
    owner = args.owner or owner
    repo = args.repo or repo
    if not owner or not repo:
        print("GitHub 저장소를 먼저 지정하세요:")
        print("  python release.py 1.0.0 --owner 내계정 --repo 저장소이름")
        return 1

    tag = f"v{args.version}"
    print(f"{cur} -> {args.version}   ({owner}/{repo})")
    print("=" * 58)

    # 1) 버전 기록
    write_meta(args.version, owner, repo)
    print(f"1. core/version.py 를 {args.version} 로 갱신")

    # 2) 빌드
    r = run([sys.executable, "build.py", "--version", args.version,
             "--owner", owner, "--repo", repo], capture_output=True)
    if r.returncode != 0:
        print("빌드 실패:\n" + (r.stderr or r.stdout))
        write_meta(cur)          # 되돌린다
        return 1
    print("2. 배포본 생성 완료")

    missing = [a for a in ASSETS if not (DIST / a).exists()]
    if missing:
        print(f"   빠진 파일: {', '.join(missing)}")
        return 1

    if args.dry_run:
        # 시험 삼아 돌린 것이므로 버전을 되돌린다.
        # 그러지 않으면 올리지도 않은 버전이 소스에 남는다.
        write_meta(cur, owner, repo)
        print(f"\n--dry-run 이라 업로드하지 않았고 버전도 {cur} 로 되돌렸습니다.")
        print("dist/ 폴더를 확인하세요.")
        return 0

    # 3) gh 로 릴리스
    if run(["gh", "--version"], capture_output=True).returncode != 0:
        print("gh 를 찾을 수 없습니다. https://cli.github.com 에서 설치하세요.")
        return 1

    notes = args.notes or f"{args.version} 업데이트"
    cmd = ["gh", "release", "create", tag,
           *[str(DIST / a) for a in ASSETS],
           "--title", f"{args.version}", "--notes", notes,
           "--repo", f"{owner}/{repo}"]
    r = run(cmd, capture_output=True)
    if r.returncode != 0:
        err = (r.stderr or "").strip()
        print("릴리스 실패:\n" + err)
        if "already exists" in err:
            print(f"\n{tag} 태그가 이미 있습니다. 지우고 다시 하려면:")
            print(f"  gh release delete {tag} --repo {owner}/{repo} --yes")
        return 1

    print(f"3. 릴리스 {tag} 업로드 완료")
    print(f"\n{(r.stdout or '').strip()}")
    print("\n이제 사용자들이 프로그램을 켜면 업데이트 알림을 받습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
