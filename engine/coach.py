"""牌効率コーチ：いまの手牌について「どれを切ると聴牌に近いか」を調べ、切った牌を評価する。

    analyze(position)              →  Analysis   向聴数、打牌候補の表、おすすめ、手牌の分け方、待ち、引ける確率
    judge_discard(analysis, tile)  →  Verdict    実際に切った牌を、おすすめと比べる（理由つき）
    rebase(analysis, kind)         →  Analysis   おすすめをほかの牌に置きかえて、候補の評価を付け直す（対局のコーチが使う）

ここで比べるのは速さ（向聴数と受け入れ枚数）だけ。役や打点、守備との兼ね合いは見ていない
（対局のコーチで加える）。だから「おすすめ」は「いちばん速い打牌」という意味になる。

数値はすべて数え上げで決まる事実（向聴数は判定ライブラリ、受け入れは残り枚数の数え上げ）。
評価のひとことと理由の文章も、その数値から機械的に組み立てる。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import lru_cache

from engine.analysis.advice import Advice, advise, discard_dora, loose_rank, tile_for_discard
from engine.analysis.blocks import PART_NAMES, Layout, Part, best_layout
from engine.analysis.shanten import AGARI, TENPAI, ShantenInfo, shanten_info, shanten_text
from engine.analysis.ukeire import Acceptance, DiscardOption, chance_within, draw_chance, remaining_counts
from engine.analysis.waits import Wait, waits_of
from engine.melds import Meld
from engine.rules import DEFAULT_RULES, Rules
from engine.scoring.decompose import Form
from engine.scoring.dora import dora_kind_of
from engine.scoring.texts import kind_text, kinds_text
from engine.tiles import CHUN, EAST, HAKU, HATSU, NUM_TILES, counts34, is_red, kind_of

HAND_SIZE = 14      # 打牌の前の手牌の枚数（副露が n 組なら、門前の牌は 14 − 3n 枚）


@dataclass(frozen=True)
class Position:
    """コーチに見せる局面（自分から見えている情報だけ）"""

    tiles: tuple[int, ...]                    # 門前の手牌（ツモ牌を含む。副露が n 組なら 14 − 3n 枚）
    visible: tuple[int, ...] = ()             # 門前の手牌以外で見えている牌（河・全員の副露・ドラ表示牌）
    seat_wind: int = EAST
    round_wind: int = EAST
    dora_indicators: tuple[int, ...] = ()
    draws_left: int = 0                       # このあと自分がツモれる回数
    drawn: int | None = None                  # ツモ牌（手牌に含まれる牌ID。鳴いた直後は None）
    can_riichi: bool = False                  # 聴牌したらリーチを宣言できる状況か（門前・未リーチ・ツモが残っている）
    rules: Rules = DEFAULT_RULES
    melds: tuple[Meld, ...] = ()              # 副露（鳴いた面子と暗槓）
    forbidden: tuple[int, ...] = ()           # 切れない種類（鳴いた直後の喰い替え）
    called: bool = False                      # 鳴いた直後（ツモっていないので、あがれない。切るだけ）

    def __post_init__(self) -> None:
        object.__setattr__(self, "tiles", tuple(self.tiles))
        object.__setattr__(self, "visible", tuple(self.visible))
        object.__setattr__(self, "dora_indicators", tuple(self.dora_indicators))
        object.__setattr__(self, "melds", tuple(self.melds))
        object.__setattr__(self, "forbidden", tuple(sorted(set(self.forbidden))))
        if len(self.tiles) + 3 * len(self.melds) != HAND_SIZE:
            raise ValueError(f"打牌の前の手牌は、副露 {len(self.melds)} 組なら {HAND_SIZE - 3 * len(self.melds)} 枚です: {len(self.tiles)} 枚")
        if self.drawn is not None and self.drawn not in self.tiles:
            raise ValueError("ツモ牌が手牌に含まれていません")
        if all(kind_of(t) in self.forbidden for t in self.tiles):
            raise ValueError("切れる牌がありません")

    @property
    def menzen(self) -> bool:
        """門前か（暗槓だけなら門前のまま）"""
        return not any(m.is_open for m in self.melds)

    @property
    def unseen(self) -> int:
        """見えていない牌の枚数"""
        return NUM_TILES - len(self.tiles) - len(self.visible)

    @property
    def dora_kinds(self) -> tuple[int, ...]:
        return tuple(dora_kind_of(kind_of(t)) for t in self.dora_indicators)

    @property
    def value_kinds(self) -> tuple[int, ...]:
        """役牌になる字牌（三元牌・自風・場風）"""
        return (HAKU, HATSU, CHUN, self.seat_wind, self.round_wind)


#: リーチできたのに、宣言せずに聴牌をとったときの補足
MISSED_RIICHI_REASON = "この打牌で聴牌。門前なので、リーチを宣言して切ることもできた（リーチは 1 翻の役）。"


class Grade(StrEnum):
    BEST = "best"            # おすすめと同じ速さ
    NARROWER = "narrower"    # 向聴数は同じだが、受け入れが少ない
    FARTHER = "farther"      # 向聴数が遠ざかる
    DEAD = "dead"            # 有効牌が 1 枚も残っていない形になる
    PASSED = "passed"        # あがれる形だったのに、あがらずに切った
    NO_RIICHI = "no_riichi"  # リーチが要る役を狙う局で、リーチせずに聴牌をとった（役指定練習だけ。engine.target_coach が付ける）


@dataclass(frozen=True)
class Candidate:
    """打牌候補 1 つ（ある種類の牌を切る場合）"""

    option: DiscardOption
    tile: int                # 切るならこの牌（赤でないほうを優先）
    held: int                # 手牌にある枚数
    dora: int                # tile 1 枚に付いているドラの数（ドラ表示牌ぶん＋赤）
    grade: Grade             # おすすめと比べた評価（PASSED・NO_RIICHI は使わない）
    shanten_loss: int        # おすすめより向聴数がいくつ遠いか
    tiles_loss: int          # 向聴数が同じとき、受け入れが何枚少ないか
    is_pick: bool            # おすすめの 1 枚か

    @property
    def kind(self) -> int:
        return self.option.kind

    @property
    def shanten(self) -> int:
        return self.option.shanten

    @property
    def acceptance(self) -> Acceptance:
        return self.option.acceptance

    @property
    def total(self) -> int:
        return self.option.total

    @property
    def kinds(self) -> int:
        return self.option.kinds

    @property
    def is_best(self) -> bool:
        return self.grade is Grade.BEST


@dataclass(frozen=True)
class Analysis:
    position: Position
    shanten: int                              # この手の向聴数（形の上で、いちばん聴牌に近い切り方をしたあと。有効牌が残っているかは見ない）
    info: ShantenInfo                         # 形ごとの向聴数（4 面子 1 雀頭・七対子・国士無双）
    candidates: tuple[Candidate, ...]         # 打牌候補（良い順）
    pick: Candidate                           # おすすめ
    layout: Layout                            # 手牌の分け方（分解図のもと）
    layout_tiles: tuple[tuple[int, ...], ...] # 分け方のまとまりごとの牌ID（layout.parts と同じ順）
    next_chance: float                        # おすすめを切ったあと、次のツモで有効牌を引く確率
    within_chance: float                      # 残りのツモのうちに、1 回以上引く確率
    waits: tuple[Wait, ...]                   # おすすめを切ると聴牌するとき、その待ち（あがったときの結果つき）

    @property
    def can_win(self) -> bool:
        """いま、あがりの形になっているか（鳴いた直後は、形がそろっていても、あがれないので含めない）"""
        return self.shanten == AGARI and not self.position.called

    @property
    def stalled(self) -> bool:
        """形の上ではもっと近い切り方があるが、その有効牌（待ち牌）が 1 枚も残っていないので、おすすめは別の切り方になっているか。

        例：聴牌にとれる形だが、待ち牌がすべて見えている（空聴）。おすすめは、1 向聴に戻して受け入れを広げる切り方になる。
        このとき shanten（形の上の向聴数）より pick.shanten（おすすめを切ったあとの向聴数）が大きい。
        """
        return self.pick.shanten > self.shanten

    @property
    def best(self) -> tuple[Candidate, ...]:
        """おすすめと同じ速さの候補すべて"""
        return tuple(c for c in self.candidates if c.is_best)

    @property
    def layout_matches(self) -> bool:
        """分け方から数えた向聴数が、判定ライブラリの向聴数と同じか（式を見せてよいか）"""
        return self.layout.shanten == self.shanten

    @property
    def last_discard(self) -> bool:
        """これが最後の打牌か（このあとツモが無い。違いは、聴牌で終われるかどうかだけ）"""
        return self.position.draws_left <= 0

    @property
    def can_end_tenpai(self) -> bool:
        """おすすめを切れば、聴牌の形になるか"""
        return self.pick.shanten <= TENPAI

    def candidate(self, kind: int) -> Candidate | None:
        return next((c for c in self.candidates if c.kind == kind), None)


def _grade(option: DiscardOption, pick: DiscardOption) -> Grade:
    if (option.reach, option.total) == (pick.reach, pick.total):
        return Grade.BEST
    if option.total == 0:
        return Grade.DEAD
    if option.shanten > pick.shanten:
        return Grade.FARTHER
    return Grade.NARROWER


def _last_pick(advice: Advice, position: Position, dora_of: dict[int, int]) -> DiscardOption:
    """最後の打牌のおすすめ。聴牌で終われる牌があれば、その中から選ぶ（待ちが残っているかは問わない）"""
    tenpai = [o for o in advice.options if o.shanten <= TENPAI]
    if not tenpai:
        return advice.pick
    return min(tenpai, key=lambda o: loose_rank(o.kind, value_kinds=position.value_kinds, dora=dora_of.get(o.kind, 0)))


def _last_grade(option: DiscardOption, pick: DiscardOption) -> Grade:
    """最後の打牌の評価。聴牌にとれない手は、どれを切っても同じ。とれる手は、聴牌で終われるかどうか"""
    if pick.shanten > TENPAI or option.shanten <= TENPAI:
        return Grade.BEST
    return Grade.FARTHER


def _dora_count(tile: int, position: Position) -> int:
    return position.dora_kinds.count(kind_of(tile)) + (1 if is_red(tile, aka=position.rules.aka_dora) else 0)


@lru_cache(maxsize=512)
def analyze(position: Position) -> Analysis:
    """局面を調べる（同じ局面は覚えておいて、計算をくり返さない）"""
    tiles = position.tiles
    counts = counts34(tiles)
    remaining = remaining_counts(tiles, position.visible)
    # 受け入れが同じ候補の中では、ドラ（赤 5 を含む）を手放さない牌を先に切る
    dora_of = discard_dora(tiles, dora_kinds=position.dora_kinds, aka=position.rules.aka_dora, drawn=position.drawn)
    advice = advise(counts, remaining, value_kinds=position.value_kinds, dora_of=dora_of, skip=position.forbidden)
    last = position.draws_left <= 0          # 最後の打牌：このあとツモが無いので、受け入れの広さは関係ない
    top = _last_pick(advice, position, dora_of) if last else advice.pick

    candidates = []
    for option in advice.options:
        tile = tile_for_discard(tiles, option.kind, aka=position.rules.aka_dora, drawn=position.drawn)
        grade = _last_grade(option, top) if last else _grade(option, top)
        same_shanten = option.shanten == top.shanten
        candidates.append(
            Candidate(
                option=option,
                tile=tile,
                held=counts[option.kind],
                dora=dora_of[option.kind],
                grade=grade,
                shanten_loss=0 if grade is Grade.BEST else max(0, option.shanten - top.shanten),
                tiles_loss=top.total - option.total if same_shanten and not last else 0,
                is_pick=option is top,
            )
        )
    pick = next(c for c in candidates if c.is_pick)

    info = shanten_info(counts)
    layout = best_layout(counts)
    waits: tuple[Wait, ...] = ()
    if pick.shanten == TENPAI:
        hand = tuple(t for t in tiles if t != pick.tile)
        waits = waits_of(
            hand,
            remaining,
            visible=(*position.visible, pick.tile),
            melds=position.melds,
            seat_wind=position.seat_wind,
            round_wind=position.round_wind,
            dora_indicators=position.dora_indicators,
            rules=position.rules,
        )
    return Analysis(
        position=position,
        shanten=info.value,
        info=info,
        candidates=tuple(candidates),
        pick=pick,
        layout=layout,
        layout_tiles=layout.assign(tiles),
        next_chance=draw_chance(pick.total, position.unseen) if position.draws_left > 0 else 0.0,
        within_chance=chance_within(pick.total, position.unseen, position.draws_left),
        waits=waits,
    )


def rebase(analysis: Analysis, kind: int) -> Analysis:
    """おすすめを、ほかの牌（その種類を切る候補）に置きかえた分析。候補の評価（同じ速さ・受け入れが少ない・遠ざかる…）を、
    その牌と比べて付け直す。

    対局のコーチは、速さだけでなく、役（鳴いた手）やあがれるか・安全度でおすすめを選ぶことがある。切った牌の評価を、
    そのおすすめと比べて作るのに使う（judge_discard に渡す）。おすすめより速い候補の評価は、意味を持たない
    （コーチが役などのために避けた牌。対局のコーチは、その牌を切ったときは速さだけの分析で評価する）。
    """
    target = analysis.candidate(kind)
    if target is None:
        raise ValueError(f"切れる牌の種類ではありません: {kind}")
    if target.is_pick:
        return analysis
    top = target.option
    last = analysis.last_discard
    candidates = []
    for candidate in analysis.candidates:
        option = candidate.option
        grade = _last_grade(option, top) if last else _grade(option, top)
        same_shanten = option.shanten == top.shanten
        candidates.append(replace(
            candidate,
            grade=grade,
            shanten_loss=0 if grade is Grade.BEST else max(0, option.shanten - top.shanten),
            tiles_loss=max(0, top.total - option.total) if same_shanten and not last else 0,
            is_pick=option is top,
        ))
    pick = next(c for c in candidates if c.is_pick)
    position = analysis.position
    return replace(
        analysis,
        candidates=tuple(candidates),
        pick=pick,
        next_chance=draw_chance(pick.total, position.unseen) if position.draws_left > 0 else 0.0,
        within_chance=chance_within(pick.total, position.unseen, position.draws_left),
        waits=(),                   # 待ちの表は、速さだけのおすすめのもの。置きかえた分析では使わない
    )


# ---------------------------------------------------------------- 切った牌の評価


@dataclass(frozen=True)
class Verdict:
    chosen: Candidate
    pick: Candidate
    grade: Grade
    riichi: bool                               # リーチを宣言して切ったか
    gained: tuple[tuple[int, int], ...]        # おすすめなら増える有効牌（種類, 残り枚数）
    lost: tuple[tuple[int, int], ...]          # 選んだ牌のほうにだけある有効牌
    broken: Part | None                        # 向聴数が遠ざかったとき、くずしたまとまり
    red_wasted: bool                           # 赤 5 を切ったが、赤でない同じ牌も持っていた
    dora_wasted: bool                          # 同じ速さの候補の中で、ドラのほうを切った
    missed_riichi: bool                        # リーチできたのに、宣言せずに聴牌をとった
    label: str                                 # 評価の短い呼び方（例: いちばん速い打牌、受け入れが 4 枚少ない）
    text: str                                  # ひとことの評価
    reasons: tuple[str, ...]                   # 理由と補足

    @property
    def is_best(self) -> bool:
        return self.grade is Grade.BEST

    @property
    def shanten_loss(self) -> int:
        return self.chosen.shanten_loss

    @property
    def tiles_loss(self) -> int:
        return self.chosen.tiles_loss


def _tile_text(tile: int, rules: Rules) -> str:
    return ("赤" if is_red(tile, aka=rules.aka_dora) else "") + kind_text(kind_of(tile))


def _tiles_text(items: Sequence[tuple[int, int]]) -> str:
    return "・".join(f"{kind_text(kind)}（{count} 枚）" for kind, count in items)


def _width(candidate: Candidate) -> str:
    """受け入れ（聴牌なら待ち）の広さの書き方"""
    return f"{candidate.kinds} 種 {candidate.total} 枚"


def _noun(candidate: Candidate) -> str:
    return "待ち" if candidate.shanten == TENPAI else "受け入れ"


def _sp(text: str) -> str:
    """文の途中に入れる語（数字で始まるときは、前に空白を入れる。例：「おすすめの 1萬切り」）"""
    return f" {text}" if text[0].isdigit() else text


def _stage(shanten: int) -> str:
    """文の途中に入れる向聴数の呼び方"""
    return _sp(shanten_text(shanten))


def judge_discard(analysis: Analysis, tile: int, *, riichi: bool = False) -> Verdict:
    """実際に切った牌（牌ID）を、おすすめと比べる"""
    position = analysis.position
    rules = position.rules
    if tile not in position.tiles:
        raise ValueError(f"手牌にない牌です: {tile}")
    chosen = analysis.candidate(kind_of(tile))
    assert chosen is not None
    pick = analysis.pick
    grade = Grade.PASSED if analysis.can_win else chosen.grade
    name = _tile_text(tile, rules)
    pick_name = _tile_text(pick.tile, rules)
    reasons: list[str] = []

    gained: tuple[tuple[int, int], ...] = ()
    lost: tuple[tuple[int, int], ...] = ()
    broken: Part | None = None

    last = analysis.last_discard
    if grade is Grade.PASSED:
        label = "あがりを見送った"
        text = f"あがりの形だったが、あがらずに{_sp(name)}を切った。"
        reasons.append("あがるときは、牌を切らずに「ツモ」を押す。")
    elif last:
        if not analysis.can_end_tenpai:
            label = "どれを切っても同じ"
            text = "最後の打牌。聴牌にとれない手なので、どれを切っても結果は同じ（ノーテンで流局）。"
        else:
            if grade is Grade.BEST:
                label = "聴牌で流局"
                text = f"最後の打牌。{name}切りで、聴牌したまま流局。"
            else:
                label = "聴牌をくずした"
                text = f"最後の打牌。{name}を切ると、聴牌をくずして流局になる。{pick_name}切りなら、聴牌したまま終われた。"
                broken = analysis.layout.part_with(chosen.kind)
            reasons.append("対局では、流局したときに聴牌していると、聴牌していない人から点をもらえる（ノーテン罰符）。")
    elif grade is Grade.BEST:
        label = "いちばん速い打牌"
        if pick.total == 0:
            text = f"{name}切り。どれを切っても、有効牌は残っていなかった。"
        elif chosen.shanten == TENPAI:
            head = f"{name}を切ってリーチ。" if riichi else f"{name}切りで聴牌。"
            text = f"{head}待ちは {_width(chosen)}で、いちばん広い。"
        elif chosen.is_pick or len(analysis.best) == 1:
            text = f"{name}切りは、いちばん受け入れが広い（{_width(chosen)}）。"
        else:
            label = "おすすめと同じ速さ"
            if chosen.acceptance.live == pick.acceptance.live:
                text = f"{name}切りは、おすすめの{_sp(pick_name)}切りと同じ受け入れ（{_width(chosen)}）。"
            else:       # 有効牌の中身は違うが、残り枚数の合計が同じ
                text = (
                    f"{name}切りの受け入れは {_width(chosen)}。"
                    f"おすすめの{_sp(pick_name)}切り（{_width(pick)}）と、枚数が同じ。"
                )
    elif grade is Grade.DEAD:
        label = "有効牌が残っていない形"
        text = (
            f"{name}を切ると{_stage(chosen.shanten)}の形だが、有効牌がすべて見えていて残り 0 枚（何を引いても進まない）。"
            f"{pick_name}切りなら{_stage(pick.shanten)}で、{_noun(pick)}は {_width(pick)}。"
        )
    elif grade is Grade.FARTHER:
        label = "聴牌をくずした" if pick.shanten == TENPAI else "聴牌から遠ざかった"
        if pick.shanten == TENPAI:
            head = f"{name}を切ると、聴牌をくずして{_stage(chosen.shanten)}に戻る。"
        else:
            head = f"{name}を切ると、{shanten_text(pick.shanten)}から{_stage(chosen.shanten)}に遠ざかる。"
        keep = "聴牌" if pick.shanten == TENPAI else f"{_stage(pick.shanten)}のまま"
        text = f"{head}{pick_name}切りなら{keep}（{_noun(pick)} {_width(pick)}）。"
        broken = analysis.layout.part_with(chosen.kind)
        if broken is not None:
            reasons.append(
                f"{kind_text(chosen.kind)}は「{kinds_text(broken.kinds)}」（{PART_NAMES[broken.type]}）に使っていた牌。"
                "切ると、そのまとまりがくずれる。"
            )
        elif analysis.layout.form is Form.CHIITOI:
            reasons.append(
                "七対子には、種類の違う対子が 7 組いる。同じ牌の 3 枚目・4 枚目は対子に数えられないので、"
                f"{kind_text(chosen.kind)}を切ると、対子にできる牌の種類が足りなくなる。"
            )
    else:
        noun = _noun(chosen)
        label = f"{noun}が {chosen.tiles_loss} 枚少ない"
        text = f"{name}切りの{noun}は {_width(chosen)}。{pick_name}切りなら {_width(pick)}で、{chosen.tiles_loss} 枚多い。"
        mine, theirs = dict(chosen.acceptance.live), dict(pick.acceptance.live)
        gained = tuple((kind, count) for kind, count in pick.acceptance.live if kind not in mine)
        lost = tuple((kind, count) for kind, count in chosen.acceptance.live if kind not in theirs)
        if gained:
            reasons.append(f"{pick_name}切りなら、{_tiles_text(gained)}も有効牌になる。")
        if lost:
            reasons.append(f"{name}切りにだけある有効牌は、{_tiles_text(lost)}。")

    is_red_tile = is_red(tile, aka=rules.aka_dora)
    # 最後の打牌では、手に残すドラはもう点にならない（聴牌で終われるかだけが違い）ので、ドラの注意はしない
    red_wasted = not last and is_red_tile and any(kind_of(t) == chosen.kind and t != tile for t in position.tiles)
    if red_wasted:
        reasons.append(f"赤い 5 はドラ（1 枚で 1 翻）。赤でない{_sp(kind_text(chosen.kind))}を切れば、受け入れは同じままドラを残せた。")

    dora_wasted = False
    if grade is Grade.BEST and not red_wasted and not last:
        mine = _dora_count(tile, position)
        fewer = [c for c in analysis.best if c.dora < mine]
        if fewer:
            dora_wasted = True
            other = pick if pick in fewer else min(fewer, key=lambda c: c.dora)
            less = "ドラでない" if other.dora == 0 else "ドラの少ない"
            same = "待ちの枚数" if chosen.shanten == TENPAI else "受け入れの枚数"
            reasons.append(f"{name}はドラ。{same}が同じなら、{less}{_sp(_tile_text(other.tile, rules))}を先に切ると打点を残せる。")

    missed_riichi = (
        position.can_riichi and chosen.shanten == TENPAI and chosen.total > 0 and not riichi and grade is not Grade.PASSED
    )
    if missed_riichi:
        reasons.append(MISSED_RIICHI_REASON)

    return Verdict(
        chosen=chosen,
        pick=pick,
        grade=grade,
        riichi=riichi,
        gained=gained,
        lost=lost,
        broken=broken,
        red_wasted=red_wasted,
        dora_wasted=dora_wasted,
        missed_riichi=missed_riichi,
        label=label,
        text=text,
        reasons=tuple(reasons),
    )
