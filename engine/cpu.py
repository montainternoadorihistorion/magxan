"""CPU の打ち方（素直な打ち手）と、CPU の手番を進める係。

ふつう
    * 牌効率で切る：切ったあとの向聴数がいちばん小さく、受け入れ（有効牌の残り枚数）がいちばん多い牌。
      同じなら、ドラを残し、使いにくい牌（役牌でない字牌 → 役牌 → 1・9 → 2・8 → 3〜7）から切る
    * 聴牌したら、リーチできればリーチする
    * ほかの人がリーチしていて、自分が聴牌にとれない（1 向聴以上）ときは、オリる：いちばん安全な牌を切る（ベタオリ）
    * ロン・ツモできれば、あがる
    * 九種九牌は、么九牌が 10 種類以下なら流局にする（11 種類以上なら、国士無双を目指して打つ）
    * 鳴き：役牌の対子があれば、その役牌をポンする（役が確定する。ただし、鳴くと向聴数が戻る手では鳴かない）。
      それ以外は、鳴くと向聴数が進み、役が残る
      （断么九：喰いタンありで、手がほぼ 2〜8 だけ。混一色：手がほぼ 1 色と字牌だけ）ときだけ、チー・ポンする。
      鳴いたあとは、その役を残す牌（断么九なら 1・9・字牌、混一色ならほかの色）から切る。
      ほかの人のリーチを受けているとき（宣言牌そのものが出たときも）は鳴かない。大明槓はしない
    * カン：暗槓・加槓は、手が遅くならないときだけする（リーチを受けているときはしない）。
      リーチのあとの暗槓は、できるとき（待ちが変わらないとき）はする
弱い
    * 向聴数だけを見て切る（受け入れの広さとドラは見ない。同じ向聴数になる牌から、でたらめに選ぶ）
    * オリない。聴牌したらリーチ、あがれればあがる（ふつうと同じ）
    * 鳴くのは、役牌の対子でのポンだけ（鳴くと向聴数が戻るときと、リーチを受けているときは鳴かない）。カンは、リーチのあとの暗槓だけ

CPU が見るのは、自分の手牌・全員の河・全員の副露・ドラ表示牌・リーチの宣言だけ。ほかの人の手牌や山の中身は見ない。
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
    ankan,
    apply,
    auto_action,
    discard,
    kakan,
    kuikae_kinds,
    nine,
    nine_kinds,
    pass_,
    riichi,
    ron,
    tsumo,
    waiting_for,
)
from engine.melds import Meld, MeldType
from engine.rng import Rng
from engine.scoring.dora import dora_kind_of
from engine.tiles import CHUN, HAKU, HATSU, counts34, is_red, is_yaochu_kind, kind_of

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
    for kind in sorted({kind_of(t) for t in tiles} - set(hand.forbidden)):       # 鳴いた直後は、喰い替えになる牌を切らない
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
    """ふつうの CPU が切りたい順（牌効率。同じならドラを残し、使いにくい牌から）。
    鳴いた手で、役（断么九・混一色）を残すために切りたい牌があれば、それを先にする"""
    options = _options(hand, seat, count_tiles=True)
    values = _value_kinds(hand, seat)
    player = hand.players[seat]
    unwanted = plan_discards(player.melds, player.tiles, values, kuitan=hand.rules.kuitan)

    def key(option: Option) -> tuple:
        reach = option.reach if option.total >= 0 else option.shanten + 1
        return (option.kind not in unwanted, reach, -option.total, loose_rank(option.kind, value_kinds=values, dora=_dora_of(hand, option)))

    return sorted(options, key=key)


# ---------------------------------------------------------------- 鳴いた手の役（素直な打ち手のための、簡単な見方）


def _suit(kind: int) -> int | None:
    return None if kind >= 27 else kind // 9


def plan_of(melds: tuple[Meld, ...], tiles: tuple[int, ...] | list[int], values: tuple[int, ...], *, kuitan: bool) -> str | None:
    """鳴いた手が狙う役：yakuhai（役牌の刻子・槓子がある）、tanyao（副露がすべて 2〜8）、honitsu（副露が 1 色と字牌だけ）。
    どれでもなければ None。門前の手（暗槓だけを含む）は None（リーチで役が付けられる）"""
    if not any(m.is_open for m in melds):
        return None
    counts = counts34(tiles)
    if any(m.type is not MeldType.CHI and m.first_kind in values for m in melds) or any(counts[k] >= 3 for k in values):
        return "yakuhai"
    meld_kinds = [kind_of(t) for m in melds for t in m.tiles]
    if kuitan and not any(is_yaochu_kind(k) for k in meld_kinds):
        return "tanyao"
    suits = {_suit(k) for k in meld_kinds} - {None}
    if len(suits) <= 1:
        return "honitsu"
    return None


def plan_discards(melds: tuple[Meld, ...], tiles: tuple[int, ...] | list[int], values: tuple[int, ...], *, kuitan: bool) -> frozenset[int]:
    """鳴いた手の役を残すために、先に切りたい牌の種類（断么九なら 1・9・字牌、混一色ならほかの色）"""
    plan = plan_of(melds, tiles, values, kuitan=kuitan)
    kinds = {kind_of(t) for t in tiles}
    if plan == "tanyao":
        return frozenset(k for k in kinds if is_yaochu_kind(k))
    if plan == "honitsu":
        suit = next(iter({_suit(kind_of(t)) for m in melds for t in m.tiles} - {None}), None)
        return frozenset(k for k in kinds if _suit(k) is not None and _suit(k) != suit)
    return frozenset()


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


def _call_choice(hand: HandState, seat: int, level: CpuLevel) -> Action | None:
    """鳴くかどうか（鳴くなら、その返事）。上の説明の決まりどおり"""
    options = [a for a in hand.call_actions(seat) if a.move in (Move.CHI, Move.PON)]
    claim = hand.claim
    # リーチを受けているときは鳴かない（宣言牌そのものも。鳴けばリーチが成立する）
    if not options or claim is None or threats(hand, seat) or hand.players[claim.seat].in_riichi:
        return None
    values = _value_kinds(hand, seat)
    tile = claim.tile
    player = hand.players[seat]
    before = shanten_of(counts34(player.hand))
    if kind_of(tile) in values:
        # 役牌の対子があれば、ポン（役が確定する）。ただし手が遅くなる（七対子の形をくずすなど）なら鳴かない。
        # もう 3 枚あれば役は付いているので、鳴いて門前をくずさない
        held = sum(1 for t in player.hand if kind_of(t) == kind_of(tile))
        pon = next((a for a in options if a.move is Move.PON), None)
        if pon is None or held != 2:
            return None
        rest = list(player.hand)
        for used in pon.tiles:
            rest.remove(used)
        counts = counts34(rest)
        after = None
        for kind in {kind_of(t) for t in rest} - kuikae_kinds(Move.PON, tile, pon.tiles):
            counts[kind] -= 1
            value = shanten_of(counts)
            counts[kind] += 1
            after = value if after is None else min(after, value)
        return pon if after is not None and after <= before else None
    if level is CpuLevel.WEAK:
        return None
    best: tuple[int, int, Action] | None = None
    for action in options:
        rest = list(player.hand)
        for used in action.tiles:
            rest.remove(used)
        meld_type = MeldType.CHI if action.move is Move.CHI else MeldType.PON
        melds = (*player.melds, Meld(meld_type, (*action.tiles, tile), tile))
        plan = plan_of(melds, rest, values, kuitan=hand.rules.kuitan)
        if plan is None:
            continue
        unwanted = plan_discards(melds, rest, values, kuitan=hand.rules.kuitan)
        if len([t for t in rest if kind_of(t) in unwanted]) > 1:
            continue                                                            # 役のために切る牌が 2 枚以上残る：まだ遠い
        forbidden = kuikae_kinds(action.move, tile, action.tiles)
        counts = counts34(rest)
        after = None
        for kind in {kind_of(t) for t in rest} - forbidden:
            counts[kind] -= 1
            value = shanten_of(counts)
            counts[kind] += 1
            if unwanted and kind not in unwanted:
                continue                                                        # 役を残す牌を切る
            after = value if after is None else min(after, value)
        if after is None or after >= before:
            continue
        key = (after, 0 if action.move is Move.PON else 1)
        if best is None or key < best[:2]:
            best = (*key, action)
    return best[2] if best is not None else None


def _kan_choice(hand: HandState, seat: int, level: CpuLevel) -> Action | None:
    """自分の番のカン（暗槓・加槓）。手が遅くならないときだけ。リーチを受けているとき・弱い CPU はしない"""
    if level is CpuLevel.WEAK or threats(hand, seat):
        return None
    player = hand.players[seat]
    counts = counts34(player.tiles)
    now = shanten_of(counts)
    for tile in hand.ankan_tiles(seat):
        kind = kind_of(tile)
        counts[kind] -= 4
        after = shanten_of(counts)
        counts[kind] += 4
        if after <= now:
            return ankan(seat, tile)
    for tile in hand.kakan_tiles(seat):
        kind = kind_of(tile)
        counts[kind] -= 1
        after = shanten_of(counts)
        counts[kind] += 1
        if after <= now:
            return kakan(seat, tile)
    return None


def decide(hand: HandState, seat: int, level: CpuLevel) -> Action:
    """CPU の行動を 1 つ決める（その席が行動を決める番のとき）"""
    if hand.phase is Phase.CLAIM:
        if hand.ron_check(seat).ok:
            return ron(seat)
        return _call_choice(hand, seat, level) or pass_(seat)
    auto = auto_action(hand, seat)
    if auto is not None:
        return auto
    if hand.can_tsumo(seat):
        return tsumo(seat)
    player = hand.players[seat]
    if player.in_riichi:
        # リーチのあとで、暗槓できる（ツモった牌で、待ちが変わらない）：カンする
        kans = hand.ankan_tiles(seat)
        assert player.drawn is not None
        return ankan(seat, kans[0]) if kans else discard(seat, player.drawn)
    if hand.can_nine(seat) and nine_kinds(player.tiles) < KOKUSHI_KINDS:
        return nine(seat)
    kan = _kan_choice(hand, seat, level) if player.drawn is not None else None
    if kan is not None:
        return kan

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
