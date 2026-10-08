"""CPU との対局の画面の状態（対局・打牌の評価・設定・成績）を動かす。

状態はセッション（ふつうは st.session_state）に置き、同じ内容の小さな記録をブラウザ内保存にも残す。
通信が切れてセッションが消えても、開き直せば続きから打てる。

    session = GameSession(st.session_state, store)
    if not session.started:
        session.start(generation)       # ブラウザに残っていた設定・成績・対局を読み込む（無ければ新しい対局）
    session.sync_code(generation)       # コードが更新されていたら、古い型のオブジェクトを作り直す
    session.pick(tile_id, riichi)       # 1 枚切る（リーチを宣言して切る）
    session.act("tsumo" | "ron" | "pass" | "nine")
    session.next_hand()                 # 次の局へ
    session.begin()                     # 新しい対局

CPU の手番は、自分の行動のあとに、まとめて進める（engine.cpu.advance）。自分が行動を決める番になるか、局が終わるまで。
画面の部品（Streamlit）には触れない。画面なしでテストできる。
"""
from __future__ import annotations

import json
import secrets
import time
from collections.abc import Callable, MutableMapping
from typing import Any

from engine import game as g
from engine.cpu import advance, human_turn
from engine.game import HUMAN, CpuLevel, GameConfig, GameState, Length, Move
from engine.game_coach import TurnDecision, judge_turn, turn_advice
from engine.game_records import (
    MAX_RECORDS,
    GameRecord,
    Tally,
    add_record,
    dump_record,
    load_history,
    record_of,
)
from engine.luck import LuckSettings
from engine.progress import add_stamps
from engine.rules import Rules
from engine.scoring.explain import explain
from ui.practice_view import HINT_AFTER, HINT_BEFORE, HINT_OFF, LEVEL_FULL, LEVEL_MIN, LEVEL_NORMAL
from ui.progress_store import GAME_HISTORY_NAME, GAME_NAME, GAME_SETTINGS_NAME, Store, read_stamps, write_stamps
from ui.progress_store import parse_json as _parse_json

SAVE_VERSION = 1
MAX_SEED = 999_999
MOVES_TOGETHER, MOVES_EACH = "together", "each"
#: 画面で切り替えられるルール（初期値は雀魂の段位戦）
GAME_RULES = ("multiple_ron", "abortive_draws", "nagashi_mangan", "tobi")

#: 初めて開いたときの設定。ツキ補正は「弱」（25）。CPU の補正は 0。
#: 「強」（75）だと、CPU のリーチを受ける前にあがってしまうことが多く、守備（オリ）の練習の場面がほとんど来ない
#: （CPU 同士の対局での計測：CPU のリーチを受けた局は、自分の補正 75 で 27%、25 で 65%、0 で 80%。docs/DESIGN.md の 5 章）
DEFAULT_SETTINGS: dict[str, Any] = {
    "length": Length.EAST.value,
    "cpu_level": CpuLevel.NORMAL.value,
    "deal": 25,
    "draw": 25,
    "cpu_deal": 0,
    "cpu_draw": 0,
    "hint": HINT_BEFORE,
    "level": LEVEL_NORMAL,
    "mark": True,
    "moves": MOVES_TOGETHER,
    "rules": {name: True for name in GAME_RULES},
}


def clean_settings(data: object, base: dict[str, Any] | None = None) -> dict[str, Any]:
    """設定の値を確かめる。base（指定が無ければ初期値）から始めて、正しい値だけを上書きする"""
    result = json.loads(json.dumps(DEFAULT_SETTINGS if base is None else base))
    if not isinstance(data, dict):
        return result
    if data.get("length") in {item.value for item in Length}:
        result["length"] = data["length"]
    if data.get("cpu_level") in {item.value for item in CpuLevel}:
        result["cpu_level"] = data["cpu_level"]
    for name in ("deal", "draw", "cpu_deal", "cpu_draw"):
        value = data.get(name)
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100:
            result[name] = value
    if data.get("hint") in (HINT_BEFORE, HINT_AFTER, HINT_OFF):
        result["hint"] = data["hint"]
    if data.get("level") in (LEVEL_MIN, LEVEL_NORMAL, LEVEL_FULL) and not isinstance(data.get("level"), bool):
        result["level"] = data["level"]
    if isinstance(data.get("mark"), bool):
        result["mark"] = data["mark"]
    if data.get("moves") in (MOVES_TOGETHER, MOVES_EACH):
        result["moves"] = data["moves"]
    rules = data.get("rules")
    if isinstance(rules, dict):
        for name in GAME_RULES:
            if isinstance(rules.get(name), bool):
                result["rules"][name] = rules[name]
    return result


