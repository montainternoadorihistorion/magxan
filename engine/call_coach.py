"""鳴きの判断のコーチ：ポン・チー・カン（大明槓）ができるとき、「鳴く」と「鳴かない」を比べる。

    advice = call_advice(hand, seat)          鳴ける牌が出たとき：鳴き方ごとの見込みと、おすすめ
    judge_call(advice, action, number=…)      実際の返事（鳴いた・見送った）を評価する

比べること（仕様の 5 章「鳴きの判断」）
    役      鳴いたあとに役が残るか。門前ならリーチで役が付けられるが、鳴くとリーチはできない（役なしの警告）
    打点    付きそうな役と翻数の目安。鳴くと門前でしか付かない役（立直・平和・一盃口など）は消え、
            喰い下がりの役（混一色・一気通貫など）は 1 翻下がる。ドラは鳴いても変わらない
    速さ    向聴数と受け入れの枚数（鳴くなら、鳴いて 1 枚切ったあと。切る牌は、役を残せる牌を先に選ぶ）

役の見込みの決め方（数え上げで決まる事実から）
    確定        役牌（三元牌・自風・場風）の刻子・槓子がある（副露でも、手の中の 3 枚でも）
    いまの形    いちばん速い形のまま、役が付く（その役の聴牌までの枚数 ＝ 向聴数）
    リーチ      門前なので、聴牌すればリーチで役が付く
    遠回り      役を付けるには、いちばん速い形より 1 枚多く要る
    役なし      2 枚以上の遠回りが要るか、役の形がもう作れない（このままでは、あがれない）

打点の目安（翻）＝ 確定した役 ＋ リーチ（門前のとき 1 翻）＋ いまの形で付く役のうち、いちばん高い役 1 つ ＋ ドラ
    役どうしが同時に付くかまでは見ていない、おおまかな目安。画面にも「目安」として出す。

おすすめ（よく言われる目安。「1 向聴以内」「2 翻」の線は、このアプリが決めたもの。docs/DESIGN.md の 6 章）
    役が見えなくなる鳴きはしない。
    大明槓はすすめない（手は進まず、ほかの人のドラも増える）。
    リーチを受けていて、鳴いても聴牌しないなら鳴かない（手牌が減って、守りにくくなる）。宣言牌そのものを鳴くときも同じ
    （鳴けばリーチが成立する）。
    役牌の対子をポンすると役が確定する。手が遅くならなければ、鳴いてよい（もう 3 枚持っているなら、役は付いているので鳴かない）。
    鳴くと速くなって（向聴数が進む）、役も残るなら、鳴いてよい。
    ただし（役牌のポンでも）門前で 1 向聴以内、鳴くと打点が 2 翻以上下がるなら、鳴かずにリーチを目指すのも有力（見送るをすすめる）。
    それ以外（速くならない・遅くなる・役まで遠回り）は、鳴かない。
鳴いたあとの打牌（open_hand_discard）は、速さが同じか 1 段遅いまでの中で、役を残せる牌を先に選ぶ。
鳴きの判断の表の「鳴いたら ○ 切り」と、鳴いたあとの打牌のおすすめ（engine/game_coach.py）は、同じ関数で決める。
"""
from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

from engine.analysis.advice import discard_dora, loose_rank, tile_for_discard
from engine.analysis.shanten import TENPAI, shanten_of
from engine.analysis.target import IMPOSSIBLE, target_distance
from engine.analysis.ukeire import acceptance, remaining_counts
from engine.content import yaku_page_map
from engine.game import (
    RIICHI_MIN_WALL,
    RIICHI_STICK,
    Action,
    HandState,
    Move,
    Phase,
    kuikae_kinds,
)
from engine.melds import Meld, MeldType
from engine.scoring.dora import dora_kind_of
from engine.scoring.texts import kind_text
from engine.tiles import CHUN, HAKU, HATSU, counts34, is_red, kind_of
from engine.yaku_table import YAKU, YAKUMAN_HAN

