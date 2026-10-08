"""CPU の打ち方（素直な打ち手）と、CPU の手番を進める係。

ふつう
    * 牌効率で切る：切ったあとの向聴数がいちばん小さく、受け入れ（有効牌の残り枚数）がいちばん多い牌。
      同じなら、ドラを残し、使いにくい牌（役牌でない字牌 → 役牌 → 1・9 → 2・8 → 3〜7）から切る
    * 聴牌したら、リーチできればリーチする
    * ほかの人がリーチしていて、自分が聴牌にとれない（1 向聴以上）ときは、オリる：いちばん安全な牌を切る（ベタオリ）
    * ロン・ツモできれば、あがる
    * 九種九牌は、么九牌が 10 種類以下なら流局にする（11 種類以上なら、国士無双を目指して打つ）
弱い
    * 向聴数だけを見て切る（受け入れの広さとドラは見ない。同じ向聴数になる牌から、でたらめに選ぶ）
    * オリない。聴牌したらリーチ、あがれればあがる（ふつうと同じ）

CPU が見るのは、自分の手牌・全員の河・ドラ表示牌・リーチの宣言だけ。ほかの人の手牌や山の中身は見ない。
でたらめに選ぶところも、乱数は（局の山のシード, 席, 何番目の行動か）で決まるので、同じ対局は同じように進む。
"""
from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from engine.analysis.advice import loose_rank, tile_for_discard
from engine.analysis.shanten import TENPAI, shanten_of
from engine.analysis.ukeire import acceptance, remaining_counts
from engine.defense import danger_table, threats
from engine.game import (
    HUMAN,
    NUM_PLAYERS,
    Action,
    CpuLevel,
    GameState,
    HandState,
    Move,
    Phase,
    apply,
    auto_action,
    discard,
    nine,
    nine_kinds,
    pass_,
    riichi,
    ron,
    tsumo,
    waiting_for,
)
from engine.rng import Rng
from engine.scoring.dora import dora_kind_of
from engine.tiles import CHUN, HAKU, HATSU, counts34, is_red, kind_of

#: 九種九牌のとき、么九牌がこの種類数以上なら、流局にせず国士無双を目指す
KOKUSHI_KINDS = 11


@dataclass(frozen=True)
class Option:
    """切る候補 1 つ（ある種類を切る場合）"""

    kind: int
    shanten: int        # 切ったあとの向聴数
    total: int          # 切ったあとの受け入れ（有効牌の残り枚数）。弱い CPU は数えない（−1）
    tile: int           # 実際に切る牌（赤 5 は残す）

    @property
    def reach(self) -> int:
        """有効牌が 1 枚も残っていない形は、向聴数が 1 つ大きいものとして比べる（engine.analysis.ukeire と同じ）"""
        return self.shanten + (1 if self.total == 0 else 0)


def _options(hand: HandState, seat: int, *, count_tiles: bool) -> list[Option]:
    player = hand.players[seat]
    tiles = player.tiles
    counts = counts34(tiles)
    remaining = remaining_counts(tiles, hand.visible_to(seat))
    aka = hand.rules.aka_dora
    found = []
    for kind in sorted({kind_of(t) for t in tiles}):
        counts[kind] -= 1
        found.append((kind, shanten_of(counts)))
        counts[kind] += 1
    options = [Option(kind, shanten, -1, tile_for_discard(tiles, kind, aka=aka, drawn=player.drawn)) for kind, shanten in found]
    if not count_tiles:
        return options
    # 受け入れを数えるのは、いちばん良い向聴数の候補だけ（どれも有効牌が残っていなければ、その次の向聴数まで）
    best = min(o.shanten for o in options)
    for limit in (best, best + 1):
        counted = []
        for option in options:
            if option.total < 0 and option.shanten <= limit:
                counts[option.kind] -= 1
                total = acceptance(counts, remaining).total
                counts[option.kind] += 1
                option = Option(option.kind, option.shanten, total, option.tile)
            counted.append(option)
        options = counted
        if any(o.total > 0 for o in options):
            break
    return options


def _value_kinds(hand: HandState, seat: int) -> tuple[int, ...]:
    return (HAKU, HATSU, CHUN, hand.seat_wind(seat), hand.round_wind)


