"""ツキ補正：配牌とツモの「引きの良さ」を、山の並べ替えだけで上げる。

    配牌の良さ（0〜100）  配牌の候補をいくつか作り、いちばん良いものを採用する
    ツモの良さ（0〜100）  ツモのたびに、ある確率で「欲しい牌」を次のツモ位置に入れ替える

守っていること
  * 山は 136 枚の牌の並び。補正は、まだ誰も見ていない牌どうしの並べ替えだけで行う。
    牌を作り出さないので、同じ牌が 5 枚になることはない。
  * 王牌（嶺上牌・ドラ表示牌・裏ドラ表示牌）と、ほかの席の配牌には触れない。
  * 補正 0 のときは、乱数を 1 回も引かず、山にも触れない。素のシャッフルと完全に同じ山になる。
  * 補正で何が起きたかを記録して返す（画面に出したり、成績と一緒に残したりできるように）。

乱数は山とは別の系統（"luck:…"）を使う。同じシードなら、補正の強さを変えても元の山は変わらない。
"""
from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass

from engine.analysis.shanten import TENPAI, shanten_of
from engine.analysis.ukeire import acceptance, remaining_counts
from engine.rng import Rng
from engine.scoring.dora import dora_kind_of
from engine.tiles import CHUN, HAKU, HATSU, counts34, is_red, is_yaochu_kind, kind_of
from engine.wall import LIVE_END, LIVE_START, Wall

MAX_LEVEL = 100
MAX_CANDIDATES = 256
#: ツモの補正が働く確率。スライダーの値 → 確率（間は直線でつなぐ）。少しの確率でも強く効くので、低い側を細かくしてある
DRAW_CURVE = ((0, 0.0), (25, 0.05), (50, 0.12), (75, 0.25), (100, 0.60))
#: 画面で選べる段階（名前、スライダーの値）
PRESETS = (("なし", 0), ("弱", 25), ("中", 50), ("強", 75), ("最大", 100))