#: 門前の手で調べる役
CLOSED_KEYS = ("tanyao", "pinfu", "iipeikou", "chiitoitsu", "sanshoku", "ittsu", "honitsu", "chanta", "chinitsu", "junchan")
#: 鳴いた手で調べる役（役牌は「確定」として別に数える）
OPEN_KEYS = ("tanyao", "toitoi", "honitsu", "ittsu", "sanshoku", "chanta", "chinitsu", "junchan", "shousangen", "honroutou")
#: 役牌でない役の候補に出す数
SHOW_LIMIT = 4
#: 門前で聴牌に近い（この向聴数以内）なら、打点の下がり方も見る
NEAR_TENPAI = 1
#: 鳴くと打点がこれだけ（翻）下がるなら、鳴かずにリーチを目指すのも有力
BIG_DROP = 2


class YakuStatus(StrEnum):
    SECURED = "secured"     # 役牌の刻子・槓子があり、役が確定している
    ON_PATH = "on_path"     # いちばん速い形のまま、役が付く
    RIICHI = "riichi"       # 門前なので、聴牌すればリーチで役が付く
    DETOUR = "detour"       # 役を付けるには、1 枚の遠回りが要る
    NONE = "none"           # 役が見えない（このままでは、あがれない）


STATUS_NAMES = {
    YakuStatus.SECURED: "役が確定",
    YakuStatus.ON_PATH: "役あり",
    YakuStatus.RIICHI: "リーチで役",
    YakuStatus.DETOUR: "役まで遠回り",
    YakuStatus.NONE: "役なし",
}

#: 役の見込みの良さ（小さいほど良い。鳴いたあとに切る牌を選ぶときに使う）
STATUS_RANK = {YakuStatus.SECURED: 0, YakuStatus.ON_PATH: 0, YakuStatus.RIICHI: 1, YakuStatus.DETOUR: 2, YakuStatus.NONE: 3}


@dataclass(frozen=True)
class YakuChance:
    key: str
    name: str
    distance: int       # その役の聴牌までの枚数（0 ＝ その役の聴牌、−1 ＝ その役であがりの形）
    han: int            # 付いたときの翻数（鳴いていれば喰い下がり後。役満は 13 × 倍数）

    @property
    def yakuman(self) -> bool:
        return self.han >= YAKUMAN_HAN


@dataclass(frozen=True)
class Outlook:
    """ある手（門前の牌 13 − 3n 枚と副露）の、役・打点・速さの見込み"""

    shanten: int
    total: int                          # 受け入れ（有効牌の残り枚数）
    kinds: int                          # 受け入れの種類
    menzen: bool
    can_riichi: bool                    # 聴牌すればリーチできる（門前で、点棒とツモ番がある）
    status: YakuStatus
    secured: tuple[YakuChance, ...]     # 確定している役（役牌の刻子・槓子）
    chances: tuple[YakuChance, ...]     # 近い役（いちばん速い形から 1 枚遠回りまで。近い順）
    dora: int                           # ドラの数（ドラ表示牌ぶん＋赤）

    @property
    def han(self) -> int:
        """打点の目安（翻）。確定した役＋リーチ（門前）＋いまの形で付く役のうち最高の 1 つ＋ドラ"""
        best = max((c.han for c in self.chances if c.distance <= self.shanten), default=0)
        return sum(c.han for c in self.secured) + (1 if self.can_riichi else 0) + best + self.dora

    @property
    def path_yaku(self) -> tuple[YakuChance, ...]:
        """いまの形で付く役（確定した役を除く）"""
        return tuple(c for c in self.chances if c.distance <= self.shanten)

    @property
    def nearest(self) -> YakuChance | None:
        return min(self.chances, key=lambda c: (c.distance, -c.han), default=None)


@dataclass(frozen=True)
class CallOption:
    """返事の 1 つ（鳴かない、または、ある鳴き方）の見込み"""

    action: Action | None               # None ＝ 鳴かない（見送る）
    discard: int | None                 # 鳴いたあとに切る牌（チー・ポン。喰い替えで切れない牌は選ばない）
    outlook: Outlook                    # 鳴いて discard を切ったあとの見込み（役を残す切り方を先に選ぶ）
    gains_yakuhai: bool = False         # この鳴きで、役牌の刻子がそろう（役が確定する）
    fastest: int | None = None          # 鳴いたあと、役を考えずにいちばん速く切ったときの向聴数（大明槓は None）
    fastest_status: YakuStatus | None = None   # そのいちばん速い切り方の、役の見込み（遠回り・役が見えない など）

    @property
    def is_call(self) -> bool:
        return self.action is not None


