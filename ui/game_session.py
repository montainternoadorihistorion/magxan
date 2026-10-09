"""CPU との対局の画面の状態（対局・打牌の評価・設定・成績）を動かす。

状態はセッション（ふつうは st.session_state）に置き、同じ内容の小さな記録をブラウザ内保存にも残す。
通信が切れてセッションが消えても、開き直せば続きから打てる。

    session = GameSession(st.session_state, store)
    if not session.started:
        session.start(generation)       # ブラウザに残っていた設定・成績・対局を読み込む（無ければ新しい対局）
    session.sync_code(generation)       # コードが更新されていたら、古い型のオブジェクトを作り直す
    session.pick(tile_id, riichi)       # 1 枚切る（リーチを宣言して切る）
    session.act("tsumo" | "ron" | "pass" | "nine" | "call:N" | "kan:牌ID")
    session.next_hand()                 # 次の局へ
    session.begin()                     # 新しい対局

call:N は、鳴ける牌への返事のうち N 番目の鳴き（HandState.call_actions からロンを除いた並び）。
kan:牌ID は、自分の番の暗槓・加槓。

CPU の手番は、自分の行動のあとに、まとめて進める（engine.cpu.advance）。自分が行動を決める番になるか、局が終わるまで。
おまかせ補正：設定の auto を入れておくと、新しい対局（成績に入れる対局）を始めるたびに、自分のツキ補正の段階を
成績から決め直す（engine/auto_luck.py・ui/auto_state.py。CPU の補正は変えない）。
画面の部品（Streamlit）には触れない。画面なしでテストできる。
"""
from __future__ import annotations

import json
import secrets
import time
from collections.abc import Callable, MutableMapping
from typing import Any

from engine import game as g
from engine.auto_luck import MIN_GAMES, AutoDecision, decision_data, decision_from_data, game_play
from engine.call_coach import CallDecision
from engine.cpu import advance, human_turn
from engine.declare import DeclareQuiz
from engine.game import HUMAN, CpuLevel, GameConfig, GameState, Length, Move
from engine.game_coach import TurnDecision
from engine.game_records import (
    MAX_RECORDS,
    GameRecord,
    Tally,
    add_record,
    dump_record,
    load_history,
    record_of,
)
from engine.kifu import Kifu, kifu_of
from engine.luck import LuckSettings
from engine.progress import add_stamps
from engine.review import human_decisions, judge_action
from engine.rules import Rules
from engine.scoring.explain import explain
from ui.auto_state import AUTO_DEFAULTS, clean_auto, judge, step_values, turn_on
from ui.declare_state import clean_declared, declared_state, record_declaration, skipped_state
from ui.game_view import kifu_notes
from ui.practice_view import HINT_AFTER, HINT_BEFORE, HINT_OFF, LEVEL_FULL, LEVEL_MIN, LEVEL_NORMAL
from ui.progress_store import GAME_HISTORY_NAME, GAME_NAME, GAME_SETTINGS_NAME, Store, read_stamps, write_stamps
from ui.progress_store import parse_json as _parse_json

SAVE_VERSION = 1
MAX_SEED = 999_999
MOVES_TOGETHER, MOVES_EACH = "together", "each"
#: 画面で切り替えられるルール（初期値は雀魂の段位戦）。calls は鳴きあり・なし（なしなら門前だけ。Phase 3 と同じ）
GAME_RULES = ("multiple_ron", "abortive_draws", "nagashi_mangan", "tobi", "calls")
#: 鳴きの返事のボタンの名前の頭（call:0、call:1 …）と、自分の番のカン（kan:牌ID）
CALL_KEY, KAN_KEY = "call:", "kan:"

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
    "declare": True,         # あがったら、解説の前に点数を申告する（Phase 5）
    **AUTO_DEFAULTS,         # おまかせ補正（Phase 5。ui/auto_state.py）
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
    for name in ("mark", "declare"):
        if isinstance(data.get(name), bool):
            result[name] = data[name]
    if data.get("moves") in (MOVES_TOGETHER, MOVES_EACH):
        result["moves"] = data["moves"]
    rules = data.get("rules")
    if isinstance(rules, dict):
        for name in GAME_RULES:
            if isinstance(rules.get(name), bool):
                result["rules"][name] = rules[name]
    clean_auto(data, result)
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


