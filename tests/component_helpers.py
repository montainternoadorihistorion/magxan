"""画面なしのテスト（AppTest）で、ブラウザの中で動く自前の部品（手牌・選択肢）から値が届いたときと同じように動かす道具。

AppTest は、カスタムコンポーネント v2 の部品を押せない。ブラウザの部品は、確定したときに
「部品の状態（JSON）」と「出来事の一覧（"events"）」を送ってくる。それと同じ値を作って、次の実行に渡す。
Streamlit の内部の仕組み（AppTest._run・出来事の受け口の名前）を使うので、Streamlit の版を上げたら、ここが動くか確かめる。
"""
from __future__ import annotations

import json

from streamlit.components.v2.bidi_component.main import _make_trigger_id
from streamlit.testing.v1 import AppTest


def component(at: AppTest, name: str, key: str | None = None):
    """画面に置かれた、その名前の部品（key を渡したときは、その鍵で置いたもの。渡さなければ最初の 1 つ）"""
    return next(
        c for c in at.get("bidi_component")
        if c.proto.component_name == name and (key is None or c.proto.id.endswith(f"-{key}"))
    )


def component_data(at: AppTest, name: str, key: str | None = None) -> dict:
    """部品に渡した内容"""
    return json.loads(component(at, name, key).proto.json)


def send(at: AppTest, name: str, event: str, value: object, *, key: str | None = None) -> AppTest:
    """部品 name（鍵 key）から、出来事 event（例 "pick"）が値 value つきで届いたとして、ページを 1 回動かす"""
    target = component(at, name, key)
    states = at._tree.get_widget_states()
    base = states.widgets.add()                 # 部品の状態（この部品は使っていないので空）
    base.id = target.proto.id
    base.json_value = "{}"
    trigger = states.widgets.add()              # 出来事の一覧
    trigger.id = _make_trigger_id(target.proto.id, "events")
    trigger.json_trigger_value = json.dumps([{"event": event, "value": value}])
    at._run(states)
    assert not at.exception, [e.value for e in at.exception]
    return at


def pick_tile(at: AppTest, tile: int, *, riichi: bool = False) -> AppTest:
    """手牌の部品で、牌 tile を選んで確定した（リーチして切った）"""
    rev = component_data(at, "mjdojo_tile_hand")["rev"]
    return send(at, "mjdojo_tile_hand", "pick", {"id": tile, "rev": rev, "riichi": riichi})


def press_action(at: AppTest, key: str | None = None) -> AppTest:
    """手牌の部品で、牌を切らずにする操作のボタン（ツモあがり・ロンなど）を押した。key を省くと、最初のボタン"""
    data = component_data(at, "mjdojo_tile_hand")
    keys = [a["key"] for a in data["actions"]]
    assert keys, "操作のボタンが出ていない"
    if key is None:
        key = keys[0]
    assert key in keys, f"{key} のボタンが出ていない（{keys}）"
    return send(at, "mjdojo_tile_hand", "pick", {"action": key, "rev": data["rev"]})


def action_keys(at: AppTest) -> list[str]:
    """手牌の部品に出ている、操作のボタンの名前"""
    return [a["key"] for a in component_data(at, "mjdojo_tile_hand")["actions"]]


def choose(at: AppTest, keys, *, key: str | None = None) -> AppTest:
    """選択肢の部品（鍵 key）で、keys の選択肢を選んで答えた"""
    rev = component_data(at, "mjdojo_choices", key)["rev"]
    return send(at, "mjdojo_choices", "pick", {"rev": rev, "keys": list(keys)}, key=key)