@dataclass(frozen=True)
class CallAdvice:
    seat: int
    tile: int                           # 鳴ける牌
    from_seat: int                      # その牌を切った人
    stay: CallOption                    # 鳴かない
    calls: tuple[CallOption, ...]       # 鳴き方ごと（チーの組み合わせ・ポン・大明槓）
    recommend: Action | None            # おすすめの鳴き方（None ＝ 見送る）
    reason: str                         # おすすめの理由（ひとこと）
    threatened: bool                    # 誰かのリーチを受けている
    short: str = ""                     # おすすめの理由を、ひとことで（手牌の上の案内に。例：役が見えなくなる）

    def option_for(self, action: Action) -> CallOption | None:
        """実際の返事に当たる鳴き方（使った牌の種類で探す）"""
        kinds = sorted(kind_of(t) for t in action.tiles)
        return next(
            (o for o in self.calls if o.action is not None and o.action.move is action.move
             and sorted(kind_of(t) for t in o.action.tiles) == kinds),
            None,
        )

    @property
    def best_call(self) -> CallOption | None:
        """鳴くとしたら、いちばん良い鳴き方"""
        return min(self.calls, key=_option_key, default=None)


def _option_key(option: CallOption) -> tuple:
    outlook = option.outlook
    kan = option.action is not None and option.action.move is Move.KAN
    return (STATUS_RANK[outlook.status], outlook.shanten, -outlook.total, kan, -outlook.han)


# ---------------------------------------------------------------- 役と打点の見込み


def value_kinds(seat_wind: int, round_wind: int) -> tuple[int, ...]:
    """役牌になる字牌（三元牌・自風・場風）"""
    return tuple(sorted({HAKU, HATSU, CHUN, seat_wind, round_wind}))


def _yakuhai_han(kind: int, seat_wind: int, round_wind: int) -> int:
    """役牌の刻子 1 つの翻数（自風と場風が同じ連風牌なら 2 翻）"""
    return (1 if kind in (HAKU, HATSU, CHUN) else 0) + (1 if kind == seat_wind else 0) + (1 if kind == round_wind else 0)


def _name(key: str) -> str:
    page = yaku_page_map().get(key)
    return page.name if page is not None else YAKU[key].name


def _han(key: str, *, menzen: bool) -> int:
    info = YAKU[key]
    return info.han_closed if menzen else info.han_open


@lru_cache(maxsize=4096)
def _chances(
    counts: tuple[int, ...], melds: tuple[Meld, ...], seat_wind: int, round_wind: int, available: tuple[int, ...], kuitan: bool,
) -> tuple[YakuChance, ...]:
    menzen = not any(m.is_open for m in melds)
    keys = CLOSED_KEYS if menzen else OPEN_KEYS
    found = []
    for key in keys:
        if key == "tanyao" and not menzen and not kuitan:
            continue
        distance = target_distance(counts, key, seat_wind=seat_wind, round_wind=round_wind, available=available, melds=melds)
        if distance < IMPOSSIBLE:
            found.append(YakuChance(key, _name(key), distance, _han(key, menzen=menzen)))
    # 役牌の対子（あと 1 枚で刻子）。どの役牌かも名前に入れる（刻子・槓子になっているものは「確定」で数える）
    for kind in value_kinds(seat_wind, round_wind):
        if counts[kind] != 2 or available[kind] < 1:
            continue
        distance = target_distance(counts, f"yakuhai:{kind}", seat_wind=seat_wind, round_wind=round_wind,
                                   available=available, melds=melds)
        if distance < IMPOSSIBLE:
            found.append(YakuChance("yakuhai", f"役牌 {kind_text(kind)}", distance, _yakuhai_han(kind, seat_wind, round_wind)))
    found.sort(key=lambda c: (c.distance, -c.han, c.key))
    return tuple(found)


