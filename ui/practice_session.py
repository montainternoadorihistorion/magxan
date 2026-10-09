"""一人練習の画面の状態（局・打牌の評価・設定・成績）を動かす。

状態はセッション（ふつうは st.session_state）に置き、同じ内容の小さな記録をブラウザ内保存にも残す。
通信が切れてセッションが消えても、開き直せば続きから打てる。

    session = PracticeSession(st.session_state, store)
    if not session.started:
        session.start()                 # ブラウザに残っていた設定・成績・局を読み込む（無ければ新しい局）
    session.sync_code(generation)       # コードが更新されていたら、古い型のオブジェクトを作り直す
    session.note_hint_shown()           # 打つ前のヒントを画面に出したときに呼ぶ（この局は「ヒントあり」になる）
    session.pick(tile_id, riichi)       # 1 枚切る（リーチを宣言して切る）
    session.tsumo()                     # ツモあがり
    session.begin()                     # 次の局
    session.again()                     # 同じ局をもう一度

役指定練習：設定の target に、狙う役（図鑑のページの鍵）を入れておくと、次の局から、その役を狙う局になる。
あがった局では、付いた役にスタンプを押す（progress.stamps）。成績に入れない局（やり直しなど）でも押す。

おまかせ補正：設定の auto を入れておくと、新しい局（成績に入れる局）を始めるたびに、成績からツキ補正の段階を決め直す
（engine/auto_luck.py・ui/auto_state.py）。段階を変えたときは、take_auto_news() で 1 回だけ知らせる。

画面の部品（Streamlit）には触れない。画面なしでテストできる。
"""
from __future__ import annotations

import json
import secrets
import time
import unicodedata
from collections.abc import Callable, MutableMapping
from typing import Any

from engine import practice
from engine.analysis.target import TARGET_KEYS
from engine.auto_luck import MIN_HANDS, AutoDecision, decision_data, decision_from_data, practice_play
from engine.declare import DeclareQuiz
from engine.luck import PRESETS, LuckSettings
from engine.practice import Decision, Outcome, PracticeConfig, PracticeState
from engine.progress import add_stamps
from engine.records import MAX_RECORDS, HandRecord, add_record, dump_record, load_history, record_of
from engine.scoring.explain import explain
from ui.auto_state import AUTO_DEFAULTS, clean_auto, judge, step_values, turn_on
from ui.declare_state import clean_declared, declared_state, record_declaration, skipped_state
from ui.practice_view import HINT_AFTER, HINT_BEFORE, HINT_OFF, LEVEL_FULL, LEVEL_MIN, LEVEL_NORMAL
from ui.progress_store import HAND_NAME, HISTORY_NAME, SETTINGS_NAME, Store, read_stamps, write_stamps
from ui.progress_store import parse_json as _parse_json

__all__ = ["HAND_NAME", "HISTORY_NAME", "SETTINGS_NAME", "PracticeSession", "Store", "clean_settings", "parse_seed", "preset_name"]

SAVE_VERSION = 1
MAX_SEED = 999_999
#: 役指定練習で、その役が作れる山に当たるまで、番号を引き直す回数の上限
MAX_DEALS = 40

#: 初めて開いたときの設定。カリキュラムの最初の段階（補正：強、ヒントは打つ前）に合わせてある
DEFAULT_SETTINGS: dict[str, Any] = {
    "deal": 75,              # 配牌の良さ
    "draw": 75,              # ツモの良さ
    "tenpai_deal": False,    # 配牌で聴牌している候補も採用するか
    "mark": True,            # 補正によるツモに印を付けるか
    "hint": HINT_BEFORE,     # ヒントのタイミング
    "level": LEVEL_NORMAL,   # コーチの表示量
    "target": None,          # 役指定練習で狙う役（図鑑のページの鍵）。None なら、ふつうの一人練習
    "declare": True,         # あがったら、解説の前に点数を申告する（Phase 5）
    **AUTO_DEFAULTS,         # おまかせ補正（Phase 5。ui/auto_state.py）
}