def _rebuild(game: GameState) -> tuple[list[TurnDecision], list[CallDecision], str | None]:
    """いまの局の自分の判断の評価と、いちばん最近の判断の種類（turn ＝ 打牌・call ＝ 鳴きの返事・None ＝ まだ無い）"""
    turns: list[TurnDecision] = []
    calls: list[CallDecision] = []
    last = None
    for _, decision in human_decisions(game.config, game.current):
        if isinstance(decision, CallDecision):
            calls.append(decision)
            last = "call"
        else:
            turns.append(decision)
            last = "turn"
    return turns, calls, last


def decisions_of(game: GameState) -> tuple[list[TurnDecision], list[CallDecision]]:
    """いまの局で、自分が選んだ打牌と鳴きの返事の評価を作り直す（続きから再開したとき）。リーチのあとの自動のツモ切りは数えない"""
    turns, calls, _ = _rebuild(game)
    return turns, calls


def _folding(decision: TurnDecision) -> bool:
    """リーチを受けていて、オリるべき局面での打牌か"""
    return decision.safety is not None and decision.advice.stance.value == "fold"


def good_turn(decision: TurnDecision) -> bool:
    """コーチの評価がいちばん良い打牌か（engine.game_records.Tally.good を参照）"""
    if _folding(decision):
        return decision.safety is not None and decision.safety.grade.value == "safe"
    return decision.verdict.is_best and not decision.lost_yaku and not decision.yaku_detour