def config_of(settings: dict[str, Any], seed: int) -> GameConfig:
    return GameConfig(
        seed=seed,
        length=Length(settings["length"]),
        luck=LuckSettings(settings["deal"], settings["draw"]),
        cpu_luck=LuckSettings(settings["cpu_deal"], settings["cpu_draw"]),
        cpu_level=CpuLevel(settings["cpu_level"]),
        rules=Rules(**settings["rules"]),
    )


def decisions_of(game: GameState) -> list[TurnDecision]:
    """いまの局で、自分が選んだ打牌の評価を作り直す（続きから再開したとき）。リーチのあとの自動のツモ切りは数えない"""
    current = game.current
    hand = g.start_hand(game.config, current.start)
    found = []
    for action in current.actions:
        manual = (
            action.seat == HUMAN
            and action.move in (Move.DISCARD, Move.RIICHI)
            and not hand.players[HUMAN].in_riichi
        )
        if manual:
            advice = turn_advice(hand, HUMAN)
            found.append(judge_turn(advice, action, number=len(hand.players[HUMAN].draws)))
        hand = g.apply_hand(game.config, hand, action)
    return found


def tally_of(decisions: list[TurnDecision]) -> Tally:
    defense = [d for d in decisions if d.safety is not None and d.advice.stance.value == "fold"]
    return Tally(
        decisions=len(decisions),
        followed=sum(1 for d in decisions if d.followed),
        defense=len(defense),
        safe=sum(1 for d in defense if d.safety is not None and d.safety.grade.value == "safe"),
    )