def outlook_of(
    concealed: Sequence[int],
    melds: Sequence[Meld],
    *,
    hand: HandState,
    seat: int,
    seen: Sequence[int] = (),
) -> Outlook:
    """門前の牌（13 − 3n 枚）と副露から、役・打点・速さの見込みを作る。seen は、見えている牌に足すもの"""
    melds = tuple(melds)
    counts = counts34(concealed)
    own = [*concealed, *(t for m in melds for t in m.tiles)]
    mine = set(own)
    visible = [t for t in (*hand.visible_to(seat), *seen) if t not in mine]
    remaining = remaining_counts(own, visible)
    result = acceptance(counts, remaining)
    seat_wind, round_wind = hand.seat_wind(seat), hand.round_wind
    menzen = not any(m.is_open for m in melds)
    can_riichi = menzen and hand.scores[seat] >= RIICHI_STICK and hand.live_remaining >= RIICHI_MIN_WALL
    secured = []
    for kind in value_kinds(seat_wind, round_wind):
        if counts[kind] >= 3 or any(m.type is not MeldType.CHI and m.first_kind == kind for m in melds):
            secured.append(YakuChance("yakuhai", f"役牌 {kind_text(kind)}", -1, _yakuhai_han(kind, seat_wind, round_wind)))
    chances = _chances(tuple(counts), melds, seat_wind, round_wind, tuple(remaining), hand.rules.kuitan)
    shanten = result.shanten
    near = tuple(c for c in chances if c.distance <= max(shanten, 0) + 1)[:SHOW_LIMIT]
    nearest = min((c.distance for c in chances), default=IMPOSSIBLE)
    if secured:
        status = YakuStatus.SECURED
    elif nearest <= max(shanten, 0):
        status = YakuStatus.ON_PATH
    elif can_riichi:
        status = YakuStatus.RIICHI
    elif nearest == max(shanten, 0) + 1:
        status = YakuStatus.DETOUR
    else:
        status = YakuStatus.NONE
    dora_kinds = [dora_kind_of(kind_of(t)) for t in hand.dora_indicators]
    dora = sum(dora_kinds.count(kind_of(t)) + (1 if is_red(t, aka=hand.rules.aka_dora) else 0) for t in own)
    return Outlook(shanten, result.total, result.kinds, menzen, can_riichi, status, tuple(secured), near, dora)


# ---------------------------------------------------------------- 鳴き方ごとの見込み


def _after_call(hand: HandState, seat: int, action: Action, tile: int) -> tuple[list[int], Meld]:
    player = hand.players[seat]
    rest = list(player.hand)
    for used in action.tiles:
        rest.remove(used)
    meld_type = {Move.CHI: MeldType.CHI, Move.PON: MeldType.PON, Move.KAN: MeldType.MINKAN}[action.move]
    return rest, Meld(meld_type, (*action.tiles, tile), tile)


@dataclass(frozen=True)
class OpenPick:
    """鳴いた手の打牌（役を残せる切り方を先に選ぶ）"""

    tile: int                           # 切る牌
    outlook: Outlook                    # 切ったあとの見込み
    fastest: int                        # 役を考えずに、いちばん速く切ったときの向聴数
    outlooks: dict[int, Outlook]        # 調べた切り方（種類）ごとの見込み
    fastest_status: YakuStatus | None = None    # いちばん速い切り方の、役の見込み（いくつかあれば、いちばん良いもの）


