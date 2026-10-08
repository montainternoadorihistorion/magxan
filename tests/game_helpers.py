"""対局のテストで、決まった局面を作るための道具。

    hand = build_hand(["123m456p789s1122z", ...4 人ぶん], turn=0, drawn="3z", next_draws="5m6m")

手牌・河・ツモ牌を文字（mpsz 表記）で書くと、それに合う山を作って HandState を返す。
山は「使った牌（配牌・ツモった牌）→ これからツモる牌 → 残り」の順に並べ、王牌（ドラ表示牌など）も指定できる。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from engine.game import (
    NUM_PLAYERS,
    START_POINTS,
    Discard,
    GameConfig,
    GameState,
    HandStart,
    HandState,
    Phase,
    Player,
)
from engine.luck import DealReport
from engine.rules import DEFAULT_RULES, Rules
from engine.tiles import parse_tiles, sort_tiles
from engine.wall import DORA_START, LIVE_END, LIVE_START, NUM_LIVE, URA_START

NO_DEAL = DealReport(1, 0, 0, 0)


def build_hand(
    hands: Sequence[str],
    *,
    turn: int = 0,
    drawn: str | None = None,
    rivers: Sequence[str] = ("", "", "", ""),
    riichi: Sequence[int | None] = (None, None, None, None),
    next_draws: str = "",
    dora: str = "",
    ura: str = "",
    live_drawn: int | None = None,
    dealer: int = 0,
    rotation: int = 0,
    honba: int = 0,
    kyotaku: int = 0,
    scores: Sequence[int] = (START_POINTS,) * NUM_PLAYERS,
    rules: Rules = DEFAULT_RULES,
    number: int = 0,
) -> HandState:
    """決まった局面（DRAW の局面。turn の人が drawn をツモったところ）を作る。

    riichi は、席ごとに「リーチ宣言牌が河の何枚目か」（成立しているものとして、リーチ棒は払い済みにする）。
    live_drawn を指定しなければ、河とツモ牌の枚数から、ツモ山から引いた枚数を決める。
    """
    used: set[int] = set()

    def take(text: str) -> list[int]:
        tiles = parse_tiles(text, used=used)
        used.update(tiles)
        return tiles

    dora_tiles = take(dora) if dora else []
    ura_tiles = take(ura) if ura else []
    hand_tiles = [take(text) for text in hands]
    drawn_tile = take(drawn)[0] if drawn else None
    river_tiles = [take(text) for text in rivers]
    upcoming = take(next_draws) if next_draws else []
    consumed = sum(len(r) for r in river_tiles) + (1 if drawn_tile is not None else 0)
    if live_drawn is None:
        live_drawn = consumed
    rest = [t for t in range(136) if t not in used]
    # 配牌と、すでにツモった牌の位置（0 〜 52 ＋ live_drawn）には、手牌・河・ツモ牌（足りなければ残りの牌）を入れる
    placed = [t for tiles in hand_tiles for t in tiles] + [t for r in river_tiles for t in r] + ([drawn_tile] if drawn_tile is not None else [])
    head = LIVE_START + live_drawn
    if len(placed) > head:
        raise ValueError("手牌と河が、配牌とツモった牌の数より多い")
    filler = rest[: head - len(placed)]
    rest = rest[head - len(placed):]
    if head + len(upcoming) > LIVE_END:
        raise ValueError("これからツモる牌が、ツモ山に入りきらない")
    wall = [*placed, *filler, *upcoming]
    live_rest = LIVE_END - len(wall)
    wall += rest[:live_rest]
    rest = rest[live_rest:]
    dead = rest
    # 王牌：嶺上牌 4 枚 → ドラ表示牌 5 枚 → 裏ドラ表示牌 5 枚
    tail = dead[:4]
    dead = dead[4:]
    dora_block = (dora_tiles + dead)[:5]
    dead = [t for t in dead if t not in dora_block]
    ura_block = (ura_tiles + dead)[:5]
    wall += tail + dora_block + ura_block
    assert len(wall) == 136 and sorted(wall) == list(range(136)), "山の作り方がおかしい"
    assert wall[DORA_START] == (dora_tiles[0] if dora_tiles else wall[DORA_START])
    assert not ura_tiles or wall[URA_START] == ura_tiles[0]
    assert live_drawn <= NUM_LIVE

    # 河の牌の順番（局の何枚目の打牌か）：親から順に 1 枚ずつ切ったものとして数える
    orders: dict[tuple[int, int], int] = {}
    count = 0
    for index in range(max((len(r) for r in river_tiles), default=0)):
        for step in range(NUM_PLAYERS):
            seat = (dealer + step) % NUM_PLAYERS
            if index < len(river_tiles[seat]):
                orders[(seat, index)] = count
                count += 1
    players = []
    for seat in range(NUM_PLAYERS):
        river = tuple(
            Discard(t, riichi=riichi[seat] == index, order=orders[(seat, index)]) for index, t in enumerate(river_tiles[seat])
        )
        paid = riichi[seat] is not None
        players.append(
            Player(
                hand=tuple(sort_tiles(hand_tiles[seat])),
                drawn=drawn_tile if seat == turn else None,
                river=river,
                riichi_at=riichi[seat],
                riichi_paid=paid,
            )
        )
    start = HandStart(number=number, rotation=rotation, dealer=dealer, honba=honba, kyotaku=kyotaku, scores=tuple(scores))
    return HandState(
        start=start,
        seed=f"test:{number}",
        rules=rules,
        actions=(),
        wall_tiles=tuple(wall),
        live_drawn=live_drawn,
        players=tuple(players),  # type: ignore[arg-type]
        turn=turn,
        phase=Phase.DRAW,
        scores=tuple(scores),  # type: ignore[arg-type]
        kyotaku=kyotaku,
        deals=(NO_DEAL,) * NUM_PLAYERS,
    )


def game_of(hand: HandState, *, first_dealer: int = 0, config: GameConfig | None = None, earlier: Sequence[HandState] = ()) -> GameState:
    """局面 1 つから、試合の状態を作る"""
    config = config or GameConfig(seed=1, rules=hand.rules)
    return GameState(config=config, first_dealer=first_dealer, hands=(*earlier, hand))


def with_players(hand: HandState, **changes: Player) -> HandState:
    """席（p0〜p3）の Player を差し替える"""
    players = list(hand.players)
    for name, player in changes.items():
        players[int(name[1:])] = player
    return replace(hand, players=tuple(players))
