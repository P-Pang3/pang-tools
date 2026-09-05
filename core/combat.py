# -*- coding: utf-8 -*-
"""
전투 판단과 생존 규칙 (P2.2 ~ P2.4).

지금까지 판단 계층은 "가장 가까운 아이템을 클릭한다" 하나뿐이었다.
사냥이 들어오면 동시에 하고 싶은 일이 여럿 생기고, 그중 무엇을 먼저
할지 정해야 한다.

  생존 > 전투 > 줍기

이 순서는 협상 대상이 아니다. HP 가 바닥인데 아이템을 주우러 가면 죽는다.
여기서 처음으로 '우선순위를 가진 규칙 목록'이 등장하는데, 이게 P3
시나리오 엔진의 씨앗이다. 지금은 손으로 짠 순서지만 나중에는 데이터가 된다.
"""
import time

# 행동 종류
IDLE = "idle"
HEAL_HP = "heal_hp"
HEAL_MP = "heal_mp"
ATTACK = "attack"
PICKUP = "pickup"
BUFF = "buff"
HALT = "halt"          # 위험해서 스스로 멈춤


class Action:
    __slots__ = ("kind", "target", "key", "reason", "skill")

    def __init__(self, kind=IDLE, target=None, key=None, reason="",
                 skill=None):
        self.kind = kind
        self.target = target      # Track (attack/pickup)
        self.key = key            # 눌러야 할 키 (heal)
        self.reason = reason
        # 공격에 쓸 스킬 키. None 이면 평타(클릭만).
        # 트릭스터는 '스킬키 -> 대상 클릭' 순서라 클릭 전에 눌러야 한다.
        self.skill = skill

    def __repr__(self):
        return f"Action({self.kind}{' ' + self.reason if self.reason else ''})"


IDLE_ACTION = Action()