def open_hand_discard(
    tiles: Sequence[int],
    melds: Sequence[Meld],
    *,
    hand: HandState,
    seat: int,
    forbidden: Collection[int] = (),
    drawn: int | None = None,
    extra: Callable[[int], tuple] | None = None,
) -> OpenPick:
    """鳴いた手（14 − 3n 枚）から 1 枚切るなら、どれか。鳴きの判断の表と、鳴いたあとの打牌のおすすめで、同じものを使う。

    まず速さで候補を絞り（向聴数がいちばん小さい切り方と、その次）、その中から、役を残せる牌を選ぶ
    （役が確定 ／ いまの形で付く → 遠回り → 役が見えない の順）。同じなら、速い・受け入れが広い・打点が高い・使いにくい牌から。
    速さは「実質の向聴数」で比べる（有効牌が 1 枚も残っていない形は、1 つ遠いものとして数える。牌効率のコーチと同じ。
    待ち牌がすべて見えている聴牌（空聴）を、有効牌の残る 1 向聴より先にすすめないように）。
    extra は、実質の向聴数の次に比べるもの（種類 → 並べる値。打牌のコーチが、フリテンにならない聴牌を先にするのに使う）。
    """
    melds = tuple(melds)
    counts = counts34(tiles)
    by_kind: dict[int, int] = {}
    for kind in sorted({kind_of(t) for t in tiles} - set(forbidden)):
        counts[kind] -= 1
        by_kind[kind] = shanten_of(counts)
        counts[kind] += 1
    if not by_kind:
        raise ValueError("切れる牌がありません")
    low = min(by_kind.values())
    values = value_kinds(hand.seat_wind(seat), hand.round_wind)
    dora_kinds = [dora_kind_of(kind_of(t)) for t in hand.dora_indicators]
    dora_of = discard_dora(tiles, dora_kinds=dora_kinds, aka=hand.rules.aka_dora, drawn=drawn)
    outlooks: dict[int, Outlook] = {}
    best = None
    for kind in sorted(k for k, v in by_kind.items() if v <= low + 1):
        tile_out = tile_for_discard(tiles, kind, aka=hand.rules.aka_dora, drawn=drawn)
        after = list(tiles)
        after.remove(tile_out)
        outlook = outlook_of(after, melds, hand=hand, seat=seat, seen=(tile_out,))
        outlooks[kind] = outlook
        key = (
            STATUS_RANK[outlook.status], _reach(outlook), *(extra(kind) if extra is not None else ()),
            -outlook.total, -outlook.han, loose_rank(kind, value_kinds=values, dora=dora_of[kind]),
        )
        if best is None or key < best[0]:
            best = (key, tile_out, outlook)
    assert best is not None
    # 役を考えずに、いちばん速く切ったとき（実質の向聴数 → 受け入れの順）の向聴数と、その切り方の役の見込み
    speed = min((_reach(o), -o.total) for o in outlooks.values())
    fast = [o for o in outlooks.values() if (_reach(o), -o.total) == speed]
    fast_status = min((o.status for o in fast), key=lambda status: STATUS_RANK[status])
    return OpenPick(best[1], best[2], fast[0].shanten, outlooks, fast_status)


def _reach(outlook: Outlook) -> int:
    """実質の向聴数（有効牌が 1 枚も残っていない形は、何を引いても進まないので、1 つ遠いものとして数える）"""
    return outlook.shanten + (1 if outlook.total == 0 else 0)


def _call_option(hand: HandState, seat: int, action: Action, tile: int) -> CallOption:
    player = hand.players[seat]
    rest, meld = _after_call(hand, seat, action, tile)
    melds = (*player.melds, meld)
    value = value_kinds(hand.seat_wind(seat), hand.round_wind)
    # 役牌の対子（手の中に 2 枚）をポンすると、役が確定する。もう 3 枚あれば役は付いている（ポン・カンしても、役は増えない）
    held = sum(1 for t in player.hand if kind_of(t) == kind_of(tile))
    gains = action.move is Move.PON and kind_of(tile) in value and held == 2
    if action.move is Move.KAN:
        # 大明槓：嶺上牌をツモってから切る。見込みは、カンしたあとの 13 − 3n 枚で数える
        return CallOption(action, None, outlook_of(rest, melds, hand=hand, seat=seat), gains)
    pick = open_hand_discard(rest, melds, hand=hand, seat=seat, forbidden=kuikae_kinds(action.move, tile, action.tiles))
    return CallOption(action, pick.tile, pick.outlook, gains, pick.fastest, pick.fastest_status)


def call_advice(hand: HandState, seat: int) -> CallAdvice | None:
    """鳴ける牌が出たときの、鳴き方ごとの見込みとおすすめ。鳴けなければ None（ロンだけのときも None）"""
    if hand.phase is not Phase.CLAIM or hand.claim is None:
        return None
    actions = [a for a in hand.call_actions(seat) if a.move in (Move.CHI, Move.PON, Move.KAN)]
    if not actions:
        return None
    player = hand.players[seat]
    tile = hand.claim.tile
    stay = CallOption(None, None, outlook_of(player.hand, player.melds, hand=hand, seat=seat))
    calls = tuple(_call_option(hand, seat, a, tile) for a in actions)
    # リーチを受けている（宣言牌そのものを鳴くときも、鳴けばリーチが成立するので、受けているものとして扱う）
    threatened = any(p.riichi_paid or p.in_riichi for s, p in enumerate(hand.players) if s != seat)
    recommend, reason, short = _recommend(stay, calls, threatened=threatened)
    return CallAdvice(seat, tile, hand.claim.seat, stay, calls, recommend, reason, threatened, short)