def tally_of(decisions: list[TurnDecision], calls: list[CallDecision] | None = None) -> Tally:
    defense = [d for d in decisions if _folding(d)]
    made = [c for c in (calls or []) if c.called]
    return Tally(
        decisions=len(decisions),
        followed=sum(1 for d in decisions if d.followed),
        defense=len(defense),
        safe=sum(1 for d in defense if d.safety is not None and d.safety.grade.value == "safe"),
        calls=len(made),
        bad_calls=sum(1 for c in made if c.no_yaku),
        good=sum(1 for d in decisions if good_turn(d)),
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
    def calls(self) -> list[CallDecision]:
        """いまの局で、鳴ける牌に返事をした評価（古い順）"""
        return self._s.setdefault("gm_calls", [])

    @property
    def last_call(self) -> CallDecision | None:
        """いちばん最近の自分の判断が、鳴ける牌への返事だったとき、その評価"""
        if self._s.get("gm_last") != "call" or not self.calls:
            return None
        return self.calls[-1]

    @property
    def dora_seen(self) -> int | None:
        """自分が最後に行動する前に見えていた、ドラ表示牌の枚数（カンでドラが増えたことを知らせるため。分からなければ None）"""
        value = self._s.get("gm_dora_seen")
        return value if isinstance(value, int) else None

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
        """この対局の、自分の打牌と鳴きの評価の集計（いまの局を含む）"""
        return self._s.get("gm_tally", Tally()).add(tally_of(self.decisions, self.calls))

    @property
    def fresh_stamps(self) -> list[str]:
        return self._s.get("gm_fresh", [])

    @property
    def declared(self) -> dict[str, Any] | None:
        """いまの局で、点数を申告した（または申告しないことにした）記録。まだなら None。
        {"hand": 局の番号, "picked": 選んだ点（申告しなかったら None）, "answer": 正しい点, "why": 理由}"""
        state = self._s.get("gm_declared")
        if isinstance(state, dict) and state.get("hand") == self.game.current.start.number:
            return state
        return None

    @property
    def declare_fair(self) -> bool:
        """この局の申告を、記録に入れるか（成績に入れる対局で、打つ前のヒントを見ていない。ui/declare_state.py）"""
        return self.counted and not self.hinted

    @property
    def declared_rev(self) -> int:
        """申告するか、申告しないことにするたびに増える番号（答え合わせを、画面の上から見せる合図）"""
        return int(self._s.get("gm_declared_rev", 0))

    def declare(self, quiz: DeclareQuiz, picked: str) -> bool:
        """あがった手の点数を申告する（いまの局で 1 回だけ）。→ 正解したか。記録に入れるのは declare_fair のときだけ"""
        if self.declared is not None or picked not in quiz.choices:
            self._bump()
            return False
        fair = self.declare_fair
        correct = record_declaration(self._store, quiz, picked, now=self._now()) if fair else quiz.correct(picked)
        self._s["gm_declared"] = declared_state(self.game.current.start.number, quiz, picked, recorded=fair)
        self._s["gm_declared_rev"] = self.declared_rev + 1
        self._bump()
        self._save()
        return correct

    def skip_declare(self) -> None:
        """申告しないで、結果を見る（記録には残さない）"""
        if self.declared is None:
            self._s["gm_declared"] = skipped_state(self.game.current.start.number)
            self._s["gm_declared_rev"] = self.declared_rev + 1
        self._bump()
        self._save()

    def result_shown(self) -> None:
        """あがりの結果（点数）を、申告の問題を出さずに見せた。あとで申告の設定を入れても、この局では問題を出さない"""
        if self.declared is None and self.game.current.result is not None:
            self._s["gm_declared"] = skipped_state(self.game.current.start.number)
            self._save()

    @property
    def config_changed(self) -> bool:
        """いまの対局の設定（長さ・CPU・補正・ルール）が、設定と違うか"""
        return config_of(self.settings, self.game.config.seed) != self.game.config

    # ------------------------------------------------------------ おまかせ補正

    @property
    def auto(self) -> bool:
        """おまかせ補正にしているか"""
        return self.settings.get("auto") is True

    def set_auto(self, on: bool) -> None:
        """おまかせ補正を入れる・切る（ui/practice_session.py と同じ）"""
        if on == self.auto:
            return
        self.update_settings(turn_on(self.settings, int(self._now())) if on else {"auto": False})

    def auto_preview(self) -> AutoDecision:
        """いまの成績で判断すると、どうなるか（次に新しい対局を始めるとき、こう判断する）"""
        return judge(self.settings, lambda since, level: game_play(self.history, since, level), MIN_GAMES, self._store, int(self._now()))

    def take_auto_news(self) -> AutoDecision | None:
        """新しい対局を始めたときに、おまかせが段階を変えていれば、その判断（1 回だけ）"""
        found = decision_from_data(self._s.pop("gm_auto_news", None))
        return found[0] if found is not None else None

    def _auto_step(self) -> None:
        now = int(self._now())
        decision = self.auto_preview()
        values = step_values(self.settings, decision, now)
        if values is not None:
            self.update_settings(values)
        if decision.changed:
            self._s["gm_auto_news"] = decision_data(decision, now)

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
        """新しい対局を始める。番号を指定した対局は、成績に入れない。
        おまかせ補正なら、成績に入れる対局を始める前に、自分の補正の段階を決め直す"""
        counted = seed is None
        if counted and self.auto:
            self._auto_step()
        config = config_of(self.settings, self._new_seed() if seed is None else seed)
        game = advance(g.start_game(config))
        self._s["gm_game"] = game
        self._s["gm_decisions"] = []
        self._s["gm_calls"] = []
        self._s["gm_last"] = None
        self._s.pop("gm_dora_seen", None)
        self._s["gm_tally"] = Tally()
        self._s["gm_counted"] = counted
        self._s["gm_hinted"] = False
        self._s["gm_resumed"] = False
        self._s["gm_recorded"] = False
        self._s["gm_fresh"] = []
        self._s["gm_mark"] = 0
        self._s["gm_scroll"] = True
        self._s.pop("gm_declared", None)
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
            decisions, calls, last = _rebuild(game)
        except Exception:  # 打牌の評価だけが作れないときは、評価を空にして対局は続ける
            decisions, calls, last = [], [], None
        if not game.finished and game.current.result is None and not human_turn(game):
            # CPU の番で止まっている記録（途中で切れた、など）。CPU を進めて、自分の番から始める
            try:
                game = advance(game)
            except Exception:  # 進められない記録は「記録なし」として扱う
                return False
        self._s["gm_game"] = game
        self._s["gm_decisions"] = decisions
        self._s["gm_calls"] = calls
        self._s["gm_last"] = last          # 続きから開いても、いちばん最近の判断の答え合わせを出す
        self._s.pop("gm_dora_seen", None)
        self._s["gm_tally"] = Tally.from_dict(data.get("tally"))
        self._s["gm_counted"] = data.get("counted") is True
        self._s["gm_hinted"] = data.get("hinted") is True
        self._s["gm_recorded"] = data.get("recorded") is True
        self._s["gm_declared"] = clean_declared(data.get("declared"))
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
        self._s.pop("gm_kifu_cache", None)        # 牌譜は、古い型のまま残さず、次に開いたときに作り直す
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
        """1 枚切る。できない操作（画面が古かった、喰い替えの牌、など）なら何もせず False"""
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
        decision = judge_action(hand, HUMAN, action)
        if isinstance(decision, TurnDecision):
            self.decisions.append(decision)
            self._s["gm_last"] = "turn"
        self._s["gm_dora_seen"] = len(hand.dora_indicators)
        self._advance(after)
        return True

    def action_for(self, key: str) -> g.Action | None:
        """ボタンの名前を、いまの局面でできる行動にする（できなければ None）"""
        game = self.game
        if not human_turn(game):
            return None
        hand = game.current
        simple = {"tsumo": g.tsumo, "ron": g.ron, "pass": g.pass_, "nine": g.nine}
        if key in simple:
            return simple[key](HUMAN)
        if key.startswith(CALL_KEY) and key[len(CALL_KEY):].isdigit():
            calls = [a for a in hand.call_actions(HUMAN) if a.move is not Move.RON]
            index = int(key[len(CALL_KEY):])
            return calls[index] if index < len(calls) else None
        if key.startswith(KAN_KEY) and key[len(KAN_KEY):].isdigit():
            tile = int(key[len(KAN_KEY):])
            if tile in hand.kakan_tiles(HUMAN):
                return g.kakan(HUMAN, tile)
            if tile in hand.ankan_tiles(HUMAN):
                return g.ankan(HUMAN, tile)
        return None

    def act(self, key: str) -> bool:
        """牌を切らずにする操作：tsumo・ron・pass・nine・call:N（鳴き）・kan:牌ID（暗槓・加槓）"""
        game = self.game
        action = self.action_for(key)
        if action is None:
            self._bump()
            return False
        hand = game.current
        try:
            after = g.apply(game, action)
        except g.GameError:
            self._bump()
            return False
        decision = judge_action(hand, HUMAN, action)
        if isinstance(decision, CallDecision):
            self.calls.append(decision)
            self._s["gm_last"] = "call"
        self._s["gm_dora_seen"] = len(hand.dora_indicators)
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
        self._s["gm_tally"] = self._s.get("gm_tally", Tally()).add(tally_of(self.decisions, self.calls))
        self._s["gm_decisions"] = []
        self._s["gm_calls"] = []
        self._s["gm_last"] = None
        self._s.pop("gm_dora_seen", None)
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

    def kifu(self, index: int) -> Kifu:
        """その局（0 始まり）の牌譜（自分の判断の評価つき）。作るのに時間がかかるので、局ごとに覚えておく"""
        game = self.game
        hand = game.hands[index]
        key = (repr(game.config.to_dict()), index, len(hand.actions))
        cache = self._s.setdefault("gm_kifu_cache", {})
        if key not in cache:
            notes = kifu_notes(human_decisions(game.config, hand))
            if len(cache) > 8:
                cache.clear()
            cache[key] = kifu_of(game.config, hand, notes)
        return cache[key]

    def refresh(self) -> None:
        """画面だけを描き直す（手牌の部品が、次の入力を受け付けるように番号を進める）"""
        self._bump()

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
            "declared": self._s.get("gm_declared"),
        }

    def _save(self) -> None:
        data = self._data()
        self._s["gm_save"] = data
        self._store.set(GAME_NAME, json.dumps(data, separators=(",", ":")))