class CombatPolicy:
    """스냅샷과 추적기를 보고 다음 행동 하나를 고른다."""

    def __init__(self, config_getter, log=None):
        self._cfg = config_getter
        self._log = log or (lambda m: None)
        self._last_heal = {}          # key -> 마지막 사용 시각
        self._engaged_id = None       # 지금 때리고 있는 대상
        self._engaged_since = 0.0
        self._low_hp_since = 0.0
        self._last_hp_warn = 0.0
        self._last_skill = {}         # 스킬 키 -> 마지막 사용 시각
        self._skill_turn = 0          # 순환 위치
        self._last_buff = {}          # 버프 키 -> 마지막 사용 시각
        self._buffed_once = set()     # 시작 후 한 번은 걸었는가

    def reset(self):
        self._last_heal.clear()
        self._last_skill.clear()
        self._skill_turn = 0
        self._last_buff.clear()
        self._buffed_once.clear()
        self._engaged_id = None
        self._engaged_since = 0.0
        self._low_hp_since = 0.0

    # ------------------------------------------------------------------
    def _c(self, key, default):
        try:
            v = (self._cfg() or {}).get(key, default)
            return default if v is None else v
        except Exception:
            return default

    def _cf(self, key, default):
        try:
            return float(self._c(key, default))
        except (TypeError, ValueError):
            return float(default)

    # ------------------------------------------------------------------
    def decide(self, snapshot, tracker, cursor=None) -> Action:
        """다음 행동. 위에서부터 순서대로 검사하고 첫 번째로 걸리는 것을 쓴다."""
        hunting = bool(self._c("combat_enabled", False))
        player = snapshot.player if snapshot else None

        # ── 1. 생존 ──────────────────────────────────────────────
        if player is not None:
            act = self._survival(player)
            if act is not None:
                return act

        # ── 2. 버프 ──────────────────────────────────────────────
        # 끊긴 채로 계속 싸우면 결국 죽는다. 전투보다 먼저 챙긴다.
        act = self._buff()
        if act is not None:
            return act

        # ── 3. 전투 ──────────────────────────────────────────────
        if hunting:
            act = self._combat(snapshot, tracker, cursor)
            if act is not None:
                return act

        # ── 4. 줍기 ──────────────────────────────────────────────
        item = self._pick_target(tracker, cursor, kind="item")
        if item is not None:
            return Action(PICKUP, target=item)

        return IDLE_ACTION

    # ------------------------------------------------------------------
    def _survival(self, player):
        """회복과 후퇴. 전투보다 항상 먼저 본다."""
        hp = player.hp_ratio
        mp = player.mp_ratio

        # 사망 — 더 할 수 있는 게 없다
        if not player.alive:
            return Action(HALT, reason="캐릭터가 죽었습니다")

        if hp is not None:
            halt_at = self._cf("hp_halt_percent", 0) / 100.0
            if halt_at > 0 and hp <= halt_at:
                return Action(HALT,
                              reason=f"HP {hp*100:.0f}% — 위험해서 정지")

            heal_at = self._cf("hp_potion_percent", 50) / 100.0
            key = str(self._c("hp_potion_key", "")).strip()
            if key and heal_at > 0 and hp <= heal_at:
                if self._ready(key, self._cf("potion_cooldown_sec", 2.0)):
                    return Action(HEAL_HP, key=key,
                                  reason=f"HP {hp*100:.0f}%")

        if mp is not None:
            heal_at = self._cf("mp_potion_percent", 30) / 100.0
            key = str(self._c("mp_potion_key", "")).strip()
            if key and heal_at > 0 and mp <= heal_at:
                if self._ready(key, self._cf("potion_cooldown_sec", 2.0)):
                    return Action(HEAL_MP, key=key,
                                  reason=f"MP {mp*100:.0f}%")

        # 인벤토리가 가득 차면 줍기를 멈춘다 (전투는 계속)
        return None

    def _ready(self, key, cooldown) -> bool:
        """물약을 연타하지 않도록 — 한 번 먹고 효과가 도는 시간을 준다."""
        last = self._last_heal.get(key, 0.0)
        if (time.monotonic() - last) < cooldown:
            return False
        return True

    def note_heal(self, key):
        self._last_heal[key] = time.monotonic()

    # ------------------------------------------------------------------
    def buffs(self):
        """[(key, 유지시간초), ...]. 유지시간이 0 이하면 무시한다."""
        raw = self._c("buff_skills", []) or []
        out = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            k = str(item.get("key", "")).strip()
            dur = float(item.get("duration", 0) or 0)
            if k and dur > 0:
                out.append((k, dur))
        return out

    def _buff(self):
        """다시 걸어야 할 버프가 있으면 그 행동을 돌려준다."""
        if not self._c("buff_enabled", False):
            return None
        now = time.monotonic()
        margin = self._cf("buff_margin_sec", 5.0)
        for key, dur in self.buffs():
            last = self._last_buff.get(key)
            if last is None:
                # 시작하고 아직 한 번도 안 걸었다
                return Action(BUFF, key=key, reason="시작 버프")
            # 지속 시간이 끝나기 조금 전에 미리 건다.
            # 정확히 끝나는 순간을 노리면 그 틈에 버프가 빠진다.
            if (now - last) >= max(1.0, dur - margin):
                return Action(BUFF, key=key,
                              reason=f"{dur:.0f}초 경과 — 재사용")
        return None

    def note_buff(self, key):
        if key:
            self._last_buff[key] = time.monotonic()

    # ------------------------------------------------------------------
    def skills(self):
        """설정된 스킬 목록 [(key, cooldown), ...]. 빈 목록이면 평타."""
        raw = self._c("attack_skills", []) or []
        out = []
        for item in raw:
            if isinstance(item, dict):
                k = str(item.get("key", "")).strip()
                cd = float(item.get("cooldown", 0) or 0)
            else:
                k, cd = str(item).strip(), 0.0
            if k:
                out.append((k, cd))
        return out

    def pick_skill(self):
        """쓸 수 있는 스킬 하나. 없으면 None (평타).

        쿨다운이 지난 것 중에서 순환으로 고른다. 같은 스킬만 계속 쓰면
        쿨다운에 걸려 공격이 비고, 무작위로 고르면 순서가 뒤죽박죽이 된다.
        """
        sk = self.skills()
        if not sk:
            return None
        now = time.monotonic()
        n = len(sk)
        for i in range(n):
            key, cd = sk[(self._skill_turn + i) % n]
            if cd <= 0 or (now - self._last_skill.get(key, 0.0)) >= cd:
                self._skill_turn = (self._skill_turn + i + 1) % n
                return key
        return None       # 전부 쿨다운 — 이번엔 클릭만

    def note_skill(self, key):
        if key:
            self._last_skill[key] = time.monotonic()

    # ------------------------------------------------------------------
    def _combat(self, snapshot, tracker, cursor):
        """교전 대상을 고르고 때린다."""
        now = time.monotonic()
        timeout = self._cf("attack_timeout_sec", 12.0)

        # 이미 붙어 있는 대상이 아직 살아 있으면 계속 때린다.
        # 매번 새로 고르면 몬스터 사이를 왔다갔다하며 아무것도 못 죽인다.
        if self._engaged_id is not None:
            cur = next((t for t in tracker.tracks
                        if t.id == self._engaged_id), None)
            if cur is None:
                # 사라졌다 = 처치했거나 놓쳤다
                self._engaged_id = None
            elif (now - self._engaged_since) > timeout:
                self._log(f"⏱  {timeout:.0f}초 안에 못 잡음 — 대상 교체")
                cur.blocked_until = now + self._cf("engage_block_sec", 15.0)
                self._engaged_id = None
            elif not cur.is_blocked():
                return Action(ATTACK, target=cur, skill=self.pick_skill())
            else:
                self._engaged_id = None

        mon = self._pick_target(tracker, cursor, kind="monster")
        if mon is None:
            return None
        self._engaged_id = mon.id
        self._engaged_since = now
        return Action(ATTACK, target=mon, reason="새 대상",
                      skill=self.pick_skill())

    # ------------------------------------------------------------------
    @staticmethod
    def _pick_target(tracker, cursor, kind):
        """해당 종류 중 다음에 처리할 대상. 없으면 None."""
        if cursor is None:
            cands = [t for t in tracker.tracks
                     if t.kind == kind and not t.is_blocked()]
            return max(cands, key=lambda t: t.score) if cands else None

        # tracker.next_target 은 종류를 가리지 않으므로 여기서 걸러 쓴다
        saved = tracker.tracks
        try:
            tracker.tracks = [t for t in saved if t.kind == kind]
            return tracker.next_target(cursor[0], cursor[1])
        finally:
            tracker.tracks = saved