def _stage(shanten: int) -> str:
    return "聴牌" if shanten == TENPAI else f"{shanten} 向聴"


def _recommend(stay: CallOption, calls: Sequence[CallOption], *, threatened: bool) -> tuple[Action | None, str, str]:
    """おすすめの鳴き方（None ＝ 見送る）と、その理由（文と、ひとこと）"""
    candidates = [o for o in calls if o.action is not None and o.action.move is not Move.KAN]
    usable = [o for o in candidates if o.outlook.status is not YakuStatus.NONE]
    if not usable:
        if any(o.action is not None and o.action.move is Move.KAN for o in calls) and not candidates:
            return None, (
                "大明槓は、嶺上牌で有効牌を引かない限り手が進まず、ほかの人のドラも増える（門前なら、リーチもできなくなる）。"
                "見送るのがふつう。"
            ), "大明槓は見送るのがふつう"
        return None, (
            "鳴くと役が見えなくなる（役を付けるには 2 枚以上の遠回りが要る。鳴いた手はリーチもできないので、このままではあがれない）。"
        ), "鳴くと役が見えなくなる"
    best = min(usable, key=_option_key)
    after, before = best.outlook, stay.outlook
    if threatened and after.shanten > TENPAI:
        return None, (
            "リーチを受けている。鳴いても聴牌しないので、見送って守りを優先する（鳴くと手牌が減り、安全な牌も減る）。"
        ), "リーチを受けている"
    # 門前の 1 向聴以内で、鳴くと打点の目安が大きく下がる（2 翻以上）なら、門前のままリーチを目指すほうをすすめる（このアプリの目安）
    big_drop = before.menzen and before.shanten <= NEAR_TENPAI and before.han - after.han >= BIG_DROP
    drop_text = f"打点の目安が {before.han} 翻 → {after.han} 翻 と大きく下がる。門前のまま、リーチを目指すのも有力。"
    if best.gains_yakuhai and after.shanten <= before.shanten:
        assert best.action is not None
        name = kind_text(kind_of(best.action.tiles[0]))
        if big_drop:
            return None, f"役牌のポンで役（役牌 {name}）は確定するが、{drop_text}", "打点が大きく下がる"
        return best.action, f"役牌のポンで、役（役牌 {name}）が確定する。手も遅くならない（{_stage(after.shanten)}）。", f"役牌 {name}が確定する"
    if after.shanten < before.shanten and after.status in (YakuStatus.SECURED, YakuStatus.ON_PATH):
        if big_drop:
            return None, f"鳴くと速くなる（{_stage(before.shanten)} → {_stage(after.shanten)}）が、{drop_text}", "打点が大きく下がる"
        names = "・".join(c.name for c in (*after.secured, *after.path_yaku)[:2]) or "役"
        return best.action, (
            f"鳴くと速くなり（{_stage(before.shanten)} → {_stage(after.shanten)}）、役も残る見込み（{names}）。"
        ), "速くなり、役も残る"
    if after.shanten < before.shanten:
        return None, "鳴くと速くなるが、役を付けるには遠回りが要る。見送って、門前で進めるほうが無難。", "役まで遠回り"
    fastest = best.fastest if best.fastest is not None else after.shanten
    if fastest < before.shanten:
        # いちばん速い切り方は、役が見えなくなる（または役まで遠回り）。役を残す切り方では速くならない
        slower = after.shanten > before.shanten
        keep = f"遅くなる（{_stage(before.shanten)} → {_stage(after.shanten)}）" if slower else f"速くならない（{_stage(before.shanten)} のまま）"
        lose = "役が見えなくなり" if best.fastest_status in (None, YakuStatus.NONE) else "役まで遠回りになり"
        return None, (
            f"速さを取る切り方（{_stage(fastest)}）だと{lose}、役を残す切り方では{keep}。"
        ), "役を残すと遅くなる" if slower else "役を残すと速くならない"
    if fastest > before.shanten:
        return None, f"鳴くと遅くなる（{_stage(before.shanten)} → {_stage(fastest)}）。", "鳴くと遅くなる"
    if after.shanten > before.shanten:
        return None, (
            f"鳴いても速くならない（{_stage(before.shanten)} のまま）。役を残す切り方では、{_stage(after.shanten)} に戻る。"
        ), "鳴いても速くならない"
    return None, f"鳴いても速くならない（{_stage(before.shanten)} のまま）。", "鳴いても速くならない"