def clean_settings(data: object, base: dict[str, Any] | None = None) -> dict[str, Any]:
    """設定の値を確かめる。base（指定が無ければ初期値）から始めて、正しい値だけを上書きする"""
    result = dict(DEFAULT_SETTINGS if base is None else base)
    if not isinstance(data, dict):
        return result
    for name in ("deal", "draw"):
        value = data.get(name)
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100:
            result[name] = value
    for name in ("tenpai_deal", "mark", "declare"):
        if isinstance(data.get(name), bool):
            result[name] = data[name]
    if data.get("hint") in (HINT_BEFORE, HINT_AFTER, HINT_OFF):
        result["hint"] = data["hint"]
    if data.get("level") in (LEVEL_MIN, LEVEL_NORMAL, LEVEL_FULL) and not isinstance(data.get("level"), bool):
        result["level"] = data["level"]
    if "target" in data and (data["target"] is None or (isinstance(data["target"], str) and data["target"] in TARGET_KEYS)):
        result["target"] = data["target"]
    clean_auto(data, result)
    return result


def preset_name(deal: int, draw: int) -> str | None:
    """2 つのスライダーの値が、決まった段階（なし・弱・中・強・最大）のどれかに当たるなら、その名前"""
    return next((name for name, level in PRESETS if deal == draw == level), None)


def parse_seed(text: object) -> int | None:
    """入力された局の番号を読む。0〜MAX_SEED の整数でなければ None（全角の数字も受け付ける）"""
    if not isinstance(text, str):
        return None
    digits = unicodedata.normalize("NFKC", text).strip()
    if not (digits.isascii() and digits.isdigit()) or len(digits) > len(str(MAX_SEED)):
        return None
    return int(digits)