def _dora_of(hand: HandState, option: Option) -> int:
    """その牌を切るときに手放すドラの数"""
    dora_kinds = [dora_kind_of(kind_of(t)) for t in hand.dora_indicators]
    return dora_kinds.count(option.kind) + (1 if is_red(option.tile, aka=hand.rules.aka_dora) else 0)


def efficient_order(hand: HandState, seat: int) -> list[Option]:
    """ふつうの CPU が切りたい順（牌効率。同じならドラを残し、使いにくい牌から）"""
    options = _options(hand, seat, count_tiles=True)
    values = _value_kinds(hand, seat)

    def key(option: Option) -> tuple:
        reach = option.reach if option.total >= 0 else option.shanten + 1
        return (reach, -option.total, loose_rank(option.kind, value_kinds=values, dora=_dora_of(hand, option)))

    return sorted(options, key=key)


def _fold_choice(hand: HandState, seat: int, order: list[Option]) -> Option:
    """ベタオリ：いちばん安全な牌。同じ安全度なら、牌効率で切りたい順"""
    player = hand.players[seat]
    found = threats(hand, seat)
    table = danger_table(player.tiles, hand.visible_to(seat), found, dora_indicators=hand.dora_indicators)
    level = {row.kind: row.level for row in table}
    rank = {option.kind: index for index, option in enumerate(order)}
    return min(order, key=lambda option: (level[option.kind], rank[option.kind]))


def _rng(hand: HandState, seat: int) -> Rng:
    return Rng(hand.seed, f"cpu:{seat}:{len(hand.actions)}")


def decide(hand: HandState, seat: int, level: CpuLevel) -> Action:
    """CPU の行動を 1 つ決める（その席が行動を決める番のとき）"""
    if hand.phase is Phase.CLAIM:
        return ron(seat) if hand.ron_check(seat).ok else pass_(seat)
    auto = auto_action(hand, seat)
    if auto is not None:
        return auto
    if hand.can_tsumo(seat):
        return tsumo(seat)
    player = hand.players[seat]
    if hand.can_nine(seat) and nine_kinds(player.tiles) < KOKUSHI_KINDS:
        return nine(seat)

    if level is CpuLevel.WEAK:
        options = _options(hand, seat, count_tiles=False)
        best = min(o.shanten for o in options)
        choice = _rng(hand, seat).choice([o for o in options if o.shanten == best])
    else:
        order = efficient_order(hand, seat)
        choice = order[0]
        # ほかの人のリーチを受けていて、聴牌にとれないなら、オリる
        if choice.shanten > TENPAI and threats(hand, seat):
            choice = _fold_choice(hand, seat, order)
    if choice.shanten == TENPAI and choice.tile in hand.riichi_tiles(seat):
        return riichi(seat, choice.tile)
    return discard(seat, choice.tile)


# ---------------------------------------------------------------- 手番を進める


def advance(game: GameState, *, cpu_seats: Collection[int] = (1, 2, 3), levels: dict[int, CpuLevel] | None = None) -> GameState:
    """CPU の行動と、自分の決まった行動（リーチのあとのツモ切り）を進める。

    自分（cpu_seats に入っていない席）が行動を決める番になるか、局が終わったら止まる。
    リーチのあとにあがり牌を引いたときも止まる（「ツモ」は、自分で押して宣言する。卓で自分で言うのと同じ）。
    levels で、席ごとに CPU の強さを変えられる（計測用。ふだんは設定の強さ）。
    """
    while not game.finished and game.current.result is None:
        hand = game.current
        seat = waiting_for(hand)
        assert seat is not None
        if seat in cpu_seats:
            level = (levels or {}).get(seat, game.config.cpu_level)
            action = decide(hand, seat, level)
        else:
            auto = auto_action(hand, seat)
            if auto is None or auto.move is Move.TSUMO:
                break
            action = auto
        game = apply(game, action)
    return game


def human_turn(game: GameState) -> bool:
    """自分が行動を決める番か"""
    if game.finished or game.current.result is not None:
        return False
    return waiting_for(game.current) == HUMAN


def all_cpu() -> tuple[int, ...]:
    """4 人とも CPU（計測と、ドリルの局面づくりに使う）"""
    return tuple(range(NUM_PLAYERS))