# ---------------------------------------------------------------- 返事の評価


class CallGrade(StrEnum):
    GOOD = "good"
    SOSO = "soso"
    BAD = "bad"


@dataclass(frozen=True)
class CallDecision:
    """鳴ける牌への返事 1 回ぶんの評価"""

    number: int                         # 自分の何巡目の返事か（その時点で切った枚数 ＋ 1）
    action: Action                      # 実際の返事（見送る・チー・ポン・大明槓）
    advice: CallAdvice
    grade: CallGrade
    label: str                          # 短い評価（例：おすすめどおり、役なしの鳴き）
    text: str                           # ひとことの評価
    ron_missed: bool = False            # ロンできる牌だったのに、ロンせずに鳴いた

    @property
    def called(self) -> bool:
        return self.action.move in (Move.CHI, Move.PON, Move.KAN)

    @property
    def no_yaku(self) -> bool:
        """役なしの鳴き（鳴いたあとの手に役が見えない。卒業の目安に数える）"""
        option = self.advice.option_for(self.action) if self.called else None
        return option is not None and option.outlook.status is YakuStatus.NONE

    @property
    def followed(self) -> bool:
        if self.ron_missed:
            return False                # ロンできたなら、ロンがおすすめ
        recommend = self.advice.recommend
        if recommend is None:
            return not self.called
        option = self.advice.option_for(self.action) if self.called else None
        return option is not None and option.action == recommend


def call_name(action: Action) -> str:
    """鳴き方の短い呼び方（例：ポン、チー 3萬4萬、カン）"""
    if action.move is Move.CHI:
        return "チー " + "".join(kind_text(k) for k in sorted(kind_of(t) for t in action.tiles))
    return {Move.PON: "ポン", Move.KAN: "カン（大明槓）", Move.PASS: "見送り"}.get(action.move, action.move.value)


def judge_call(advice: CallAdvice, action: Action, *, number: int, could_ron: bool = False) -> CallDecision:
    """鳴ける牌への返事（見送る・鳴く）を評価する。could_ron は、その牌でロンもできたか"""
    called = action.move in (Move.CHI, Move.PON, Move.KAN)
    recommend = advice.recommend
    if called and could_ron:
        return CallDecision(number, action, advice, CallGrade.BAD, "ロンできた",
                            "この牌でロンしてあがれた。ふつうは、鳴くより、あがるほうがよい（「ロン」を押す）。", ron_missed=True)
    if called:
        option = advice.option_for(action)
        if option is not None and option.outlook.status is YakuStatus.NONE:
            return CallDecision(number, action, advice, CallGrade.BAD, "役なしの鳴き",
                                "鳴いたあとの手に役が見えない。鳴いた手はリーチもできないので、このままではロンもツモもできない。")
        if recommend is not None and option is not None and option.action == recommend:
            return CallDecision(number, action, advice, CallGrade.GOOD, "おすすめどおり", advice.reason)
        if recommend is None:
            return CallDecision(number, action, advice, CallGrade.SOSO, "見送るのがおすすめだった", advice.reason)
        return CallDecision(number, action, advice, CallGrade.SOSO, "別の鳴き方がおすすめだった",
                            f"おすすめは「{call_name(recommend)}」。{advice.reason}")
    if recommend is None:
        return CallDecision(number, action, advice, CallGrade.GOOD, "見送ってよい", advice.reason)
    return CallDecision(number, action, advice, CallGrade.SOSO, "鳴くのも有力だった", f"「{call_name(recommend)}」もおすすめだった。{advice.reason}")