@dataclass(frozen=True)
class LuckSettings:
    deal: int = 0                      # 配牌の良さ（0〜100）
    draw: int = 0                      # ツモの良さ（0〜100）
    allow_tenpai_deal: bool = False    # 配牌で聴牌している候補も採用してよいか

    def __post_init__(self) -> None:
        for name in ("deal", "draw"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX_LEVEL:
                raise ValueError(f"補正の強さは 0〜{MAX_LEVEL} の整数です: {name}={value!r}")

    @property
    def is_off(self) -> bool:
        """補正なし（通常の麻雀）か"""
        return self.deal == 0 and self.draw == 0

    def to_dict(self) -> dict:
        return {"deal": self.deal, "draw": self.draw, "allow_tenpai_deal": self.allow_tenpai_deal}

    @classmethod
    def from_dict(cls, data: dict) -> LuckSettings:
        """保存した形から作る。形や値がおかしければ ValueError"""
        if not isinstance(data, dict):
            raise ValueError("ツキ補正の記録の形が違います")
        allow = data.get("allow_tenpai_deal", False)
        if not isinstance(allow, bool):
            raise ValueError(f"ツキ補正の記録の値がおかしい: allow_tenpai_deal={allow!r}")
        return cls(data.get("deal", 0), data.get("draw", 0), allow)       # 数値は __post_init__ で確かめる


def deal_candidates(level: int) -> int:
    """配牌の候補の数。0 → 1（何もしない）、25 → 4、50 → 16、75 → 64、100 → 256。

    0 でなければ、必ず 2 個以上にする（式のままだと 1〜7 は 1 個に丸まり、補正を入れたのに何も起きなくなる）。
    """
    if level <= 0:
        return 1
    return max(2, round(MAX_CANDIDATES ** (level / MAX_LEVEL)))


def draw_probability(level: int) -> float:
    """ツモの補正が働く確率。0 → 0、25 → 0.05、50 → 0.12、75 → 0.25、100 → 0.60"""
    for (x0, y0), (x1, y1) in zip(DRAW_CURVE, DRAW_CURVE[1:], strict=False):
        if level <= x1:
            return y0 + (y1 - y0) * (level - x0) / (x1 - x0)
    return DRAW_CURVE[-1][1]


# ---------------------------------------------------------------- 配牌


@dataclass(frozen=True)
class DealReport:
    candidates: int           # 比べた候補の数（1 なら補正なし）
    chosen: int               # 採用した候補の番号（0 ＝ 元の配牌）
    original_shanten: int     # 元の配牌の向聴数
    chosen_shanten: int       # 採用した配牌の向聴数

    @property
    def applied(self) -> bool:
        """配牌が元と変わったか"""
        return self.chosen != 0


def hand_prospect(hand: Sequence[int], *, seat_wind: int, round_wind: int, dora_indicators: Sequence[int] = ()) -> int:
    """役と打点の見込みを、ざっくり点数にする（配牌の候補を比べるための目安。厳密な評価ではない）。

        役牌の対子 ＋3、役牌の刻子 ＋6      役が確定しやすい
        ドラ・赤 5 が 1 枚につき ＋2        打点が上がる
        么九牌が 1 枚以下 ＋2               断么九が見える
        1 色＋字牌で 10 枚以上 ＋3          混一色・清一色が見える
        対子が 4 組以上 ＋1                 七対子・対々和が見える
    """
    counts = counts34(hand)
    score = 0
    for kind in {HAKU, HATSU, CHUN, seat_wind, round_wind}:
        if counts[kind] >= 3:
            score += 6
        elif counts[kind] == 2:
            score += 3
    dora_kinds = [dora_kind_of(kind_of(t)) for t in dora_indicators]
    score += 2 * sum(counts[k] for k in dora_kinds)
    score += 2 * sum(1 for t in hand if is_red(t))
    if sum(1 for t in hand if is_yaochu_kind(kind_of(t))) <= 1:
        score += 2
    honors = sum(counts[27:])
    if max(sum(counts[start:start + 9]) for start in (0, 9, 18)) + honors >= 10:
        score += 3
    if sum(1 for n in counts if n >= 2) >= 4:
        score += 1
    return score


def improve_deal(
    wall: Wall,
    order: int,
    settings: LuckSettings,
    seed: int | str,
    *,
    seat_wind: int,
    round_wind: int,
) -> DealReport:
    """配牌を補正する（配る前に 1 度だけ呼ぶ）。

    自分の配牌 13 枚とツモ山 70 枚の計 83 枚を並べ直した候補を作り、
    「向聴数が小さい → 受け入れ枚数＋役の見込みが大きい」の順で、いちばん良い候補を採用する。
    聴牌している候補は採用しない（allow_tenpai_deal で変更できる）。
    """
    original = wall.dealt_hand(order)
    original_shanten = shanten_of(counts34(original))
    count = deal_candidates(settings.deal)
    if count <= 1:
        return DealReport(1, 0, original_shanten, original_shanten)

    positions = [*wall.deal_positions(order), *range(LIVE_START, LIVE_END)]
    pool = [wall.tiles[p] for p in positions]
    rng = Rng(seed, "luck:deal")
    dora_indicators = wall.dora_indicators

    candidates = [pool]
    for _ in range(count - 1):
        shuffled = list(pool)
        rng.shuffle(shuffled)
        candidates.append(shuffled)

    def allowed(value: int) -> bool:
        return settings.allow_tenpai_deal or value > TENPAI

    shantens = [shanten_of(counts34(c[:13])) for c in candidates]
    usable = [i for i, value in enumerate(shantens) if allowed(value)]
    if not usable:                 # どの候補も聴牌していた（まず起きない）。元の配牌のままにする
        return DealReport(count, 0, original_shanten, original_shanten)
    best_shanten = min(shantens[i] for i in usable)

    def quality(index: int) -> int:
        hand = candidates[index][:13]
        effective = acceptance(counts34(hand), remaining_counts(hand, dora_indicators)).total
        return effective + hand_prospect(hand, seat_wind=seat_wind, round_wind=round_wind, dora_indicators=dora_indicators)

    finalists = [i for i in usable if shantens[i] == best_shanten]
    # 向聴数が同じ候補が複数あるときだけ、受け入れと役の見込みで比べる。同点なら番号の小さいほう（元の配牌を優先）
    chosen = finalists[0] if len(finalists) == 1 else max(finalists, key=lambda i: (quality(i), -i))
    if chosen:
        wall.permute(positions, candidates[chosen])
    return DealReport(count, chosen, original_shanten, shantens[chosen])


# ---------------------------------------------------------------- ツモ


@dataclass(frozen=True)
class DrawReport:
    rolled: bool = False            # 補正の抽選に当たったか
    swapped: bool = False           # 山の牌を入れ替えたか
    original: int | None = None     # 入れ替える前に、次のツモ位置にあった牌（入れ替えたときだけ）


NO_DRAW_LUCK = DrawReport()


def improve_draw(
    wall: Wall,
    probability: float,
    wanted: Callable[[], Collection[int]],
    rng: Rng,
) -> DrawReport:
    """次のツモを補正する（ツモる直前に呼ぶ）。

    確率 probability で抽選に当たったとき、次のツモ牌が「欲しい牌」でなければ、
    これからツモる山の中にある欲しい牌 1 枚と入れ替える。欲しい牌が山に残っていなければ何もしない。

    wanted は、欲しい牌の種類を返す関数（抽選に当たったときだけ呼ぶ。計算に少し時間がかかるため）。
    """
    if probability <= 0 or wall.live_remaining <= 0:
        return NO_DRAW_LUCK
    if not rng.chance(probability):
        return NO_DRAW_LUCK
    kinds = set(wanted())
    position = wall.next_live_position
    if not kinds or kind_of(wall.tiles[position]) in kinds:
        return DrawReport(rolled=True)
    sources = [p for p in range(position + 1, wall.live_end) if kind_of(wall.tiles[p]) in kinds]
    if not sources:
        return DrawReport(rolled=True)
    original = wall.tiles[position]
    wall.swap_live(position, rng.choice(sources))
    return DrawReport(rolled=True, swapped=True, original=original)
