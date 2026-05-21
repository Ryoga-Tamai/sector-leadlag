# sector-leadlag

日米業種リードラグ投資ツール — **個人用クオンツ・パイプライン**。
中川他 (2025) 「部分空間正則化付き主成分分析を用いた日米業種リードラグ投資戦略」を、毎営業日朝に自動でシグナル化し LINE 通知するための実運用パイプラインです。

> ⚠️ **本リポジトリは個人の投資判断補助のみを目的とした自家利用ツールであり、投資助言・投資勧誘・収益保証のいずれも行いません。** 全ての投資判断および結果責任は利用者本人に帰属します。詳細は [免責事項](#免責事項) を参照してください。

---

## 概要

米国市場クローズ後（東京 06:00 JST）に GitHub Actions が自動起動し、

1. 米国 9 銘柄＋日本 17 銘柄の固定ユニバース（**26 銘柄**）の調整後 OHLC を yfinance から取得
2. 共通営業日インターセクション上で **部分空間正則化付き PCA** を計算（L=60, K=3, λ=0.9）
3. 米国当日 CC リターンから日本翌日シグナルを復元し、上位 5 銘柄ロング・下位 5 銘柄ショートに振り分け
4. 想定運用額（既定 500 万円）から発注ロット数を逆算
5. LINE Messaging API で個人に通知
6. シグナル履歴を `data/signals/*.csv` と GitHub Pages 用 `docs/data.json` に保存

を一気通貫で実行します。証券会社 API は使用せず、発注は手動。

戦略仕様の根拠は [requirements_v3.md](./requirements_v3.md)、開発手順は [sections_v3.md](./sections_v3.md) を参照。

---

## ユニバース（26 銘柄固定）

**米国側（情報源）**: Select Sector SPDR ETF 9 銘柄
`XLB, XLE, XLF, XLI, XLK, XLP, XLU, XLV, XLY`
（XLC・XLRE は 2010 年以前の履歴が無いため除外。詳細は requirements_v3.md §0 C2）

**日本側（投資対象）**: NEXT FUNDS TOPIX-17 業種別 ETF 17 銘柄
`1617.T 〜 1633.T`

ユニバース定数とラベルは [`src/universe.py`](./src/universe.py) に集約しています。

---

## 論文との相違点

`notebooks/01_paper_replication.ipynb` のファイル名は「paper_replication」となっていますが、本リポジトリの実装は**論文の完全再現ではなく、論文をベースとした再構成**です。以下の点で論文と意図的にズレています。比較・引用の際はご注意ください。

### 1. ユニバースが論文と異なる（米国 11 → 9、合計 28 → 26）

論文は米国側 11 銘柄（Select Sector SPDR ETF のフルセット）＋日本側 17 銘柄＝**28 銘柄**を採用していますが、本実装は **XLC（Communication Services、2018 年上場）** と **XLRE（Real Estate、2015 年上場）** を除外した米国 9 銘柄＋日本 17 銘柄＝**26 銘柄**を採用しています。

- **除外理由**: 論文は事前相関行列 `C_full` を 2010–2014 の 5 年間で推定しますが、XLC（2018 年上場）・XLRE（2015 年上場）はこの期間の履歴が無く、文字通りには再現不可能です。固定ユニバースに絞ることで `C_full` 期間と評価期間を論文に合わせ、銘柄入替起因のバグを恒久的に排除しています（requirements_v3.md §0 C2）。
- **副作用**: リードラグ情報源から **不動産（Real Estate）** と **通信サービス（Communication Services）** の 2 セクターが欠落します。日本側の不動産（1633.T）・情報通信（1626.T）への波及効果は、米国側に対応セクター ETF が無いため部分空間 V₀ ではなく残差成分に押し込まれます。
- 将来的に動的ユニバース（ウィンドウ単位で XLC・XLRE を取り込む）への拡張余地は残しています（requirements_v3.md §6.3）。

### 2. バックテスト R/R が論文値と一致せず上回る

論文 Table 2 と本実装の PCA_SUB（部分空間正則化 PCA）の数値比較（notebook SECTION 2E より）:

| 指標 | 論文 (PCA_SUB) | 本実装 (PCA_SUB) |
|---|---|---|
| AR（年率リターン） | 23.79% | 約 27.89% |
| RISK（年率ボラ） | 10.70% | 約 10.51% |
| **R/R** | **2.22** | **約 2.65** |

R/R が論文値を上回っていますが、**完全一致は原理的に期待していません**（requirements_v3.md §4.3）。主な差異要因:

- ユニバース差（米国 9 vs 11、上記項目 1）
- データ期間・データソース差（本実装は yfinance、評価期間も論文と完全一致しない）
- 年率化係数の解釈差（下記項目 4）

本実装の合否はこの R/R 一致ではなく、**IC・分位スプレッド・ルックアヘッド監査**（notebook SECTION 2D）で判定しています（requirements_v3.md §4.1）。R/R 値は参考値として扱ってください。

### 3. MDD に 2 つの定義があり、論文比較には複利版を使う

notebook SECTION 2E では、最大ドローダウン（MDD）を 2 通りで計算しています。

- **MDD_compound（複利版）**: 論文式(30) 準拠。Wₜ = ∏(1 + Rτ) を作りピーク比下落率の最大値。
- **MDD_simple（単純和版）**: notebook 既存流儀。累積和ベースで peak − cum の最大値。

論文の MDD 9.58%（PCA_SUB）と比較する場合は **MDD_compound を使ってください**。MDD_simple は控除前 P/L の単純累積に近い直感的指標ですが、論文式と定義が異なります。

### 4. 年率化係数は 252（論文式(27)(28)の「12」は月次テンプレートの名残）

論文の式(27)(28) には年率化係数として「12」が記載されていますが、論文本体は**日次戦略**であり、本文中の AR=23.79% も日次平均×252 で整合します。したがって式中の「12」は月次戦略用テンプレートの名残（誤植）と判断し、本実装では **252 を採用**しています（requirements_v3.md §0 C5、§3.5）。

---

## セットアップ

### 1. Python 3.11 環境を用意

macOS 標準の Python 3.9 は LibreSSL の関係で yfinance 接続が不安定なため、Homebrew 等で **Python 3.11** を導入してください。

```bash
brew install python@3.11
```

### 2. リポジトリ取得と venv 作成

```bash
git clone https://github.com/Ryoga-Tamai/sector-leadlag.git
cd sector-leadlag
python3.11 -m venv venv
source venv/bin/activate
python --version    # Python 3.11.x であること
```

### 3. 依存パッケージのインストール

```bash
pip install -r requirements.txt
```

### 4. 環境変数を設定

`.env.example` をコピーして `.env` を作成し、各キーを埋めます（`.env` は `.gitignore` 対象）。

```bash
cp .env.example .env
```

| キー | 用途 | 取得方法 |
|---|---|---|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Messaging API の長期チャネルアクセストークン | [LINE Developers Console](https://developers.line.biz/console/) → 自分のプロバイダー → Messaging API チャネル → `Messaging API設定` → `チャネルアクセストークン（長期）` |
| `LINE_USER_ID` | 通知を受け取るユーザー ID（`U` で始まる 33 文字） | LINE Developers Console → `チャネル基本設定` → `あなたのユーザーID` |
| `CAPITAL_JPY` | 想定運用額（JPY、整数）。未設定時は 5,000,000 が既定 | 任意 |

### 5. 事前相関行列の準備

`data/prior/C_full.npy` はリポジトリに同梱されています（2010-2014 の 26 銘柄共通営業日で算出済み）。再計算する場合は `notebooks/01_paper_replication.ipynb` のセル 10 を実行してください。

---

## 実行方法

### ローカル単発実行

```bash
source venv/bin/activate
python -m src.main
```

`src/main.py` は以下の流れで動きます（詳細は [src/main.py](./src/main.py) docstring 参照）。

```
[DATA]    fetch_prices: 過去 180 営業日 + バッファのキャッシュ更新
[PRIOR]   load_prior_correlation → build_prior_subspace → build_target_correlation
[SIGNAL]  generate_signal: 直近共通営業日のシグナル生成（上位5/下位5）
[LOTS]    fetch_latest_prices → calculate_lots: 想定運用額からロット数を確定
[LINE]    format_signal_message → send_line_message
[SAVE]    data/signals/{YYYY-MM-DD}.csv と docs/data.json を出力
[DONE]    完了
```

各ステップで例外が出ると `send_error_notification` で LINE にスタックトレースを通知してから再 raise します（GitHub Actions ジョブも失敗扱い）。

### テスト

```bash
# オフラインのみ（CI で常時実行する想定）
pytest -m "not network"

# 全件（yfinance / LINE 等の実通信を含む）
pytest
```

SECTION 7 までで合計 92 テスト（オフライン）＋ 5 テスト（network マーカー）。

### スモークテスト用補助スクリプト

| スクリプト | 用途 |
|---|---|
| `scripts/check_signal.py` | 任意日付の単発シグナル生成（LINE には送らない）。`--target-date`、`--lookback-days` を指定可能 |
| `scripts/test_line_send.py` | LINE 送信テスト。`--with-signal` で実シグナル全パイプライン通知 |

---

## ファイル構成

要件定義書 v3 §6.2 準拠（実装済みの範囲のみ列挙）。

```
sector-leadlag/
├── .github/workflows/          # SECTION 9 で daily-signal.yml を追加予定
├── src/
│   ├── __init__.py
│   ├── universe.py             # 26 銘柄定数、業種ラベル、マスク
│   ├── returns.py              # CC / OC リターン計算
│   ├── data_loader.py          # yfinance 取得 + 共通営業日インターセクション
│   ├── pca_engine.py           # 部分空間正則化付き PCA（V0, C0, C_reg, 固有分解）
│   ├── signal_generator.py     # 単日シグナル生成（SECTION 2C と bit-identical）
│   ├── lot_calculator.py       # 想定運用額 → ロット数換算
│   ├── line_notifier.py        # LINE Messaging API 直叩き
│   └── main.py                 # 毎朝のオーケストレータ（SECTION 7）
├── tests/                      # pytest（92 オフライン + 5 network）
├── scripts/
│   ├── check_signal.py
│   └── test_line_send.py
├── notebooks/
│   └── 01_paper_replication.ipynb   # 論文再現バックテスト + 検証レイヤー
├── data/
│   ├── signals/                # 毎日のシグナル CSV（`YYYY-MM-DD.csv`）
│   ├── prior/C_full.npy        # 2010-2014 事前相関行列（26×26）
│   └── cache_prices.csv        # yfinance キャッシュ（コミット非対象推奨）
├── docs/                       # GitHub Pages 用（SECTION 10 で拡張予定）
│   └── data.json               # ダッシュボード用最新シグナル + 履歴
├── requirements.txt
├── requirements_v3.md          # 戦略・データ・検証仕様
├── sections_v3.md              # 開発手順書
├── HANDOFF.md                  # セッション間引き継ぎノート
├── .env.example
├── .gitignore
└── README.md
```

---

## シグナル出力フォーマット

### `data/signals/{YYYY-MM-DD}.csv`

| 列 | 型 | 説明 |
|---|---|---|
| `date` | str (YYYY-MM-DD) | シグナル生成日（t） |
| `ticker` | str | 日本 17 銘柄のティッカー（`1617.T` 〜 `1633.T`） |
| `score` | float | シグナルスコア（高いほど翌日 OC リターンが大きい予測） |
| `rank` | int | スコア降順ランク（1〜17） |
| `position` | str | `long` / `short` / `neutral` |
| `suggested_lots` | int | `position` が long/short の場合の推奨ロット数（単元 = 10 株） |

### `docs/data.json`

```json
{
  "last_updated": "ISO 8601 timestamp (JST)",
  "current_signal": {
    "date": "YYYY-MM-DD",
    "long_basket":  ["1618.T", ...],
    "short_basket": ["1633.T", ...],
    "factor_scores": [PC1, PC2, PC3],
    "all_scores":    { "1617.T": float, ... }
  },
  "history": [
    { "date": "YYYY-MM-DD", "long": [...], "short": [...] },
    ...   /* 直近 100 営業日 */
  ]
}
```

---

## 開発進捗（v3）

| SECTION | 内容 | 状態 |
|---|---|---|
| 0, 1 | プロジェクト初期化、PCA エンジン | ✅ |
| 1.5 | Python 3.11 化、`universe.py` 切り出し | ✅ |
| 2 | 論文再現バックテスト + 検証レイヤー（IC・分位スプレッド・ルックアヘッド監査） | ✅ |
| 3 | データローダー本番化（`data_loader.py`、`returns.py`） | ✅ |
| 4 | シグナル生成モジュール（バックテストと bit-identical） | ✅ |
| 5 | ロット計算 | ✅ |
| 6 | LINE 通知 | ✅ |
| 7 | メインスクリプト統合（`src/main.py`） | ✅ |
| 8 | リモート確認・README 更新 | ✅ |
| 9 | GitHub Actions ワークフロー | ⏳ |
| 10 | GitHub Pages ダッシュボード | ⏳ |
| 11 | 動作確認と微調整 | ⏳ |

---

## 既知の制約

- **データソース**: yfinance は非公式ラッパーで、稀に欠損・遅延が発生します。本格運用時は J-Quants Light（月 ¥1,650）への切替を検討。
- **ユニバース**: 米国側 9 銘柄に限定したため、論文（11 銘柄）の数値とは完全一致しません（想定内・文書化済み、requirements_v3.md §4.3）。
- **取引コスト**: 論文の AR は理論値。実運用では手数料・スプレッド・貸株料・税金で減衰します。
- **モデル劣化**: 戦略の有効性は将来も保証されません。継続モニタリング前提。

---

## ライセンス

[MIT License](./LICENSE)

---

## 免責事項

本ツールは作者個人の投資判断補助のみを目的とした自家利用ツールです。
**第三者への投資助言、投資勧誘、収益保証、運用代行のいずれも提供しません。**

- 本ツールが出力するシグナル・ロット数等を利用したことによる損益は、利用者本人が全責任を負います
- 戦略の論文準拠性は最善を尽くしていますが、データソース・実装の差異から論文値と完全に一致するとは限りません
- 個人投資家による自己責任での投資判断補助としてのみ使用してください
- 本ツールを第三者向けに提供・配布する場合、金融商品取引法上の投資助言業（要登録）に該当する可能性があります

利用者は自らの責任において、関連法令を遵守してください。
