# -*- coding: utf-8 -*-
"""
업데이트 알림 띠 — 새 버전이 있을 때만 나타난다.

평소에는 화면에 없다. 확인은 시작할 때 백그라운드로 조용히 하고,
없으면 아무 일도 일어나지 않는다. **업데이트가 없을 때 자리를 차지하거나
"최신입니다" 를 알리는 것은 방해일 뿐이다.**

받을지 말지는 사용자가 정한다. 쓰는 도중에 코드가 바뀌면 당황스럽다.
"""
import tkinter as tk

from .updater import Updater
from . import version as _ver

_BG = "#8A5B00"
_BG_HOVER = "#6D4800"
_FG = "#FFFFFF"


class UpdateBar(tk.Frame):
    def __init__(self, parent, app_dir=None, log=None, on_before_restart=None):
        super().__init__(parent, bg=_BG)
        self._parent = parent
        self._log = log or (lambda m: None)
        self._on_before_restart = on_before_restart
        self.updater = Updater(app_dir=app_dir, log=self._log)
        self._info = None
        self._busy = False

        self.label = tk.Label(
            self, text="", font=("맑은 고딕", 9), bg=_BG, fg=_FG,
            anchor="w", padx=12, pady=5)
        self.label.pack(side="left", fill="x", expand=True)

        self.btn = tk.Button(
            self, text="업데이트", font=("맑은 고딕", 9, "bold"),
            bg="#FFFFFF", fg=_BG, relief="flat", bd=0, cursor="hand2",
            padx=12, pady=2, command=self._start)
        self.btn.pack(side="right", padx=(0, 6), pady=4)

        self.later = tk.Button(
            self, text="나중에", font=("맑은 고딕", 9),
            bg=_BG, fg="#FFE0B2", relief="flat", bd=0, cursor="hand2",
            activebackground=_BG_HOVER, activeforeground=_FG,
            padx=8, pady=2, command=self.hide)
        self.later.pack(side="right", padx=(0, 4), pady=4)

    # ------------------------------------------------------------------
    def check(self):
        """시작할 때 한 번 부른다. 없으면 조용히 지나간다."""
        if not self.updater.enabled():
            return
        self.updater.check_async(self._on_result)

    def _on_result(self, info):
        # 백그라운드 스레드 → GUI 스레드
        try:
            self._parent.after(0, lambda: self._show(info))
        except (RuntimeError, tk.TclError):
            pass

    def _show(self, info):
        if info is None:
            return
        self._info = info
        size = f" ({info.size_text()})" if info.size_text() else ""
        self.label.config(
            text=f"새 버전 {info.version} 이 있습니다{size}"
                 f"   ·   지금 버전 {self.updater.current()}")
        self.pack(fill="x", side="top")
        self._log(f"새 버전 {info.version} 이 있습니다")

    def hide(self):
        self.pack_forget()

    # ------------------------------------------------------------------
    def _start(self):
        if self._busy or self._info is None:
            return
        self._busy = True
        self.btn.config(state="disabled", text="받는 중")
        self.later.config(state="disabled")
        self.label.config(text=f"{self._info.version} 을 받는 중…  0%")

        import threading
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        info = self._info
        try:
            def progress(frac):
                pct = int(frac * 100)
                try:
                    self._parent.after(0, lambda: self.label.config(
                        text=f"{info.version} 을 받는 중…  {pct}%"))
                except (RuntimeError, tk.TclError):
                    pass

            zip_path = self.updater.download(info, progress)
            staged = self.updater.stage(zip_path)
            self._parent.after(0, lambda: self._apply(staged))
        except Exception as e:
            self._parent.after(0, lambda: self._failed(e))

    def _apply(self, staged):
        self.label.config(text="적용하는 중… 프로그램이 다시 시작됩니다")
        if self._on_before_restart:
            try:
                self._on_before_restart()
            except Exception:
                pass
        try:
            self.updater.apply_and_restart(staged)
        except Exception as e:
            self._failed(e)
            return
        # 교체 배치가 이 프로세스가 끝나기를 기다린다
        try:
            self._parent.quit()
            self._parent.destroy()
        except Exception:
            pass
        import os
        os._exit(0)

    def _failed(self, err):
        self._busy = False
        self.btn.config(state="normal", text="다시 시도")
        self.later.config(state="normal")
        self.label.config(text=f"업데이트 실패 — {err}")
        self._log(f"업데이트 실패: {err}")


def version_text() -> str:
    """설정 화면 등에 넣을 짧은 버전 표시."""
    info = _ver.info()
    if info["owner"] and info["repo"]:
        return f"v{info['version']}"
    return f"v{info['version']} (개발)"