class PracticeSession:
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
        return "pr_state" in self._s

    @property
    def state(self) -> PracticeState:
        return self._s["pr_state"]

    @property
    def decisions(self) -> list[Decision]:
        """この局で自分が選んだ打牌の評価（古い順）"""
        return self._s["pr_decisions"]

    @property
    def last_decision(self) -> Decision | None:
        return self.decisions[-1] if self.decisions else None

    @property
    def rev(self) -> int:
        """行動を 1 つ処理するたびに増える番号（手牌の部品に「応答した」と伝える）"""
        return self._s["pr_rev"]

    @property
    def counted(self) -> bool:
        """この局を成績に入れるか（やり直しと、番号を指定した局は入れない）"""
        return self._s["pr_counted"]

    @property
    def hinted(self) -> bool:
        """この局で、打つ前のヒント（おすすめ）が 1 回でも画面に出たか"""
        return self._s["pr_hinted"]

    @property
    def resumed(self) -> bool:
        """ブラウザに残っていた記録から再開した局か"""
        return self._s.get("pr_resumed", False)

    @property
    def settings(self) -> dict[str, Any]:
        return self._s["pr_settings"]

    @property
    def history(self) -> list[HandRecord]:
        return self._s["pr_history"]

    @property
    def luck(self) -> LuckSettings:
        """設定されているツキ補正（次に始める局に使う）"""
        settings = self.settings
        return LuckSettings(settings["deal"], settings["draw"], settings["tenpai_deal"])

    @property
    def luck_changed(self) -> bool:
        """いま打っている局のツキ補正が、設定と違うか（設定を変えた直後）"""
        return self.state.config.luck != self.luck

    @property
    def target(self) -> str | None:
        """設定されている、役指定練習で狙う役（次に始める局に使う）"""
        return self.settings.get("target")

    @property
    def target_changed(self) -> bool:
        """いま打っている局の狙う役が、設定と違うか（設定を変えた直後）"""
        return self.state.config.target != self.target

    @property
    def fresh_stamps(self) -> list[str]:
        """この局のあがりで、はじめてスタンプが押された役（図鑑のページの鍵）"""
        return self._s.get("pr_fresh", [])

    @property
    def declared(self) -> dict[str, Any] | None:
        """この局で、点数を申告した（または申告しないことにした）記録。まだなら None（ui.declare_state の形）"""
        state = self._s.get("pr_declared")
        return state if isinstance(state, dict) else None

    @property
    def declare_fair(self) -> bool:
        """この局の申告を、記録に入れるか（成績に入れる局で、打つ前のヒントを見ていない。ui/declare_state.py）"""
        return self.counted and not self.hinted

    @property
    def declared_rev(self) -> int:
        """申告するか、申告しないことにするたびに増える番号（答え合わせを、画面の上から見せる合図）"""
        return int(self._s.get("pr_declared_rev", 0))

    def declare(self, quiz: DeclareQuiz, picked: str) -> bool:
        """あがった手の点数を申告する（この局で 1 回だけ）。→ 正解したか。記録に入れるのは declare_fair のときだけ"""
        if self.declared is not None or not self.state.finished or picked not in quiz.choices:
            self._bump()
            return False
        fair = self.declare_fair
        correct = record_declaration(self._store, quiz, picked, now=self._now()) if fair else quiz.correct(picked)
        self._s["pr_declared"] = declared_state(None, quiz, picked, recorded=fair)
        self._s["pr_declared_rev"] = self.declared_rev + 1
        self._bump()
        self._save_hand()
        return correct

    def skip_declare(self) -> None:
        """申告しないで、結果を見る（記録には残さない）"""
        if self.declared is None:
            self._s["pr_declared"] = skipped_state(None)
            self._s["pr_declared_rev"] = self.declared_rev + 1
        self._bump()
        self._save_hand()

    def result_shown(self) -> None:
        """あがりの結果（点数）を、申告の問題を出さずに見せた。あとで申告の設定を入れても、この局では問題を出さない"""
        if self.declared is None:
            self._s["pr_declared"] = skipped_state(None)
            self._save_hand()

    # ------------------------------------------------------------ おまかせ補正

    @property
    def auto(self) -> bool:
        """おまかせ補正にしているか"""
        return self.settings.get("auto") is True

    def set_auto(self, on: bool) -> None:
        """おまかせ補正を入れる・切る。入れたときは、いまの補正にいちばん近い段階から始める。切ったときは、いまの補正のまま"""
        if on == self.auto:
            return
        self.update_settings(turn_on(self.settings, int(self._now())) if on else {"auto": False})

    def auto_preview(self) -> AutoDecision:
        """いまの成績で判断すると、どうなるか（次に新しい局を始めるとき、こう判断する）"""
        return judge(self.settings, lambda since, level: practice_play(self.history, since, level), MIN_HANDS, self._store, int(self._now()))

    def take_auto_news(self) -> AutoDecision | None:
        """新しい局を始めたときに、おまかせが段階を変えていれば、その判断（1 回だけ。画面で知らせる）"""
        found = decision_from_data(self._s.pop("pr_auto_news", None))
        return found[0] if found is not None else None

    def _auto_step(self) -> None:
        now = int(self._now())
        decision = self.auto_preview()
        values = step_values(self.settings, decision, now)
        if values is not None:
            self.update_settings(values)
        if decision.changed:
            self._s["pr_auto_news"] = decision_data(decision, now)

    # ------------------------------------------------------------ 始める

    def start(self, generation: int = 0) -> None:
        """セッションの最初に 1 度呼ぶ。ブラウザに残っていた設定・成績・局を読み込む。

        generation は、いま動いているコードの世代（sync_code を参照）。
        """
        self._s["pr_settings"] = clean_settings(_parse_json(self._store.get(SETTINGS_NAME)))
        self._s["pr_history"] = load_history(self._store.get(HISTORY_NAME))
        self._s["pr_generation"] = generation
        # 番号の出発点は、セッションごとに変える。通信が切れてセッションが作り直されたとき、手牌の部品が
        # 「番号が変わった＝サーバーが応答した」と気づけるように（同じ 0 から始めると、送信中のまま止まる）
        self._s["pr_rev"] = int(self._now() * 1000) % 1_000_000_000 * 100
        if not self._adopt(_parse_json(self._store.get(HAND_NAME)), resumed=True):
            self.begin()

    def begin(self, seed: int | None = None, *, counted: bool = True) -> None:
        """新しい局を始める。seed を指定した局は、成績に入れない。

        役指定練習では、その役が作れる山に当たるまで、番号を引き直す。必要な牌が王牌（嶺上牌・ドラ表示牌）にしか
        無い山では、どう打っても役が作れないため（補正は王牌に触れない）。番号を指定した局は、引き直さない。
        おまかせ補正なら、成績に入れる局を始める前に、補正の段階を決め直す（番号を指定した局では、決め直さない）。
        """
        if seed is None and counted and self.auto:
            self._auto_step()
        if seed is not None:
            self._open(practice.start(self._config(seed)), counted=False)
            return
        for _ in range(MAX_DEALS):
            state = practice.start(self._config(self._new_seed()))
            if not state.deal.target or state.deal.chosen_distance is not None:
                break
        self._open(state, counted=counted)

    def again(self) -> None:
        """同じ配牌（同じ番号・同じ補正・同じ狙う役）で、もう一度打つ。成績には入れない"""
        self._open(practice.start(self.state.config), counted=False)

    def _config(self, seed: int) -> PracticeConfig:
        return PracticeConfig(seed=seed, luck=self.luck, target=self.target)

    def _open(self, state: PracticeState, *, counted: bool) -> None:
        self._s["pr_state"] = state
        self._s["pr_decisions"] = []
        self._s["pr_counted"] = counted
        self._s["pr_hinted"] = False
        self._s["pr_resumed"] = False
        self._s["pr_fresh"] = []
        self._s.pop("pr_declared", None)
        self._s["pr_scroll"] = True       # 新しい局は、画面のいちばん上から見せる
        self._bump()
        self._save_hand()

    def take_scroll(self) -> bool:
        """新しい局を始めた直後の 1 回だけ True（画面のいちばん上までスクロールを戻す合図）"""
        return bool(self._s.pop("pr_scroll", False))

    def _adopt(self, data: object, *, resumed: bool) -> bool:
        """保存してあった記録（_hand_data の形）から、局を作り直してセッションに入れる。作り直せなければ False。

        記録はブラウザに置いてあるので、壊れていたり、書き換えられていたりすることがある。
        何が入っていても、ここで例外を外に出さない（開くたびにエラーで止まり、直す手段も無くなるのを防ぐ）。
        """
        if not isinstance(data, dict) or data.get("v") != SAVE_VERSION:
            return False
        try:
            state, assessed = practice.from_save_assessed(data.get("save"))       # 作り直しと評価を、1 回のたどりで
            decisions = list(assessed)
        except Exception:  # どんな壊れ方でも「記録なし」として扱う
            return False
        self._s["pr_state"] = state
        self._s["pr_decisions"] = decisions
        self._s["pr_counted"] = data.get("counted") is True
        self._s["pr_hinted"] = data.get("hinted") is True
        self._s["pr_declared"] = clean_declared(data.get("declared")) if state.finished else None
        self._s["pr_resumed"] = resumed
        self._s.setdefault("pr_fresh", [])       # スタンプは、あがった瞬間にだけ押す（再開した局では押し直さない）
        self._s["pr_save"] = self._hand_data()
        return True

    # ------------------------------------------------------------ コードの更新

    def sync_code(self, generation: int) -> None:
        """コードが更新されていたら、セッションに残っているオブジェクトを新しい型で作り直す。

        アプリを更新すると、engine/ と ui/ のモジュールは読み直される（ui/fresh.py）。ところが、セッションに
        入れてあるオブジェクト（局の状態や成績）は、読み直す前の古いクラスのまま残る。古い型と新しい型が
        混ざると、「同じはずのものが同じと判定されない」などの食い違いが起きる（実際に、あがった局が
        流局と表示された）。そこで、世代の番号が変わっていたら、文字と数だけの控えから作り直す。
        """
        if self._s.get("pr_generation") == generation:
            return
        self._s["pr_generation"] = generation
        rows = []
        for record in self._s.get("pr_history", []):
            try:
                rows.append(record.to_dict())
            except Exception:  # 古い型の記録が読めなければ、その 1 件は捨てる
                continue
        self._s["pr_history"] = load_history(json.dumps(rows))
        self._s["pr_settings"] = clean_settings(self._s.get("pr_settings"))
        saved = self._s.get("pr_save")
        if saved is None:                 # 控えを持たない古いコードが作ったセッション。状態から作ってみる
            try:
                saved = self._hand_data()
            except Exception:
                saved = None
        if not self._adopt(saved, resumed=self.resumed):
            self.begin()

    # ------------------------------------------------------------ 打つ

    def note_hint_shown(self) -> None:
        """打つ前のヒント（おすすめ）を画面に出した、と記録する。この局は「ヒントあり」になる。

        切る瞬間の設定ではなく「出したかどうか」で決める。ヒントを見てから設定を切り替えて切っても、
        ヒントなしの局として数えないようにするため。
        """
        if not self.hinted:
            self._s["pr_hinted"] = True
            self._save_hand()

    def pick(self, tile_id: int, *, riichi: bool = False) -> bool:
        """1 枚切る。できない操作（画面が古かった、など）なら何もせず False"""
        state = self.state
        action = practice.riichi(tile_id) if riichi else practice.discard(tile_id)
        try:
            after = practice.apply(state, action)        # できない操作は、ここで断られる
        except practice.PracticeError:
            self._bump()
            return False
        decision = practice.assess(state, action)
        if decision is not None:
            self.decisions.append(decision)
        self._advance(after)
        return True

    def tsumo(self) -> bool:
        """ツモあがり"""
        try:
            after = practice.apply(self.state, practice.TSUMO)
        except practice.PracticeError:
            self._bump()
            return False
        self._advance(after)
        return True

    def _advance(self, after: PracticeState) -> None:
        self._s["pr_state"] = after
        self._s["pr_resumed"] = False
        self._bump()
        if after.finished:
            now = int(self._now())
            self._stamp(after, now)
            if self.counted:
                made = record_of(after, self.decisions, time=now, hinted=self.hinted)
                self._s["pr_history"] = add_record(self.history, made)
                # 全体を書き直さず、ブラウザに残っている配列の末尾に 1 件だけ足す
                self._store.append(HISTORY_NAME, dump_record(made), limit=MAX_RECORDS)
        self._save_hand()

    def _stamp(self, after: PracticeState, now: int) -> None:
        """あがった手に付いた役に、スタンプを押す（成績に入れない局でも押す）"""
        result = after.result
        self._s["pr_fresh"] = []
        if result is None or result.outcome is not Outcome.TSUMO or result.win is None:
            return
        best = explain(result.win, after.config.rules).best
        if best is None:
            return
        keys = [item.key for item in best.evaluation.yaku]
        stamps, fresh = add_stamps(read_stamps(self._store), keys, time=now, plain=after.config.luck.is_off)
        write_stamps(self._store, stamps)
        self._s["pr_fresh"] = fresh

    def _bump(self) -> None:
        self._s["pr_rev"] = self._s.get("pr_rev", 0) + 1

    # ------------------------------------------------------------ 設定と成績

    def update_settings(self, values: dict[str, Any]) -> None:
        """設定を変える（おかしな値は無視して、前の値のままにする）。ブラウザにも残す"""
        merged = clean_settings(values, base=self.settings)
        if merged != self.settings:
            self._s["pr_settings"] = merged
        self._store.set(SETTINGS_NAME, json.dumps(merged))

    def clear_history(self) -> None:
        self._s["pr_history"] = []
        self._store.remove(HISTORY_NAME)

    # ------------------------------------------------------------ ブラウザ内保存

    def _hand_data(self) -> dict[str, Any]:
        """いまの局を、文字と数だけで表したもの（ブラウザに残す形。コードが更新されたあとの作り直しにも使う）"""
        return {"v": SAVE_VERSION, "save": practice.to_save(self.state), "counted": self.counted, "hinted": self.hinted,
                "declared": self._s.get("pr_declared")}

    def _save_hand(self) -> None:
        data = self._hand_data()
        self._s["pr_save"] = data
        self._store.set(HAND_NAME, json.dumps(data, separators=(",", ":")))
