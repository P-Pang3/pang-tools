# -*- coding: utf-8 -*-
"""오토 클릭 검증 — mainloop 을 실제로 돌린다 (after 콜백이 살아야 하므로)."""
import sys, time
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tkinter as tk
import autoclick as A

results = []
def check(label, ok, extra=""):
    results.append(ok)
    print(f"  {label:<40} {'PASS' if ok else 'FAIL'}  {extra}")

root = tk.Tk()
root.withdraw()
app = A.AutoClickApp(root)

fired = {"click": 0, "key": 0}
app.engine.hands.mouse.press   = lambda b: fired.__setitem__("click", fired["click"]+1)
app.engine.hands.mouse.release = lambda b: None
def fake_key(k, ev=None):
    fired["key"] += 1
    return False
app.engine.hands.press_key = fake_key

def phase1():
    print("1) 설정 왕복")
    # 화면은 초 단위다. 0.25 초 -> 250 ms 로 저장되어야 한다.
    app.interval_var.set("0.25"); app.jitter_var.set("10")
    app.key_on_var.set(True); app.key_var.set("f5"); app.limit_var.set("5")
    ok = app._save_from_ui(silent=True)
    check("저장 (0.25초 -> 250ms)",
          ok and app.cfg["interval_ms"] == 250 and app.cfg["key"] == "f5",
          f'{app.cfg["interval_ms"]}ms / {app.cfg["key"]}')
    app._sync_to_ui()
    check("로드 (250ms -> 0.25초)",
          app.interval_var.get() == "0.25" and app.key_var.get() == "f5",
          app.interval_var.get())

    print("\n2) 횟수 제한 실행 (60ms x 8회)")
    app.cfg.update({"failsafe_corner": False, "do_click": True, "do_key": True,
                    "key": "f5", "interval_ms": 60, "jitter_percent": 0,
                    "limit_count": 8, "window_lock": False,
                    "position_mode": "cursor",
                    # 지연은 아래에서 따로 확인한다. 여기서는 즉시 돌아야
                    # 실행 시간 측정이 의미를 갖는다.
                    "start_delay_sec": 0, "click_hold_ms": 30})
    globals()["t0"] = time.monotonic()
    app.engine.start()
    root.after(20, wait_done)

def wait_done():
    """엔진이 스스로 멈출 때까지 기다린다. 고정 시간으로 재면
    그 시간을 측정하게 되어 의미가 없다."""
    if app.engine.is_running():
        root.after(20, wait_done)
        return
    phase2()

def phase2():
    el = time.monotonic() - t0
    check("8회 정확히 실행", app.engine.count == 8, f"{app.engine.count}회")
    check("자동 정지", not app.engine.is_running())
    check("클릭 8 + 키 8", fired["click"] == 8 and fired["key"] == 8,
          f'클릭 {fired["click"]} / 키 {fired["key"]}')
    check("소요 시간 (8x(60+30ms) = 약 0.72초)", 0.5 <= el <= 1.1, f"{el:.2f}초")

    print("\n3) 마우스만 / 키만")
    fired["click"] = fired["key"] = 0
    app.cfg.update({"do_click": False, "do_key": True, "limit_count": 3,
                    "start_delay_sec": 0})
    app.engine.start()
    root.after(500, phase4)

def phase4():
    check("키만 켰을 때 클릭 안 나감",
          fired["key"] == 3 and fired["click"] == 0,
          f'클릭 {fired["click"]} / 키 {fired["key"]}')

    print("\n4) 잘못된 설정 거부")
    app.cfg.update({"do_click": False, "do_key": False})
    app.engine.start()
    check("둘 다 끄면 시작 안 함", not app.engine.is_running())
    app.cfg.update({"do_click": False, "do_key": True, "key": ""})
    app.engine.start()
    check("키 켰는데 비었으면 시작 안 함", not app.engine.is_running())

    print("\n5) 시작 지연 (게임으로 돌아갈 시간)")
    fired["click"] = fired["key"] = 0
    app.cfg.update({"do_click": True, "do_key": False, "limit_count": 2,
                    "start_delay_sec": 1, "interval_ms": 30})
    globals()["t5"] = time.monotonic()
    app.engine.start()
    root.after(1600, phase5)

def phase5():
    el = time.monotonic() - t5
    check("1초 기다린 뒤 시작", el >= 1.0 and fired["click"] == 2,
          f"{el:.2f}초 · 클릭 {fired['click']}")

    print("\n" + "=" * 56)
    print(f"오토 클릭: {sum(results)}/{len(results)} PASS")
    app.engine.stop()
    root.quit()

root.after(200, phase1)
root.mainloop()
root.destroy()