class GameSession:
    def __init__(
        self,
        session: MutableMapping[str, Any],
        store: Store,
        *,
        now: Callable[[], float] = time.time,
        new_seed: Callable[[], int] = lambda: secrets.randbelow(MAX_SEED + 1),
    ) -> None:
        self._s = session
        self._store = store
        self._now = now
        self._new_seed = new_seed

    # ------------------------------------------------------------ 読み取り

    @property
    def started(self) -> bool:
        return "gm_game" in self._s

    @property
    def game(self) -> GameState:
        return self._s["gm_game"]

    @property
    def decisions(self) -> list[TurnDecision]:
        """いまの局で、自分が選んだ打牌の評価（古い順）"""
        return self._s["gm_decisions"]

    @property
    def last_decision(self) -> TurnDecision | None:
        return self.decisions[-1] if self.decisions else None

    @property
    def rev(self) -> int:
        return self._s["gm_rev"]

    @property
    def counted(self) -> bool:
        return self._s["gm_counted"]

    @property
    def hinted(self) -> bool:
        return self._s["gm_hinted"]

    @property
    def resumed(self) -> bool:
        return self._s.get("gm_resumed", False)

    @property
    def settings(self) -> dict[str, Any]:
        return self._s["gm_settings"]

    @property
    def history(self) -> list[GameRecord]:
        return self._s["gm_history"]

    @property
    def mark(self) -> int:
        """いまの局の行動のうち、自分が最後に行動したあとの位置（ここから先が、CPU の動き）"""
        return self._s.get("gm_mark", 0)

    @property
    def tally(self) -> Tally:
        """この対局の、自分の打牌の評価の集計（いまの局を含む）"""
        return self._s.get("gm_tally", Tally()).add(tally_of(self.decisions))

    @property
    def fresh_stamps(self) -> list[str]:
        return self._s.get("gm_fresh", [])

    @property
    def config_changed(self) -> bool:
        """いまの対局の設定（長さ・CPU・補正・ルール）が、設定と違うか"""
        return config_of(self.settings, self.game.config.seed) != self.game.config

    # ------------------------------------------------------------ 始める

    def start(self, generation: int = 0) -> None:
        """セッションの最初に 1 度呼ぶ。ブラウザに残っていた設定・成績・対局を読み込む"""
        self._s["gm_settings"] = clean_settings(_parse_json(self._store.get(GAME_SETTINGS_NAME)))
        self._s["gm_history"] = load_history(self._store.get(GAME_HISTORY_NAME))
        self._s["gm_generation"] = generation
        # 番号の出発点は、セッションごとに変える（ui/practice_session.py と同じ理由）
        self._s["gm_rev"] = int(self._now() * 1000) % 1_000_000_000 * 100
        if not self._adopt(_parse_json(self._store.get(GAME_NAME)), resumed=True):
            self.begin()

    def begin(self, seed: int | None = None) -> None:
        """新しい対局を始める。番号を指定した対局は、成績に入れない"""
        counted = seed is None
        config = config_of(self.settings, self._new_seed() if seed is None else seed)
        game = advance(g.start_game(config))
        self._s["gm_game"] = game
        self._s["gm_decisions"] = []
        self._s["gm_tally"] = Tally()
        self._s["gm_counted"] = counted
        self._s["gm_hinted"] = False
        self._s["gm_resumed"] = False
        self._s["gm_recorded"] = False
        self._s["gm_fresh"] = []
        self._s["gm_mark"] = 0
        self._s["gm_scroll"] = True
        self._s.pop("gm_stamped", None)          # 同じ番号の対局を打ち直しても、あがりにスタンプを押せるように
        self._bump()
        self._after(game)

    def take_scroll(self) -> bool:
        """新しい局を始めた直後の 1 回だけ True（画面のいちばん上までスクロールを戻す合図）"""
        return bool(self._s.pop("gm_scroll", False))

    def _adopt(self, data: object, *, resumed: bool) -> bool:
        """保存してあった記録から、対局を作り直してセッションに入れる。作り直せなければ False（例外は外に出さない）"""
        if not isinstance(data, dict) or data.get("v") != SAVE_VERSION:
            return False
        try:
            game = g.from_save(data.get("save"))
        except Exception:  # どんな壊れ方でも「記録なし」として扱う
            return False
        try:
            decisions = decisions_of(game)
        except Exception:  # 打牌の評価だけが作れないときは、評価を空にして対局は続ける
            decisions = []
        if not game.finished and game.current.result is None and not human_turn(game):
            # CPU の番で止まっている記録（途中で切れた、など）。CPU を進めて、自分の番から始める
            try:
                game = advance(game)
            except Exception:  # 進められない記録は「記録なし」として扱う
                return False
        self._s["gm_game"] = game
        self._s["gm_decisions"] = decisions
        self._s["gm_tally"] = Tally.from_dict(data.get("tally"))
        self._s["gm_counted"] = data.get("counted") is True
        self._s["gm_hinted"] = data.get("hinted") is True
        self._s["gm_recorded"] = data.get("recorded") is True
        self._s["gm_resumed"] = resumed
        self._s.setdefault("gm_fresh", [])
        mark = data.get("mark")
        size = len(game.current.actions)
        self._s["gm_mark"] = mark if isinstance(mark, int) and not isinstance(mark, bool) and 0 <= mark <= size else size
        self._s["gm_save"] = self._data()
        return True

    # ------------------------------------------------------------ コードの更新

    def sync_code(self, generation: int) -> None:
        """コードが更新されていたら、セッションに残っているオブジェクトを新しい型で作り直す（ui/practice_session.py と同じ）"""
        if self._s.get("gm_generation") == generation:
            return
        self._s["gm_generation"] = generation
        rows = []
        for record in self._s.get("gm_history", []):
            try:
                rows.append(record.to_dict())
            except Exception:  # 古い型の記録が読めなければ、その 1 件は捨てる
                continue
        self._s["gm_history"] = load_history(json.dumps(rows))
        self._s["gm_settings"] = clean_settings(self._s.get("gm_settings"))
        saved = self._s.get("gm_save")
        if not self._adopt(saved, resumed=self.resumed):
            self.begin()

    # ------------------------------------------------------------ 打つ

    def note_hint_shown(self) -> None:
        """打つ前のヒント（おすすめ）を画面に出した、と記録する。この対局は「ヒントあり」になる"""
        if not self.hinted:
            self._s["gm_hinted"] = True
            self._save()

    def pick(self, tile_id: int, *, riichi: bool = False) -> bool:
        """1 枚切る。できない操作（画面が古かった、など）なら何もせず False"""
        game = self.game
        if not human_turn(game) or game.current.phase is not g.Phase.DRAW:
            self._bump()
            return False
        hand = game.current
        action = g.riichi(HUMAN, tile_id) if riichi else g.discard(HUMAN, tile_id)
        try:
            after = g.apply(game, action)
        except g.GameError:
            self._bump()
            return False
        advice = turn_advice(hand, HUMAN)
        self.decisions.append(judge_turn(advice, action, number=len(hand.players[HUMAN].draws)))
        self._advance(after)
        return True

    def act(self, key: str) -> bool:
        """牌を切らずにする操作：tsumo（ツモあがり）・ron（ロン）・pass（見送る）・nine（九種九牌）"""
        builders = {"tsumo": g.tsumo, "ron": g.ron, "pass": g.pass_, "nine": g.nine}
        game = self.game
        if key not in builders or not human_turn(game):
            self._bump()
            return False
        try:
            after = g.apply(game, builders[key](HUMAN))
        except g.GameError:
            self._bump()
            return False
        self._advance(after)
        return True

    def _advance(self, after: GameState) -> None:
        self._s["gm_mark"] = len(after.current.actions)
        self._s["gm_resumed"] = False
        after = advance(after)
        self._s["gm_game"] = after
        self._bump()
        self._after(after)

    def next_hand(self, expected: int | None = None) -> bool:
        """次の局を始める（局が終わっていて、対局が終わっていないとき）。

        expected には、ボタンを描いたときの局の数を渡す。違っていれば（二度押しで、もう次の局に進んでいる）何もしない。
        そうしないと、新しい局が自分の番の前に終わったとき（CPU の天和・九種九牌など）、その結果を見ないまま、さらに次へ進んでしまう。
        """
        game = self.game
        if not game.between_hands or (expected is not None and expected != len(game.hands)):
            self._bump()
            return False
        try:
            started = g.next_hand(game)
        except g.GameError:
            self._bump()
            return False
        self._s["gm_tally"] = self._s.get("gm_tally", Tally()).add(tally_of(self.decisions))
        self._s["gm_decisions"] = []
        self._s["gm_fresh"] = []
        game = advance(started)
        self._s["gm_game"] = game
        self._s["gm_mark"] = 0
        self._s["gm_scroll"] = True
        self._s["gm_resumed"] = False
        self._bump()
        self._after(game)
        return True

    def _after(self, game: GameState) -> None:
        """行動のあと：局が終わっていればスタンプ、対局が終わっていれば成績。最後に保存"""
        hand = game.current
        if hand.result is not None and self._s.get("gm_stamped") != (game.config.seed, hand.start.number):
            self._s["gm_stamped"] = (game.config.seed, hand.start.number)
            self._stamp(game)
        if game.finished and not self._s.get("gm_recorded") and self.counted:
            now = int(self._now())
            made = record_of(game, self.tally, time=now, hinted=self.hinted)
            self._s["gm_history"] = add_record(self.history, made)
            self._store.append(GAME_HISTORY_NAME, dump_record(made), limit=MAX_RECORDS)
            self._s["gm_recorded"] = True
        self._save()

    def _stamp(self, game: GameState) -> None:
        """自分のあがりに付いた役に、スタンプを押す（成績に入れない対局でも押す）"""
        self._s["gm_fresh"] = []
        result = game.current.result
        if result is None:
            return
        keys: list[str] = []
        for win in result.wins:
            if win.seat != HUMAN:
                continue
            best = explain(win.ctx, game.config.rules).best
            if best is not None:
                keys.extend(item.key for item in best.evaluation.yaku)
        if not keys:
            return
        stamps, fresh = add_stamps(read_stamps(self._store), keys, time=int(self._now()), plain=game.config.luck.is_off)
        write_stamps(self._store, stamps)
        self._s["gm_fresh"] = fresh

    def _bump(self) -> None:
        self._s["gm_rev"] = self._s.get("gm_rev", 0) + 1

    # ------------------------------------------------------------ 設定と成績

    def update_settings(self, values: dict[str, Any]) -> None:
        merged = clean_settings(values, base=self.settings)
        if merged != self.settings:
            self._s["gm_settings"] = merged
        self._store.set(GAME_SETTINGS_NAME, json.dumps(merged))

    def clear_history(self) -> None:
        self._s["gm_history"] = []
        self._store.remove(GAME_HISTORY_NAME)

    # ------------------------------------------------------------ ブラウザ内保存

    def _data(self) -> dict[str, Any]:
        return {
            "v": SAVE_VERSION,
            "save": g.to_save(self.game),
            "counted": self.counted,
            "hinted": self.hinted,
            "recorded": bool(self._s.get("gm_recorded")),
            "tally": self._s.get("gm_tally", Tally()).to_dict(),
            "mark": self.mark,
        }

    def _save(self) -> None:
        data = self._data()
        self._s["gm_save"] = data
        self._store.set(GAME_NAME, json.dumps(data, separators=(",", ":")))
