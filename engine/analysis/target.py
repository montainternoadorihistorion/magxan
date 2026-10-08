"""役までの距離：ある役が付くあがりの形まで、あと何枚か（役指定練習のための計算）。

    plan = target_plan(counts, "sanshoku", seat_wind=SOUTH, round_wind=EAST)
    plan.distance   −1 ＝ その役の形であがっている ／ 0 ＝ あと 1 枚（その役の聴牌）／ n ＝ その聴牌まであと n 枚
    plan.blocks     めざす形（面子と雀頭）。組ごとに、持っている牌と足りない牌
    plan.need       足りない牌（種類, 枚数）
    plan.spare      めざす形に入らない手牌（種類, 枚数）

考え方
    役が付くあがりの形（14 枚）のひとつを T とする。手牌 H と T に共通する牌が多いほど、その形に近い。

        距離 ＝ 13 − （H と T に共通する枚数の、T をいろいろ変えたときの最大値）

    ふつうの向聴数は、T を「あがりの形すべて」から選んだときの値。ここでは、T を「その役の形」に限る。
    だから、距離はいつも向聴数以上になる。

役の形は「必ず使う面子・雀頭」と「残りの面子・雀頭の選び方の制限」で書く（Shape）。
    三色同順   必ず使う：n萬・n筒・n索 から始まる順子（n ＝ 1〜7 の 7 通り）。残りの 1 面子と雀頭は自由
    断么九     必ず使うものは無い。面子と雀頭に使えるのは 2〜8 だけ
    三暗刻     必ず使うものは無い。4 面子のうち 3 つ以上が刻子

ここで見るのは牌の組み合わせだけ。あがり方（ロンかツモか）や、高点法でほかの読み方が選ばれることは見ていない。
実際にその役が付くかどうかは、あがったときの点数計算（engine.scoring）が決める。

平和だけは、待ちの形（両面待ち）が条件に入るので、あがりの形ではなく「平和が付く聴牌の形」（13 枚）で表す。
    平和   順子 3 つ・役牌でない雀頭・両面の 2 枚（23〜78。どちら側が来てもあがりで、平和が付く）
距離の数え方は同じ（13 − 共通する枚数）なので、距離 0 ＝ 平和の聴牌。この形は 13 枚なので、距離が −1 になることはない。
嵌張や辺張の聴牌は、形が 4 面子 1 雀頭に近くても、平和の聴牌とは数えない。
一人練習は鳴きが無いので、門前の手だけを扱う。

一人練習のあがりは、門前のツモだけ。だから、刻子が 4 つそろうと、いつも四暗刻（役満）になる。
役満のときは、ほかの役を数えない。そこで、刻子で作る役は「その役として数えられる形」だけを、役の形とする。
    三色同刻・小三元   残りの面子に、順子を 1 つ以上使う形（刻子 4 つの形は入れない）
    混老頭             七対子の形だけ（4 面子 1 雀頭の形は、必ず刻子 4 つになるので入れない）
対々和が役指定練習に無いのも、同じ理由。鳴きのある対局ができたら、鳴いた形も狙えるようにする。
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

from engine.scoring.decompose import KOKUSHI_KINDS, Form
from engine.tiles import CHUN, EAST, HAKU, HATSU, NORTH, NUM_KINDS

#: 作れない（必要な牌が、もう手に入らない）ことを表す距離
IMPOSSIBLE = 99

ALL = frozenset(range(NUM_KINDS))
NOTHING: frozenset[int] = frozenset()
SUIT_STARTS = (0, 9, 18)
SEQUENCE_STARTS = frozenset(k for k in range(27) if k % 9 <= 6)
SUITED = frozenset(range(27))
HONORS = frozenset(range(27, 34))
WINDS = tuple(range(EAST, NORTH + 1))
DRAGONS = (HAKU, HATSU, CHUN)
TERMINALS = frozenset(k for k in range(27) if k % 9 in (0, 8))
YAOCHU = TERMINALS | HONORS
SIMPLES = frozenset(k for k in range(27) if 1 <= k % 9 <= 7)
GREEN = frozenset({19, 20, 21, 23, 25, HATSU})       # 2・3・4・6・8 索と發
END_SEQUENCES = frozenset(k for k in range(27) if k % 9 in (0, 6))     # 123 と 789
RYANMEN_STARTS = frozenset(k for k in range(27) if 1 <= k % 9 <= 6)   # 23〜78（両側に待てる 2 枚の、小さいほう）


# ---------------------------------------------------------------- 役の形


@dataclass(frozen=True)
class Shape:
    """4 面子 1 雀頭の形で、その役が付く条件"""

    sequences: tuple[int, ...] = ()                 # 必ず使う順子（先頭の牌の種類）
    sets: tuple[int, ...] = ()                      # 必ず使う刻子（牌の種類）
    pair: int | None = None                         # 必ず使う雀頭
    seq_ok: frozenset[int] = SEQUENCE_STARTS        # 残りの面子に使える順子（先頭の牌の種類）
    set_ok: frozenset[int] = ALL                    # 残りの面子に使える刻子
    pair_ok: frozenset[int] = ALL                   # 雀頭に使える牌
    min_sets: int = 0                               # 刻子の数の下限（必ず使うものを含む）
    min_seqs: int = 0                               # 順子の数の下限（必ず使うものを含む）
    ryanmen: int = 0                                # 面子の代わりに使う「両面の 2 枚」の数（聴牌の形を表すとき）
    ryanmen_ok: frozenset[int] = RYANMEN_STARTS     # 両面の 2 枚に使える並び（小さいほうの牌の種類）


@dataclass(frozen=True)
class Spec:
    """役の形のすべて（どれか 1 つを満たせばよい）"""

    shapes: tuple[Shape, ...] = ()
    chiitoi: tuple[frozenset[int], ...] = ()        # 七対子の形でもよい役：対子に使える牌（選び方ごと）
    kokushi: bool = False
    chuuren: bool = False

    @property
    def tenpai_form(self) -> bool:
        """役の形を、あがりの形（14 枚）ではなく、役が付く聴牌の形（13 枚）で表しているか（平和）"""
        return any(shape.ryanmen for shape in self.shapes)


def _suit(start: int) -> frozenset[int]:
    return frozenset(range(start, start + 9))


def _any_hand() -> Spec:
    return Spec((Shape(),), (ALL,), kokushi=True)


@lru_cache(maxsize=256)
def spec_of(key: str, seat_wind: int = EAST, round_wind: int = EAST) -> Spec:
    """役（図鑑のページの鍵）→ その役の形。役指定練習で選べない役は KeyError"""
    if key in ("riichi", "ippatsu", "menzen_tsumo", "double_riichi"):
        return _any_hand()          # 手の形は問わない役。ふつうの向聴数と同じになる
    if key == "tanyao":
        simple_runs = frozenset(k for k in range(27) if 1 <= k % 9 <= 5)
        return Spec((Shape(seq_ok=simple_runs, set_ok=SIMPLES, pair_ok=SIMPLES),), (SIMPLES,))
    if key == "pinfu":            # 聴牌の形で表す：順子 3 つ・役牌でない雀頭・両面の 2 枚（どちら側が来ても平和）
        guests = frozenset(w for w in WINDS if w not in (seat_wind, round_wind))
        return Spec((Shape(set_ok=NOTHING, pair_ok=SUITED | guests, ryanmen=1),))
    if key == "iipeikou":
        return Spec(tuple(Shape(sequences=(a, a)) for a in sorted(SEQUENCE_STARTS)))
    if key == "yakuhai":
        kinds = sorted({*DRAGONS, seat_wind, round_wind})
        return Spec(tuple(Shape(sets=(k,)) for k in kinds))
    if key == "chiitoitsu":
        return Spec(chiitoi=(ALL,))
    if key == "sanankou":
        return Spec((Shape(min_sets=3),))
    if key == "sanshoku":
        return Spec(tuple(Shape(sequences=(n, 9 + n, 18 + n)) for n in range(7)))
    if key == "sanshoku_doukou":     # 4 つめの面子は順子（刻子 4 つは四暗刻になる）
        return Spec(tuple(Shape(sets=(n, 9 + n, 18 + n), min_seqs=1) for n in range(9)))
    if key == "ittsu":
        return Spec(tuple(Shape(sequences=(s, s + 3, s + 6)) for s in SUIT_STARTS))
    if key == "chanta":         # 字牌が無い形（純全帯么九）も含める。上位の役になるだけなので
        return Spec((Shape(seq_ok=END_SEQUENCES, set_ok=YAOCHU, pair_ok=YAOCHU, min_seqs=1),))
    if key == "junchan":
        return Spec((Shape(seq_ok=END_SEQUENCES, set_ok=TERMINALS, pair_ok=TERMINALS, min_seqs=1),))
    if key == "shousangen":          # 残りの 2 面子のどちらかは順子（刻子 4 つは四暗刻になる）
        return Spec(tuple(Shape(sets=tuple(d for d in DRAGONS if d != pair), pair=pair, min_seqs=1) for pair in DRAGONS))
    if key == "honroutou":           # 七対子の形だけ（4 面子 1 雀頭の形は、刻子 4 つ ＝ 四暗刻になる）
        return Spec(chiitoi=(YAOCHU,))
    if key == "ryanpeikou":
        starts = sorted(SEQUENCE_STARTS)
        return Spec(tuple(Shape(sequences=(a, a, b, b)) for i, a in enumerate(starts) for b in starts[i:]))
    if key == "honitsu":        # 字牌が無い形（清一色）も含める
        shapes = []
        pairs = []
        for start in SUIT_STARTS:
            kinds = _suit(start) | HONORS
            shapes.append(Shape(seq_ok=SEQUENCE_STARTS & _suit(start), set_ok=kinds, pair_ok=kinds))
            pairs.append(kinds)
        return Spec(tuple(shapes), tuple(pairs))
    if key == "chinitsu":
        shapes = [Shape(seq_ok=SEQUENCE_STARTS & _suit(s), set_ok=_suit(s), pair_ok=_suit(s)) for s in SUIT_STARTS]
        return Spec(tuple(shapes), tuple(_suit(s) for s in SUIT_STARTS))
    if key == "kokushi":
        return Spec(kokushi=True)
    if key == "suuankou":
        return Spec((Shape(seq_ok=NOTHING),))
    if key == "daisangen":
        return Spec((Shape(sets=DRAGONS),))
    if key == "tsuuiisou":
        return Spec((Shape(seq_ok=NOTHING, set_ok=HONORS, pair_ok=HONORS),), (HONORS,))
    if key == "shousuushii":
        return Spec(tuple(Shape(sets=tuple(w for w in WINDS if w != pair), pair=pair) for pair in WINDS))
    if key == "daisuushii":
        return Spec((Shape(sets=WINDS),))
    if key == "ryuuiisou":
        return Spec((Shape(seq_ok=frozenset({19}), set_ok=GREEN, pair_ok=GREEN),))
    if key == "chinroutou":
        return Spec((Shape(seq_ok=NOTHING, set_ok=TERMINALS, pair_ok=TERMINALS),))
    if key == "chuuren":
        return Spec(chuuren=True)
    raise KeyError(f"役指定練習で選べない役です: {key!r}")


#: 役指定練習で選べる役（図鑑のページの鍵）
TARGET_KEYS = (
    "riichi", "ippatsu", "menzen_tsumo", "tanyao", "pinfu", "iipeikou", "yakuhai", "double_riichi", "chiitoitsu",
    "sanankou", "sanshoku", "sanshoku_doukou", "ittsu", "chanta", "shousangen", "honroutou", "ryanpeikou", "honitsu",
    "junchan", "chinitsu", "kokushi", "suuankou", "daisangen", "tsuuiisou", "shousuushii", "daisuushii", "ryuuiisou",
    "chinroutou", "chuuren",
)
#: 手の形を問わない役（距離は、ふつうの向聴数と同じ）
SHAPELESS_KEYS = frozenset({"riichi", "ippatsu", "menzen_tsumo", "double_riichi"})


# ---------------------------------------------------------------- 数牌 1 色ぶん・字牌ぶんの表

# 表の形：{(順子の数, 刻子の数, 雀頭の数): (手牌と共通する枚数の最大, 選んだ組)}
# 選んだ組は (種類の印, その色の中での位置) の並び。印は q ＝ 順子（先頭の位置）、s ＝ 刻子、p ＝ 雀頭、r ＝ 両面の 2 枚
_Table = dict[tuple[int, int, int], tuple[int, tuple[tuple[str, int], ...]]]
# 両面の 2 枚も数える表：{(順子の数, 刻子の数, 雀頭の数, 両面の数): …}
_RyanTable = dict[tuple[int, int, int, int], tuple[int, tuple[tuple[str, int], ...]]]

# キャッシュの大きさ：1 件 2〜4 KB ほど。サーバーのプロセス全体で共有され、局をまたいで残る。
# 大きくしても当たる割合はほとんど変わらないので、何百局打ってもメモリが 100 MB 前後に収まる大きさにしてある
# （Community Cloud の無料のコンテナは小さい。以前の 20 万件では、1000 局ほどで 1 GB を超えた）。


@lru_cache(maxsize=8192)
def _suit_table(hand: tuple[int, ...], cap: tuple[int, ...], seq_mask: int, set_mask: int, pair_mask: int, free: int, pair: int) -> _Table:
    """数牌 1 色（9 種類）で、面子を free 組まで・雀頭を pair 組まで選ぶときの、いちばん良い選び方。

    hand は手牌の枚数、cap はめざす形が使ってよい枚数（種類ごと）。mask は、その位置で使える組（ビットの並び）。
    小さい数字から順に「この数字から始まる順子をいくつ・刻子・雀頭」を決めていく。
    覚えておくのは、前の数字から続いている順子の数だけでよい（j ＝ 1 つ前から、k ＝ 2 つ前から始まった順子）。
    """
    states: dict[tuple[int, int, int, int, int], tuple[int, tuple[tuple[str, int], ...]]] = {(0, 0, 0, 0, 0): (0, ())}
    for i in range(9):
        have, limit = hand[i], cap[i]
        can_seq = i <= 6 and seq_mask >> i & 1
        can_set = set_mask >> i & 1
        can_pair = pair_mask >> i & 1
        following: dict[tuple[int, int, int, int, int], tuple[int, tuple[tuple[str, int], ...]]] = {}
        for (j, k, q, t, p), (value, blocks) in states.items():
            carried = j + k                      # 前から続いている順子が、この数字を 1 枚ずつ使う
            if carried > limit:
                continue
            room = free - q - t
            for new in range((room if can_seq else 0) + 1):
                if carried + new > limit:
                    break
                for with_set in (0, 1):
                    if with_set and (not can_set or new + 1 > room):
                        continue
                    for with_pair in (0, 1):
                        if with_pair and (not can_pair or p >= pair):
                            continue
                        used = carried + new + 3 * with_set + 2 * with_pair
                        if used > limit:
                            continue
                        key = (new, j, q + new, t + with_set, p + with_pair)
                        total = value + (have if have < used else used)
                        known = following.get(key)
                        if known is None or total > known[0]:
                            chosen = blocks + (("q", i),) * new
                            if with_set:
                                chosen += (("s", i),)
                            if with_pair:
                                chosen += (("p", i),)
                            following[key] = (total, chosen)
        states = following
    table: _Table = {}
    for (_, _, q, t, p), entry in states.items():       # 9 まで来たら、続いている順子は無い
        known = table.get((q, t, p))
        if known is None or entry[0] > known[0]:
            table[(q, t, p)] = entry
    return table


@lru_cache(maxsize=4096)
def _suit_table_ryanmen(
    hand: tuple[int, ...], cap: tuple[int, ...], seq_mask: int, set_mask: int, pair_mask: int, ryan_mask: int,
    free: int, pair: int, ryan: int,
) -> _RyanTable:
    """_suit_table に「両面の 2 枚」（隣り合う 2 枚。両側に待てるもの）を、ryan 組まで加えて選ぶもの。

    平和の聴牌の形（順子 3 つ・雀頭・両面の 2 枚）に使う。両面の 2 枚は、その位置と次の位置の牌を 1 枚ずつ使うので、
    1 つ前の位置から始まった両面（r）も覚えておく。役の形の多くは両面を使わないので、速さのために関数を分けてある。
    """
    states: dict[tuple[int, ...], tuple[int, tuple[tuple[str, int], ...]]] = {(0, 0, 0, 0, 0, 0, 0): (0, ())}
    for i in range(9):
        have, limit = hand[i], cap[i]
        can_seq = i <= 6 and seq_mask >> i & 1
        can_set = set_mask >> i & 1
        can_pair = pair_mask >> i & 1
        can_ryan = i <= 7 and ryan_mask >> i & 1
        following: dict[tuple[int, ...], tuple[int, tuple[tuple[str, int], ...]]] = {}
        for (j, k, r, q, t, p, a), (value, blocks) in states.items():
            carried = j + k + r                  # 前から続いている順子と両面が、この数字を 1 枚ずつ使う
            if carried > limit:
                continue
            room = free - q - t
            for new in range((room if can_seq else 0) + 1):
                if carried + new > limit:
                    break
                for with_set in (0, 1):
                    if with_set and (not can_set or new + 1 > room):
                        continue
                    for with_pair in (0, 1):
                        if with_pair and (not can_pair or p >= pair):
                            continue
                        for with_ryan in (0, 1):
                            if with_ryan and (not can_ryan or a >= ryan):
                                continue
                            used = carried + new + 3 * with_set + 2 * with_pair + with_ryan
                            if used > limit:
                                continue
                            key = (new, j, with_ryan, q + new, t + with_set, p + with_pair, a + with_ryan)
                            total = value + (have if have < used else used)
                            known = following.get(key)
                            if known is None or total > known[0]:
                                chosen = blocks + (("q", i),) * new
                                if with_set:
                                    chosen += (("s", i),)
                                if with_pair:
                                    chosen += (("p", i),)
                                if with_ryan:
                                    chosen += (("r", i),)
                                following[key] = (total, chosen)
        states = following
    table: _RyanTable = {}
    for (_, _, _, q, t, p, a), entry in states.items():
        known = table.get((q, t, p, a))
        if known is None or entry[0] > known[0]:
            table[(q, t, p, a)] = entry
    return table


@lru_cache(maxsize=2048)
def _honor_table(hand: tuple[int, ...], cap: tuple[int, ...], set_mask: int, pair_mask: int, free: int, pair: int) -> _Table:
    """字牌 7 種類で、刻子を free 組まで・雀頭を pair 組まで選ぶときの、いちばん良い選び方"""
    states: _Table = {(0, 0, 0): (0, ())}
    for i in range(7):
        have, limit = hand[i], cap[i]
        following: _Table = dict(states)                 # この字牌を使わない
        for (q, t, p), (value, blocks) in states.items():
            options = []
            if set_mask >> i & 1 and limit >= 3 and t < free:
                options.append(((q, t + 1, p), value + min(have, 3), blocks + (("s", i),)))
            if pair_mask >> i & 1 and limit >= 2 and p < pair:
                options.append(((q, t, p + 1), value + min(have, 2), blocks + (("p", i),)))
            for key, total, chosen in options:
                known = following.get(key)
                if known is None or total > known[0]:
                    following[key] = (total, chosen)
        states = following
    return states


def _mask(kinds: frozenset[int], start: int, size: int) -> int:
    return sum(1 << i for i in range(size) if start + i in kinds)


@lru_cache(maxsize=2048)
def _masks(shape: Shape) -> tuple[tuple[int, int, int], ...]:
    """Shape の制限を、色ごと（萬・筒・索・字牌）のビットの並びにする"""
    groups = [(_mask(shape.seq_ok, s, 9), _mask(shape.set_ok, s, 9), _mask(shape.pair_ok, s, 9)) for s in SUIT_STARTS]
    groups.append((0, _mask(shape.set_ok, 27, 7), _mask(shape.pair_ok, 27, 7)))
    return tuple(groups)


_Blocks = tuple[tuple[str, int, bool], ...]       # （印, 種類, 役の条件として必ず要る組か）


def _regular(counts: tuple[int, ...], limit: tuple[int, ...], shape: Shape) -> tuple[int, _Blocks] | None:
    """4 面子 1 雀頭の形 1 通りについて、手牌と共通する枚数の最大と、そのときの組"""
    required = [0] * NUM_KINDS
    for first in shape.sequences:
        for kind in (first, first + 1, first + 2):
            required[kind] += 1
    for kind in shape.sets:
        required[kind] += 3
    if shape.pair is not None:
        required[shape.pair] += 2
    rest = list(counts)
    cap = list(limit)
    matched = 0
    for kind in range(NUM_KINDS):
        need = required[kind]
        if not need:
            continue
        if need > limit[kind]:
            return None                         # 必ず使う牌が、もう足りない
        same = min(rest[kind], need)
        matched += same
        rest[kind] -= same
        cap[kind] -= need
    fixed: _Blocks = (
        *(("q", first, True) for first in shape.sequences),
        *(("s", kind, True) for kind in shape.sets),
        *((("p", shape.pair, True),) if shape.pair is not None else ()),
    )
    if shape.ryanmen:
        return _regular_ryanmen(rest, cap, shape, matched, fixed)
    free = 4 - len(shape.sequences) - len(shape.sets)
    pair = 0 if shape.pair is not None else 1
    if free == 0 and pair == 0:
        return matched, fixed
    if free == 0:                               # 残りは雀頭だけ
        best = max((k for k in shape.pair_ok if cap[k] >= 2), key=lambda k: (min(rest[k], 2), -k), default=None)
        return None if best is None else (matched + min(rest[best], 2), (*fixed, ("p", best, False)))

    masks = _masks(shape)
    # 選んだ組は、色ごとの「つながり」（前の色までのつながり, 色の始まり, その色の組）で持ち、最後に 1 列にする（途中で長い列を作らない）
    merged: dict[tuple[int, int, int], tuple[int, _Chain]] = {(0, 0, 0): (0, None)}
    for index, start in enumerate((*SUIT_STARTS, 27)):
        seq_mask, set_mask, pair_mask = masks[index]
        if start == 27:
            table = _honor_table(tuple(rest[27:]), tuple(cap[27:]), set_mask, pair_mask, free, pair)
        else:
            table = _suit_table(tuple(rest[start:start + 9]), tuple(cap[start:start + 9]), seq_mask, set_mask, pair_mask, free, pair)
        combined: dict[tuple[int, int, int], tuple[int, _Chain]] = {}
        for (q1, t1, p1), (v1, c1) in merged.items():
            for (q2, t2, p2), (v2, b2) in table.items():
                if q1 + q2 + t1 + t2 > free or p1 + p2 > pair:
                    continue
                key = (q1 + q2, t1 + t2, p1 + p2)
                known = combined.get(key)
                if known is None or v1 + v2 > known[0]:
                    combined[key] = (v1 + v2, (c1, start, b2))
        merged = combined

    best_entry = None
    for (q, t, p), entry in merged.items():
        if q + t != free or p != pair:
            continue
        if len(shape.sets) + t < shape.min_sets or len(shape.sequences) + q < shape.min_seqs:
            continue
        if best_entry is None or entry[0] > best_entry[0]:
            best_entry = entry
    if best_entry is None:
        return None
    return matched + best_entry[0], (*fixed, *_flatten(best_entry[1]))


_Chain = tuple | None       # （前の色までのつながり, 色の始まり, その色の組）


def _flatten(chain: _Chain) -> _Blocks:
    """色ごとのつながりを、組の 1 列にする（萬子 → 筒子 → 索子 → 字牌 の順）"""
    parts = []
    while chain is not None:
        chain, start, blocks = chain
        parts.append(tuple((mark, start + i, False) for mark, i in blocks))
    return tuple(block for part in reversed(parts) for block in part)


def _regular_ryanmen(rest: list[int], cap: list[int], shape: Shape, matched: int, fixed: _Blocks) -> tuple[int, _Blocks] | None:
    """両面の 2 枚を含む聴牌の形（13 枚）1 通りについて、手牌と共通する枚数の最大と、そのときの組"""
    free = 4 - len(shape.sequences) - len(shape.sets) - shape.ryanmen
    pair = 0 if shape.pair is not None else 1
    ryan = shape.ryanmen
    masks = _masks(shape)
    merged: dict[tuple[int, int, int, int], tuple[int, _Chain]] = {(0, 0, 0, 0): (0, None)}
    for index, start in enumerate((*SUIT_STARTS, 27)):
        seq_mask, set_mask, pair_mask = masks[index]
        table: _RyanTable
        if start == 27:                         # 字牌では、両面の 2 枚は作れない
            honors = _honor_table(tuple(rest[27:]), tuple(cap[27:]), set_mask, pair_mask, free, pair)
            table = {(q, t, p, 0): entry for (q, t, p), entry in honors.items()}
        else:
            table = _suit_table_ryanmen(
                tuple(rest[start:start + 9]), tuple(cap[start:start + 9]), seq_mask, set_mask, pair_mask,
                _mask(shape.ryanmen_ok, start, 9), free, pair, ryan,
            )
        combined: dict[tuple[int, int, int, int], tuple[int, _Chain]] = {}
        for (q1, t1, p1, a1), (v1, c1) in merged.items():
            for (q2, t2, p2, a2), (v2, b2) in table.items():
                if q1 + q2 + t1 + t2 > free or p1 + p2 > pair or a1 + a2 > ryan:
                    continue
                key = (q1 + q2, t1 + t2, p1 + p2, a1 + a2)
                known = combined.get(key)
                if known is None or v1 + v2 > known[0]:
                    combined[key] = (v1 + v2, (c1, start, b2))
        merged = combined

    best_entry = None
    for (q, t, p, a), entry in merged.items():
        if q + t != free or p != pair or a != ryan:
            continue
        if len(shape.sets) + t < shape.min_sets or len(shape.sequences) + q < shape.min_seqs:
            continue
        if best_entry is None or entry[0] > best_entry[0]:
            best_entry = entry
    if best_entry is None:
        return None
    return matched + best_entry[0], (*fixed, *_flatten(best_entry[1]))


def _chiitoi(counts: tuple[int, ...], limit: tuple[int, ...], allowed: frozenset[int]) -> tuple[int, _Blocks] | None:
    """七対子の形：使える牌の中から、別々の 7 種類を対子にする"""
    kinds = sorted((k for k in allowed if limit[k] >= 2), key=lambda k: (-min(counts[k], 2), k))
    if len(kinds) < 7:
        return None
    chosen = sorted(kinds[:7])
    return sum(min(counts[k], 2) for k in chosen), tuple(("p", k, False) for k in chosen)


def _kokushi(counts: tuple[int, ...], limit: tuple[int, ...]) -> tuple[int, _Blocks] | None:
    """国士無双：13 種類の么九牌を 1 枚ずつと、そのどれかをもう 1 枚"""
    if any(limit[k] < 1 for k in KOKUSHI_KINDS):
        return None
    doubles = [k for k in KOKUSHI_KINDS if limit[k] >= 2]
    if not doubles:
        return None
    pair = max(doubles, key=lambda k: (min(counts[k], 2), -k))
    matched = sum(min(counts[k], 1) for k in KOKUSHI_KINDS) + (1 if counts[pair] >= 2 else 0)
    blocks = tuple(("p", k, True) if k == pair else ("x", k, True) for k in KOKUSHI_KINDS)
    return matched, blocks


_CHUUREN_BASE = (3, 1, 1, 1, 1, 1, 1, 1, 3)


def _chuuren(counts: tuple[int, ...], limit: tuple[int, ...]) -> tuple[int, _Blocks] | None:
    """九蓮宝燈：1 色の 1112345678999 と、同じ色の 1 枚"""
    best = None
    for start in SUIT_STARTS:
        for extra in range(9):
            shape = list(_CHUUREN_BASE)
            shape[extra] += 1
            if any(shape[i] > limit[start + i] for i in range(9)):
                continue
            matched = sum(min(counts[start + i], shape[i]) for i in range(9))
            if best is None or matched > best[0]:
                blocks = (("s", start, True), *(("x", start + i, True) for i in range(1, 8)), ("s", start + 8, True), ("x", start + extra, False))
                best = (matched, blocks)
    return best


def _upper_bound(counts: tuple[int, ...], limit: tuple[int, ...], shape: Shape, total: int) -> int:
    """その形と手牌が共通する枚数の、上限の見込み（必ず使う組で重なる枚数 ＋ 残りの組に入りうる枚数）。作れない形は −1"""
    required = [0] * NUM_KINDS
    for first in shape.sequences:
        required[first] += 1
        required[first + 1] += 1
        required[first + 2] += 1
    for kind in shape.sets:
        required[kind] += 3
    if shape.pair is not None:
        required[shape.pair] += 2
    matched = 0
    for kind in range(NUM_KINDS):
        need = required[kind]
        if need:
            if need > limit[kind]:
                return -1
            matched += min(counts[kind], need)
    free = 4 - len(shape.sequences) - len(shape.sets) - shape.ryanmen
    room = 3 * free + (0 if shape.pair is not None else 2) + 2 * shape.ryanmen
    return matched + min(total - matched, room)


@lru_cache(maxsize=4096)
def _best(counts: tuple[int, ...], key: str, seat_wind: int, round_wind: int, limit: tuple[int, ...]) -> tuple[int, Form | None, _Blocks]:
    """その役の形のうち、手牌といちばん多く重なるもの →（共通する枚数, 形, 組）"""
    spec = spec_of(key, seat_wind, round_wind)
    found: list[tuple[int, int, Form, _Blocks]] = []        # （共通する枚数, 同点のときの優先順, 形, 組）
    total = sum(counts)
    best_regular = -1
    for shape in spec.shapes:
        # 見込みの無い形は、表を作る前に飛ばす（二盃口は形が 231 通りある）。同点なら先に見つけた形を選ぶので、
        # 「見込み ≦ いまの最大」の形を飛ばしても、結果は変わらない
        if _upper_bound(counts, limit, shape, total) <= best_regular:
            continue
        result = _regular(counts, limit, shape)
        if result is not None:
            found.append((result[0], 2, Form.REGULAR, result[1]))
            best_regular = max(best_regular, result[0])
    for allowed in spec.chiitoi:
        result = _chiitoi(counts, limit, allowed)
        if result is not None:
            found.append((result[0], 1, Form.CHIITOI, result[1]))
    if spec.kokushi:
        result = _kokushi(counts, limit)
        if result is not None:
            found.append((result[0], 0, Form.KOKUSHI, result[1]))
    if spec.chuuren:
        result = _chuuren(counts, limit)
        if result is not None:
            found.append((result[0], 2, Form.REGULAR, result[1]))
    if not found:
        return (-1, None, ())
    matched, _, form, blocks = max(found, key=lambda item: (item[0], item[1]))
    return (matched, form, blocks)


# ---------------------------------------------------------------- 結果


class BlockKind(StrEnum):
    SEQUENCE = "sequence"   # 順子
    SET = "set"             # 刻子
    PAIR = "pair"           # 雀頭（七対子では対子）
    SINGLE = "single"       # 1 枚（国士無双の么九牌、九蓮宝燈の 2〜8 と余りの 1 枚）
    RYANMEN = "ryanmen"     # 両面の 2 枚（平和の聴牌の形の、待ちの部分）


_BLOCK_KINDS = {"q": BlockKind.SEQUENCE, "s": BlockKind.SET, "p": BlockKind.PAIR, "x": BlockKind.SINGLE, "r": BlockKind.RYANMEN}


@dataclass(frozen=True)
class PlanBlock:
    """めざす形の 1 組"""

    kind: BlockKind
    tiles: tuple[int, ...]      # この組に要る牌（種類）
    have: tuple[int, ...]       # そのうち、手牌にある牌
    need: tuple[int, ...]       # 足りない牌
    fixed: bool                 # 役の条件として必ず要る組か（三色同順の 3 つの順子など）

    @property
    def complete(self) -> bool:
        return not self.need


@dataclass(frozen=True)
class Plan:
    key: str
    distance: int                           # −1 ＝ あがり、0 ＝ 聴牌、n ＝ 聴牌まであと n 枚。作れなければ IMPOSSIBLE
    form: Form | None                       # めざす形（作れなければ None）
    blocks: tuple[PlanBlock, ...]
    need: tuple[tuple[int, int], ...]       # 足りない牌（種類, 枚数）
    spare: tuple[tuple[int, int], ...]      # めざす形に入らない手牌（種類, 枚数）
    tenpai_form: bool = False               # めざす形が、あがりの形ではなく、役が付く聴牌の形（13 枚）か（平和）

    @property
    def possible(self) -> bool:
        return self.distance < IMPOSSIBLE

    @property
    def missing(self) -> int:
        """あがりまでに要る牌の枚数（足りない牌の合計。聴牌の形なら、あがり牌の 1 枚を足す）"""
        return sum(count for _, count in self.need) + (1 if self.tenpai_form else 0)


def _block_tiles(mark: str, kind: int) -> tuple[int, ...]:
    if mark == "q":
        return (kind, kind + 1, kind + 2)
    if mark == "s":
        return (kind,) * 3
    if mark == "p":
        return (kind,) * 2
    if mark == "r":
        return (kind, kind + 1)
    return (kind,)


def _limit(counts: Sequence[int], available: Sequence[int] | None) -> tuple[int, ...]:
    """めざす形が使ってよい枚数（種類ごと）。手牌にある枚数＋まだ手に入る枚数（多くても 4）"""
    if available is None:
        return (4,) * NUM_KINDS
    return tuple(min(4, counts[k] + max(0, available[k])) for k in range(NUM_KINDS))


def target_distance(
    counts: Sequence[int], key: str, *, seat_wind: int = EAST, round_wind: int = EAST, available: Sequence[int] | None = None
) -> int:
    """役までの距離（13 枚でも 14 枚でもよい）。

    available は、種類ごとの「まだ手に入る枚数」（手牌は含めない）。省略すると、4 枚から手牌を引いた数。
    見えている牌を引いた数を渡せば、「もう作れない」ことが分かる（そのとき IMPOSSIBLE）。
    """
    counts = tuple(counts)
    matched, form, _ = _best(counts, key, seat_wind, round_wind, _limit(counts, available))
    return IMPOSSIBLE if form is None else 13 - matched


def target_plan(
    counts: Sequence[int], key: str, *, seat_wind: int = EAST, round_wind: int = EAST, available: Sequence[int] | None = None
) -> Plan:
    """役までの距離と、めざす形（どの組がそろっていて、何が足りないか）"""
    counts = tuple(counts)
    matched, form, raw = _best(counts, key, seat_wind, round_wind, _limit(counts, available))
    if form is None:
        return Plan(key, IMPOSSIBLE, None, (), (), ())
    wanted = [0] * NUM_KINDS
    for mark, kind, _ in raw:
        for tile in _block_tiles(mark, kind):
            wanted[tile] += 1
    # 手牌を組に割り当てる。そろう組から先に割り当てる（同じ牌を 2 つの組が欲しがるとき、片方を完成させて見せる）
    pool = list(counts)

    def shortage(item: tuple[str, int, bool]) -> int:
        tiles = _block_tiles(item[0], item[1])
        return sum(max(0, tiles.count(k) - counts[k]) for k in set(tiles))

    blocks = []
    for mark, kind, fixed in sorted(raw, key=lambda item: (shortage(item), item[1], item[0])):
        have, need = [], []
        for tile in _block_tiles(mark, kind):
            if pool[tile] > 0:
                pool[tile] -= 1
                have.append(tile)
            else:
                need.append(tile)
        blocks.append(PlanBlock(_BLOCK_KINDS[mark], _block_tiles(mark, kind), tuple(have), tuple(need), fixed))
    blocks.sort(key=lambda b: (b.tiles[0], b.kind.value))
    need = tuple((k, wanted[k] - counts[k]) for k in range(NUM_KINDS) if wanted[k] > counts[k])
    spare = tuple((k, counts[k] - wanted[k]) for k in range(NUM_KINDS) if counts[k] > wanted[k])
    tenpai_form = any(mark == "r" for mark, _, _ in raw)
    return Plan(key, 13 - matched, form, tuple(blocks), need, spare, tenpai_form)


def is_tenpai_form(key: str, *, seat_wind: int = EAST, round_wind: int = EAST) -> bool:
    """役の形を、役が付く聴牌の形（13 枚）で表しているか（平和）。手の形を問わない役では False"""
    return key not in SHAPELESS_KEYS and spec_of(key, seat_wind, round_wind).tenpai_form


def target_tiles(
    counts: Sequence[int], key: str, *, seat_wind: int = EAST, round_wind: int = EAST, available: Sequence[int] | None = None
) -> tuple[int, ...]:
    """引くと役に近づく牌（種類）。13 枚の手に対して使う。available を渡したときは、手に入る牌だけを返す。

    牌の組み合わせだけを見る。距離 0（聴牌）の手で、どの牌であがると本当にその役が付くかは、
    点数計算で確かめる（engine.target_coach.approach_tiles）。聴牌の形で表す役（平和）は、距離 0 でこれ以上縮まないので、空を返す。
    """
    counts = list(counts)
    base = target_distance(counts, key, seat_wind=seat_wind, round_wind=round_wind, available=available)
    if base >= IMPOSSIBLE or base < 0:
        return ()
    found = []
    left = None if available is None else list(available)
    for kind in range(NUM_KINDS):
        if counts[kind] >= 4 or (left is not None and left[kind] <= 0):
            continue
        counts[kind] += 1
        if left is not None:
            left[kind] -= 1
        if target_distance(counts, key, seat_wind=seat_wind, round_wind=round_wind, available=left) < base:
            found.append(kind)
        counts[kind] -= 1
        if left is not None:
            left[kind] += 1
    return tuple(found)
