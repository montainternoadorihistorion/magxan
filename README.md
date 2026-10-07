# ツキ付き麻雀道場（仮称）

自分専用の麻雀学習アプリです。CPU と実戦しながら、役・点数計算・戦術を学びます。
配牌とツモの「引きの良さ」を調整でき、上達に合わせて補正を 0（通常の麻雀）まで下げていきます。

設計の全体は [docs/DESIGN.md](docs/DESIGN.md) にあります。

## いまの状態：Phase 0（土台と実機確認）

麻雀の対局や解説はまだ入っていません。入っているのは次のものです。

- 牌・乱数・山の土台（`engine/`）。Streamlit に依存しない純粋な Python
- 牌をタップして切るための画面部品（7 枚 × 2 段、選ぶ → 確定の 2 段階）
- ブラウザ内保存を使った「続きから再開」の仕組み
- スマホで上の 2 つとサーバーの速さを確かめる「実機チェック」ページ
- 自動テスト（67 件）と、GitHub 上での自動実行の設定

## 手元で動かす

Python 3.11 以上が必要です（Streamlit Community Cloud に合わせるなら 3.12）。

```bash
python -m venv .venv
source .venv/bin/activate          # Windows は .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

ブラウザで `http://localhost:8501` が開きます。

## テスト

```bash
pip install -r requirements-dev.txt
pytest          # 全テスト
ruff check .    # 書き方の検査
```

テストが確かめていること（Phase 0）:

| 対象 | 内容 |
|---|---|
| 牌 | 牌ID の割り当てが判定ライブラリと一致する。文字列からの変換で「5」が赤5にならない、5 枚目の牌を書けない |
| 乱数 | 同じシードから同じ列が出る（値を固定して監視）。並べ替えが偏らない |
| 山 | 2 万局ぶん作っても、必ず 136 枚の牌をちょうど 1 枚ずつ含む。配牌・ツモ山・王牌が重ならない。配牌の平均向聴数が約 3.6 |
| 一人打ち | 牌が増えも減りもしない。シードと切った牌の列から、途中の局面をすべて再現できる |
| エンジン | Streamlit を読み込まない |
| 画面 | 画面なしでページを動かし、保存からの再開・壊れた保存データ・予備の操作方法を確かめる |

ブラウザを実際に動かす通し確認は `tools/e2e_mobile_check.py` にあります（開発用。Playwright が必要）。

## Streamlit Community Cloud に載せる

1. このリポジトリを GitHub に push する。
2. <https://share.streamlit.io> にサインインし、新しいアプリを作る。
   - Repository: このリポジトリ ／ Branch: `main` ／ Main file path: `app.py`
   - Advanced settings で Python のバージョンを **3.12** にする
   - Secrets は今は空のままでよい
3. デプロイが終わったら、アプリの設定の Sharing で公開範囲を決める。
   自分だけで使うなら「Only specific people can view this app」（非公開にできるアプリは 1 つまで）。

画面の文言は変わることがあります。公式の手順は
<https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app> を見てください。

サインインする GitHub アカウントから、このリポジトリが見えている必要があります。

## 実機チェックのやり方（Phase 0 の確認手順）

スマホでアプリの URL を開き、「実機チェックを始める」から次を順に試します。3〜5 分で終わります。

1. **牌を 10 回ほど切る。** 牌をタップして選び、「この牌を切る」を押すか、同じ牌をもう一度タップ。
2. **ページを再読み込みする。** 同じ手牌と河に戻れば合格。
3. **別のアプリに切り替えて 3 分以上待ってから戻る。** 続きから打てれば合格。
4. **「計測する」を押す。** サーバーの計算の速さが出る。
5. 押しやすさ・見やすさ・反応の速さを ◎○△× で選ぶ。
6. **「結果をコピー」を押して、その文章を送る。**

牌タップがうまく動かない場合は、「予備の操作方法（標準の部品）で試す」を入れると、
Streamlit 標準の部品だけで同じ操作ができます。その場合もその旨を結果のメモに書いてください。

## API キーについて（Phase 5 で使います）

AI による解説を入れるのは Phase 5 です。それまでキーは不要で、入れなくても全機能が動く作りにします。

- キーは **Streamlit Community Cloud のアプリ設定の Secrets 欄**に入れます。
- 手元で試すときは `.streamlit/secrets.toml` に書きます。このファイルは `.gitignore` に入れてあります。
- **キーをリポジトリやチャットに貼らないでください。**

## フォルダ構成

```
app.py                  入口（ページの一覧と共通設定）
views/                  各ページ（home.py, device_check.py）
ui/                     画面まわり。Streamlit に依存するコードはここと views/ だけ
  components/           自作の画面部品（HTML/CSS/JS ＋ Python の窓口）
    tile_hand/            手牌をタップして 1 枚選ぶ
    browser_store/        ブラウザ内保存の読み書き
    copy_button/          文章をコピーするボタン
  tile_view.py          牌の画像の場所・表示名
  layout.py             スマホ向けの余白調整
engine/                 麻雀ロジック。純粋な Python（pytest の対象）
  tiles.py              牌の表現（牌ID、名前、文字列との変換）
  rng.py                再現できる乱数
  wall.py               山（136 枚の並びと位置の役割）
  solo.py               一人打ちの最小ループ
static/tiles/           牌画像（PNG）
tools/                  開発用スクリプト（牌画像の作り直し、ブラウザでの通し確認）
tests/                  自動テスト
docs/DESIGN.md          設計書
.streamlit/config.toml  Streamlit の設定
```

## 開発メモ（実際にはまった点）

- **ページのフォルダ名を `pages/` にしない。** `st.navigation` と併用すると、サーバーの起動直後に
  ページの URL を直接開いたとき「Page not found」のダイアログが出る。`views/` なら出ない。
- **画面部品は置くたびに登録する。** モジュールの読み込み時に 1 度だけ登録すると、自動テストで
  「登録されていない」エラーになる（`ui/components/_base.py`）。
- **部品の JavaScript は、Python から届くデータが変わったときだけ呼ばれる。** 行動を処理したら
  必ず `rev` を増やして、部品に「応答があった」ことを伝える。
- **赤5の牌ID は 16・52・88（各色の 5 の 1 枚目）。** mahjong ライブラリの文字列変換をそのまま使うと
  「5」が赤5になるので、手牌を文字で書くときは必ず `engine.tiles.parse_tiles` を通す。
- **mahjong ライブラリの設定オブジェクトは使い回さない。** 前の計算結果のドラ翻数が書き換わる。

## 牌画像の出典

FluffyStuff 氏の [riichi-mahjong-tiles](https://github.com/FluffyStuff/riichi-mahjong-tiles)
（パブリックドメイン、CC0 1.0）をもとに、`tools/build_tiles.py` で作りました。
詳しくは [static/tiles/LICENSE.md](static/tiles/LICENSE.md) を見てください。
