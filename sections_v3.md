# 開発手順書 v3 — SECTION 1.5 以降

**対象モデル**: Claude Sonnet 4.6（Claude Code）
**プロジェクト**: 日米業種リードラグ投資ツール
**関連文書**: 要件定義書 v3.0
**前提**: SECTION 0–1 はコミット済み。GitHub リポジトリは既存

---

## このドキュメントの使い方

各セクションのプロンプトを **上から順番に** Claude Code に渡す。各セクション完了時に：

1. 「動作確認」を必ず実施
2. 問題なければ Git でコミット
3. 次のセクションへ進む

**1 セクションで不具合が出たら、そのセクション内で完結させて修正してから次へ進む。** 複数セクションをまたいで修正しようとすると原因の特定が困難になる。

---

## 開発フロー（v3 更新版）

```
SECTION 1.5  環境再整備（Python 3.11 化・universe.py 切出し）   ← 新規・約30分
   ↓
SECTION 2    論文再現バックテスト + 検証レイヤー                  ← 再定義・最大の山場
   ↓  （2A データ取得 → 2B リターン定義 → 2C バックテストループ
   ↓    → 2D 検証レイヤー → 2E パフォーマンス評価）
SECTION 3    データローダー実装（universe.py / returns.py を本番化）
   ↓
SECTION 4    シグナル生成ロジック
   ↓
SECTION 5    ロット計算機能
   ↓
SECTION 6    LINE 通知実装
   ↓
SECTION 7    メインスクリプト統合
   ↓
SECTION 8    リモート確認・README 更新（リポジトリは既存）
   ↓
SECTION 9    GitHub Actions ワークフロー
   ↓
SECTION 10   GitHub Pages ダッシュボード
   ↓
SECTION 11   動作確認と微調整
```

---

# SECTION 1.5: 環境再整備

**目的**: 開発環境を Python 3.11 に統一し、ユニバース定数を独立モジュールに切り出して、SECTION 2 以降の土台を安定させる。

**前提作業（あなたが手動でやること）**:

1. Homebrew で Python 3.11 を導入（未導入の場合）
   ```bash
   brew install python@3.11
   ```
2. 既存 venv を作り直す
   ```bash
   cd "/Users/tamairyoga/Desktop/MacBook Pro/システム開発/sector-leadlag"
   deactivate 2>/dev/null
   rm -rf venv
   python3.11 -m venv venv
   source venv/bin/activate
   python --version   # Python 3.11.x と表示されることを確認
   ```

**プロンプト**:

```
開発環境を Python 3.11 に統一し、ユニバース定数を独立モジュールに切り出します。

## タスク 1: requirements.txt の監査と修正

現在の src/ 以下のコードを確認し、実際に import されているライブラリを洗い出してください。
その上で requirements.txt を以下の方針で更新：

- 実際に使われているライブラリのみ記載する
- numpy>=1.26, scipy>=1.11, pandas>=2.1, yfinance>=0.2.40, requests>=2.31,
  python-dotenv>=1.0, matplotlib>=3.8, pytest>=7.4 をベースとする
- scikit-learn は、src/ で実際に import されている場合のみ scikit-learn>=1.3 を追加。
  PCA エンジンが numpy/scipy の固有値分解だけで実装されているなら requirements に含めない
- Notebook 実行用に jupyter を追加

更新後、requirements.txt の各行について「なぜ必要か」を1行コメントで添えた一覧を提示してください。

## タスク 2: src/universe.py の新設

ユニバース定数とラベルを独立モジュールに切り出してください。
要件定義書 v3 の §2.1 に従い、26 銘柄固定ユニバースとします。

src/universe.py に以下を定義：

US_TICKERS = ['XLB', 'XLE', 'XLF', 'XLI', 'XLK', 'XLP', 'XLU', 'XLV', 'XLY']  # 9銘柄、XLC・XLREは除外
JP_TICKERS = ['1617.T', '1618.T', '1619.T', '1620.T', '1621.T', '1622.T', '1623.T',
              '1624.T', '1625.T', '1626.T', '1627.T', '1628.T', '1629.T', '1630.T',
              '1631.T', '1632.T', '1633.T']  # 17銘柄
ALL_TICKERS = US_TICKERS + JP_TICKERS  # 26銘柄

US_CYCLICAL  = ['XLB', 'XLE', 'XLF']
US_DEFENSIVE = ['XLK', 'XLP', 'XLU', 'XLV']
JP_CYCLICAL  = ['1618.T', '1625.T', '1629.T', '1631.T']
JP_DEFENSIVE = ['1617.T', '1621.T', '1627.T', '1630.T']

# 業種名（日本語、通知・ダッシュボード用）
JP_SECTOR_NAMES = {'1617.T': '食品', '1618.T': 'エネルギー資源', ...（17銘柄すべて）}
US_SECTOR_NAMES = {'XLB': 'Materials', ...（9銘柄すべて）}

さらに get_universe_masks() 関数を実装：
- 戻り値: 辞書 {'us_cyclical': np.ndarray(bool, shape=(9,)), 'us_defensive': ...,
                'jp_cyclical': np.ndarray(bool, shape=(17,)), 'jp_defensive': ...}
- US_TICKERS / JP_TICKERS の順序に合わせた bool 配列を返す

## タスク 3: SECTION 1 コードの v3 適合確認

src/pca_engine.py を確認し、以下を報告してください（コード変更が必要なら最小限の修正も）：
- build_prior_subspace が n_us=9, n_jp=17 で正しく動作するか
- 26 銘柄前提で各関数の shape が破綻しないか
- ハードコードされた "11" や "28" が無いか（あれば universe.py 参照に修正）

## タスク 4: テストの再実行

修正後、既存テストがすべて green になることを確認するコマンドを提示してください。

実装後、私が実行する確認手順をターミナルコマンドで提示してください。
```

**動作確認**:
```bash
pip install -r requirements.txt
python -c "import numpy, scipy, pandas, yfinance; print('OK')"
python -c "from src.universe import ALL_TICKERS, get_universe_masks; print(len(ALL_TICKERS)); print(get_universe_masks())"
pytest tests/ -v -m "not network"
```
- 26 と表示され、マスクの shape が正しいこと
- 既存テストがすべて green であること

**Git コミット**:
```bash
git add requirements.txt src/universe.py src/pca_engine.py tests/
git commit -m "Section 1.5: Migrate to Python 3.11, extract universe module (26-ticker)"
git push
```

---

# SECTION 2: 論文再現バックテスト + 検証レイヤー（再定義・最大の山場）

**目的**: 実装した PCA エンジンが予測力のあるシグナルを生成できているかを、論文の数値一致ではなく **検証レイヤー（IC・分位スプレッド・ルックアヘッド監査）** で確認する。

**重要**: ここで検証レイヤーが不合格なら、絶対に SECTION 3 以降に進まない。詳細は要件定義書 v3 §4。

このセクションは 1 つの Notebook（`notebooks/01_paper_replication.ipynb`）に、サブステップ 2A〜2E をセル群として実装する。**プロンプトはサブステップごとに分けて Claude Code に渡す**こと（1 プロンプトで全部作らせない）。

---

## SECTION 2A: データ取得（共通営業日インターセクション）

**プロンプト**:

```
notebooks/01_paper_replication.ipynb を新規作成し、データ取得部分を実装します。
要件定義書 v3 の §3（データ仕様）に厳密に従ってください。

### セル1 (Markdown): タイトルと目的
「論文再現バックテスト + 検証レイヤー」「26銘柄固定ユニバースで実装」
「合否は論文の R/R 一致ではなく IC・分位スプレッド・ルックアヘッド監査で判定する」と明記。

### セル2: インポートと設定
numpy, pandas, yfinance, matplotlib, scipy.stats(spearmanr), datetime をインポート。
sys.path.append('..') して src.universe, src.pca_engine から必要な関数をインポート。

### セル3: ユニバース確認
src.universe から ALL_TICKERS, US_TICKERS, JP_TICKERS, get_universe_masks を読み込み、
26銘柄であることと各マスクを print。

### セル4: データ取得（auto_adjust=True、Open と Close 両方）
- yfinance.download で ALL_TICKERS を取得。期間 2010-01-01 〜 2025-12-31
- 必ず auto_adjust=True を指定（配当・分割調整済みの OHLC を得る）
- Open と Close の両方を保持する（OC リターン計算に必要）
- 取得後 data/cache_prices.csv にキャッシュ。再実行時はキャッシュから読む
  （Open と Close の両方をキャッシュできる形式にすること。MultiIndex CSV または
   open_/close_ プレフィックス付きの2つの DataFrame など、方法は任せる）
- yfinance 取得失敗時は最大3回、指数バックオフでリトライ

### セル5: 共通営業日インターセクション
- 全26銘柄の Close がすべて非欠損である日付のみを残す
- Open も同じ日付集合に揃える
- 【必須】処理後に「採用期間：YYYY-MM-DD 〜 YYYY-MM-DD、共通営業日数：N」を print
- 連続3営業日以上の欠損が元データにあれば警告を print

### セル6 (Markdown): データ取得結果の確認
採用期間と営業日数を見て、想定（2010〜2025の大部分）と大きくズレていないかをコメント。

実装後、私がセル1〜6を順に実行する手順を提示してください。
```

**動作確認**: セル 6 まで実行し、採用期間が概ね 2010〜2025 をカバーしていることを確認（XLC・XLRE を除外したので大きく短縮されないはず。もし 2018 年以降に短縮されていたら、26 銘柄以外が混入していないか確認）。

---

## SECTION 2B: リターン定義（CC / OC）

**プロンプト**:

```
01_paper_replication.ipynb に、リターン計算のセルを追加します。
要件定義書 v3 §2.4 のリターン定義に厳密に従ってください。

### セル7: Close-to-Close リターン（PCA推定用）
- 共通営業日の調整後 Close から CC リターンを計算
  r_cc[i,t] = Close[i,t] / Close[i,t-1] - 1
- 全26銘柄分。最初の行は NaN
- shape を print

### セル8: Open-to-Close リターン（戦略評価用、日本側）
- 共通営業日の調整後 Open と Close から OC リターンを計算
  r_oc[j,t] = Close[j,t] / Open[j,t] - 1
- 日本17銘柄分（米国側は不要）
- 同一営業日内なので NaN は出ないはず。shape を print
- 【注意】v2 で使っていた「日本側 CC リターンで近似」は使わない。必ず OC を使う

### セル9 (Markdown): リターン定義の確認
CC は配当・分割調整後の終値ベース、OC は同一日の調整後始値→終値であること、
OC は戦略リターン（翌日 t+1 の日中で執行）の評価に使うことを明記。

実装後、私がセル7〜9を実行する手順を提示してください。
```

**動作確認**: CC リターンが (営業日数-1, 26)、OC リターンが (営業日数, 17) の shape であること。OC リターンに極端な外れ値（±50% 超）が無いこと。

---

## SECTION 2C: 事前相関行列とバックテストループ

**プロンプト**:

```
01_paper_replication.ipynb に、事前相関行列の構築とバックテストループを追加します。
ルックアヘッド（未来情報の混入）を構造的に防ぐことが最重要です。

### セル10: 事前相関行列 C_full の構築
- 期間 2010-01-01 〜 2014-12-31 の共通営業日で、26銘柄の標準化 CC リターンから相関行列を計算
- np.save で data/prior/C_full.npy に保存
- 26x26 であることと対角が概ね1であることを print

### セル11: 事前部分空間 V0 と事前相関行列 C0
- src.pca_engine の build_prior_subspace を n_us=9, n_jp=17 と get_universe_masks の結果で呼ぶ
- V0 の shape が (26, 3) であることを確認
- build_target_correlation で C0 を構築、対角が1であることを確認

### セル12: バックテストループ
パラメータ: L=60, K=3, lam=0.9, q=0.3
バックテスト期間: 2015-01-01 以降の共通営業日（C_full が 2010-2014 のため）

各営業日 t について以下を実行。【ルックアヘッド防止のため、以下の index 規約を厳守】：
- 共通営業日インデックスを使う。t は整数 index
- 推定ウィンドウ W_t = CC リターンの index [t-60, t-1]（t を含まない）
- W_t 内の平均・標準偏差で標準化し、ウィンドウ内相関行列 C_t を計算
- C_reg = (1-lam) * C_t + lam * C0
- 固有分解して上位 K 固有ベクトルを抽出、米国/日本ブロックに分割
- 米国の【当日 t】の CC リターンを、【W_t の平均・標準偏差】で標準化 → z_us_t
  （z_us_t の標準化に t 自身の統計量を使わない。必ずウィンドウ統計量を使う）
- f_t = V_us^T @ z_us_t
- signal_t = V_jp @ f_t   （これは t+1 の予測）
- 日本17銘柄を signal_t でソート、上位5ロング・下位5ショート、等ウェイト
- 戦略リターン R = sum(w * r_oc[日本, t+1])  ← OC リターン、index は t+1
- 各日について {date_t, date_t1, signal(17銘柄), realized_oc(17銘柄,翌日), strategy_return} を記録

ループ内に以下の assert を入れて、ルックアヘッドを構造的に検出：
- assert ウィンドウの最終 index < t
- assert signal を計算した日付 < リターンを実現した日付

結果を DataFrame（または辞書のリスト）として保存。バックテスト日数を print。

実装後、私がセル10〜12を実行する手順を提示してください。
セル12 は時間がかかる可能性があるので、進捗表示（tqdm など）を入れてください。
```

**動作確認**: ループがエラーなく完走し、assert に引っかからないこと。バックテスト日数が想定（2015〜2025 の共通営業日、概ね 2,000 日台）であること。

---

## SECTION 2D: 検証レイヤー（ここが v3 の核心）

**プロンプト**:

```
01_paper_replication.ipynb に検証レイヤーを追加します。
要件定義書 v3 §4 の検証指標をすべて実装してください。
このセクションの結果でセクション2の合否を判定します。

### セル13: Information Coefficient (IC)
- 各営業日 t について、signal_t（17銘柄）と realized_oc（翌日17銘柄）の
  Spearman 順位相関を計算
- 全期間の IC 系列を作り、平均 IC・IC の標準偏差・t値（平均/(標準偏差/sqrt(N))）を print
- IC 系列の累積和をプロット（右肩上がりなら予測力が安定している証拠）
- 合格ライン: 平均 IC が正、t値 > 2

### セル14: 分位スプレッド
- 各日、signal_t で日本17銘柄を5分位に分割
- 各分位の平均翌日 OC リターンを全期間で集計
- 5分位の平均リターンを棒グラフで表示
- 合格ライン: 上位分位 > 下位分位、かつ概ね単調

### セル15: ルックアヘッド監査（シフト）
- signal 系列をさらに +1 営業日ずらして、誤った対応で P/L を再計算
- 正しい対応の R/R と、+1ずらした R/R を並べて print
- 合格ライン: +1ずらすとパフォーマンスが大きく低下する
  （低下しない、または改善する場合は未来情報のリーク。原因を調査して報告）

### セル16: ルックアヘッド監査（シャッフル）
- 各日の signal を銘柄方向にランダムシャッフル（seed 固定）して P/L を再計算
- 正しい signal の R/R と、シャッフル後の R/R を並べて print
- 合格ライン: シャッフルすると R/R がほぼゼロになる

### セル17 (Markdown): 検証結果の合否判定
セル13〜16 の結果を表にまとめ、要件定義書 v3 §4.2 の合格条件と照合。
合格／不合格を明記し、不合格なら原因の仮説を書く。

実装後、私がセル13〜17を実行する手順を提示してください。
```

**動作確認**:
- セル 13：平均 IC が正、t 値 > 2
- セル 14：分位スプレッドが単調（上位 > 下位）
- セル 15：シフトでパフォーマンスが崩れる
- セル 16：シャッフルで R/R がほぼゼロ
- **いずれかが不合格なら、Claude Code に「セクション2Dの検証が不合格。原因を調査して」と依頼し、SECTION 3 に進まない**
- 特にセル 15 でパフォーマンスが崩れない場合は、ルックアヘッドバグの可能性が最も高いので最優先で調査

---

## SECTION 2E: パフォーマンス評価と論文比較

**プロンプト**:

```
01_paper_replication.ipynb に、パフォーマンス評価セルを追加します。

### セル18: パフォーマンス指標（年率化係数 252）
strategy_return 系列から以下を計算して print：
- 年率リターン AR = mean(daily) * 252
- 年率リスク RISK = std(daily) * sqrt(252)
- R/R = AR / RISK
- 最大ドローダウン MDD = 累積リターン曲線からのピーク比最大下落幅
※ 年率化係数は 252 を使う（論文式(27)(28)の「12」は月次用の誤植と判断。要件定義書 v3 §0 C5）

### セル19: 累積リターン曲線
strategy_return の累積リターンをプロット。

### セル20 (Markdown): 論文値との比較と乖離要因の文書化
論文値（AR 23.79%, RISK 10.70%, R/R 2.22, MDD 9.58%）と本実装の値を表で比較。
要件定義書 v3 §4.3 の既知の乖離要因（データソース、ユニバース9 vs 11、評価期間、
OC実装差）を挙げ、どれがどの程度効いていそうかを考察。

【重要】R/R が論文と乖離していても、SECTION 2D の検証レイヤーがすべて合格なら
セクション2は合格とする。R/R 一致は目的ではない。

実装後、私がセル18〜20を実行する手順を提示してください。
```

**動作確認**: R/R が [1.0, 3.0] なら「データ・期間差を踏まえ論文と整合」。0.5 未満かつ SECTION 2D が不合格ならバグ。

**Git コミット（SECTION 2 全体完了後）**:
```bash
git add notebooks/01_paper_replication.ipynb data/prior/C_full.npy
git commit -m "Section 2: Paper replication backtest with validation layer (IC, quantile spread, lookahead audit)"
git push
```

**重要**: SECTION 2D の検証レイヤーがすべて合格して初めて SECTION 3 に進む。

---

# SECTION 3: データローダー実装

**目的**: SECTION 2A・2B の処理を本番運用用のモジュール（src/data_loader.py, src/returns.py）に切り出す。

**プロンプト**:

```
SECTION 2 の Notebook で実装したデータ取得・リターン計算を、本番運用用のモジュールに
切り出してください。要件定義書 v3 §3 に従ってください。

## ファイル1: src/returns.py
型ヒントと docstring 必須。

### compute_cc_returns(prices_close: pd.DataFrame) -> pd.DataFrame
調整後終値から Close-to-Close リターンを計算。最初の行は NaN。

### compute_oc_returns(prices_open: pd.DataFrame, prices_close: pd.DataFrame) -> pd.DataFrame
調整後始値・終値から Open-to-Close リターンを計算（同一営業日 Close/Open - 1）。

## ファイル2: src/data_loader.py
型ヒントと docstring 必須。

### fetch_prices(start_date, end_date, tickers=None, cache_path=None) -> tuple[pd.DataFrame, pd.DataFrame]
- tickers が None なら src.universe.ALL_TICKERS
- yfinance.download を auto_adjust=True で呼び、Open と Close の2つの DataFrame を返す
- 共通営業日インターセクション（全銘柄の Close が非欠損の日付のみ）を適用
- Open も同じ日付集合に揃える
- cache_path 指定時はキャッシュの読み書き（Open/Close 両方）
- 取得失敗時は最大3回リトライ（指数バックオフ）
- 連続3営業日以上の欠損があれば警告ログ
- 戻り値: (open_df, close_df)

### get_common_calendar(close_df: pd.DataFrame) -> pd.DatetimeIndex
共通営業日インデックスを返すヘルパー。

## テスト: tests/test_returns.py
1. test_compute_cc_returns: ダミー価格で CC リターンが手計算と一致
2. test_compute_oc_returns: ダミーの open/close で OC リターンが手計算と一致
3. test_oc_returns_no_nan: OC リターンに NaN が出ないこと

## テスト: tests/test_data_loader.py
1. test_fetch_prices_small_range: 直近1ヶ月の XLK のみ取得、行数>10。@pytest.mark.network
2. test_common_calendar: ダミー DataFrame で共通営業日が正しく抽出される

実装後、動作確認スクリプトとコマンドを提示してください。
```

**動作確認**:
```bash
pytest tests/test_returns.py tests/test_data_loader.py -v -m "not network"
python -c "from src.data_loader import fetch_prices; o,c = fetch_prices('2024-01-01','2024-03-01'); print(o.shape, c.shape)"
```

**Git コミット**:
```bash
git add src/returns.py src/data_loader.py tests/test_returns.py tests/test_data_loader.py
git commit -m "Section 3: Implement returns module and production data loader"
git push
```

---

# SECTION 4: シグナル生成ロジック

**目的**: PCA エンジン・データローダー・リターンモジュールを組み合わせ、日次シグナルを生成するモジュールを作る。

**プロンプト**:

```
src/pca_engine.py, src/data_loader.py, src/returns.py, src/universe.py を組み合わせて、
日次シグナル生成モジュールを実装してください。
SECTION 2 のバックテストループと同一のロジック・同一の index 規約を使うこと。

## ファイル: src/signal_generator.py

### SignalConfig (dataclass)
window_length: int = 60
n_components: int = 3
lambda_reg: float = 0.9
quantile: float = 0.3

### generate_signal(open_df, close_df, target_date, C0, config) -> dict
処理（SECTION 2C のループ1日分と完全に同じロジック）:
1. 共通営業日インデックス上で target_date の位置 t を特定
2. ウィンドウ W_t = [t-60, t-1]（t を含まない）の CC リターンを取得
3. W_t 内の平均・標準偏差で標準化、ウィンドウ内相関行列 C_t を計算
4. C_reg = (1-lam) C_t + lam C0、固有分解、上位 K 抽出、米/日ブロック分割
5. 米国の【当日 t】CC リターンを W_t 統計量で標準化 → z_us_t
6. f_t = V_us^T @ z_us_t、signal = V_jp @ f_t
7. 日本17銘柄をスコア順にソート、上位5ロング・下位5ショート
戻り値: {'date': target_date, 'long_basket': [...], 'short_basket': [...],
         'all_scores': pd.Series, 'factor_scores': np.ndarray}

エッジケース: target_date が共通営業日にない / ウィンドウ分の過去データが足りない /
価格に NaN → ValueError

### load_prior_correlation(path) -> np.ndarray
data/prior/C_full.npy を読む。無ければ ValueError。

## テスト: tests/test_signal_generator.py
1. test_generate_signal_shape: ダミー26銘柄×100日で long/short が各5銘柄、all_scores が17要素
2. test_signal_config_defaults: デフォルト値が要件定義書 v3 §2.2 通り
3. test_generate_signal_matches_backtest: 【重要】SECTION 2C のループと同じ日付・同じ入力で
   呼び、シグナルが一致することを確認（実装の二重化によるズレを防ぐ）

実装後、scripts/check_signal.py（直近データでシグナル生成を試すスクリプト）を作成してください。
```

**動作確認**:
```bash
pytest tests/test_signal_generator.py -v
python scripts/check_signal.py
```
- `test_generate_signal_matches_backtest` が通ること（SECTION 2 のループと結果が一致）

**Git コミット**:
```bash
git add src/signal_generator.py tests/test_signal_generator.py scripts/check_signal.py
git commit -m "Section 4: Implement signal generation (consistent with Section 2 backtest)"
git push
```

---

# SECTION 5: ロット計算機能

**目的**: 想定運用額からロット数を自動計算する。（v2 から実質変更なし）

**プロンプト**:

```
日本の TOPIX-17 ETF のロット数を、想定運用額から自動計算する機能を実装してください。

## ファイル: src/lot_calculator.py
注意: TOPIX-17 ETF は通常10株単位（単元株）。

### calculate_lots(capital_jpy, long_tickers, short_tickers, prices_dict, unit_size=10) -> dict
- 各銘柄の目標金額 = capital_jpy * 0.5 / 5（ロング側5銘柄に等分配、ショート側も同様）
- shares = floor(目標金額 / 株価)、lots = floor(shares / unit_size)、実 shares = lots * unit_size
- 戻り値: {'long': [{'ticker','lots','shares','price','value'}], 'short': [...],
          'total_long_value','total_short_value','total_gross_exposure','cash_remaining'}

### fetch_latest_prices(tickers) -> dict[str, float]
yfinance の最新終値（fast_info.last_price）。失敗したら例外。

## テスト: tests/test_lot_calculator.py
1. test_calculate_lots_basic: capital=5_000_000、ダミー価格。lots*unit_size==shares、cash_remaining>=0
2. test_calculate_lots_underfunded: 1ロットも買えない場合の挙動

実装後、動作確認コマンドを提示してください。
```

**動作確認**: `pytest tests/test_lot_calculator.py -v`

**Git コミット**:
```bash
git add src/lot_calculator.py tests/test_lot_calculator.py
git commit -m "Section 5: Implement lot calculator"
git push
```

---

# SECTION 6: LINE 通知実装

**目的**: LINE Messaging API でシグナルを通知する。（v2 から実質変更なし）

**前提作業（あなたが手動でやること）**:
1. https://developers.line.biz/console/ でアカウント作成 → Messaging API チャネル作成
2. チャネルアクセストークン（長期）を発行・メモ
3. 自分の LINE で Bot を友だち追加、userId を取得

**プロンプト**:

```
LINE Messaging API でシグナル通知を実装してください。
公式 SDK は使わず requests で直接 API を叩いてください（依存削減のため）。

## ファイル: src/line_notifier.py

### format_signal_message(signal_result, lot_result, capital_jpy) -> str
日付・運用額・ロング5銘柄（業種名つき・ロット数）・ショート5銘柄・ファクタースコアを
含むテキスト。業種名は src.universe.JP_SECTOR_NAMES を使う。絵文字は使用可。

### send_line_message(message, channel_access_token, user_id) -> bool
POST https://api.line.me/v2/bot/message/push
ヘッダー: Authorization: Bearer <token>, Content-Type: application/json
ボディ: {"to": <user_id>, "messages": [{"type":"text","text": <message>}]}
タイムアウト10秒。失敗時はログ出力して False。

### send_error_notification(error_message, channel_access_token, user_id)
エラー専用フォーマット（時刻・詳細）。

## テスト: tests/test_line_notifier.py
1. test_format_signal_message: ダミーデータで銘柄が文字列に含まれる
2. test_send_line_message_invalid_token: 無効トークンで False。@pytest.mark.network

実装後、scripts/test_line_send.py（手動送信テスト）を作成してください。
```

**動作確認**: `.env` に LINE トークンと userId を記入 → `python scripts/test_line_send.py` → LINE にメッセージが届く

**Git コミット**:
```bash
git add src/line_notifier.py tests/test_line_notifier.py scripts/test_line_send.py
git commit -m "Section 6: Implement LINE notifier"
git push
```

---

# SECTION 7: メインスクリプト統合

**目的**: 全モジュールを 1 本のエントリポイントにまとめる。

**プロンプト**:

```
これまで実装したモジュールを統合し、毎朝実行されるメインスクリプトを作ってください。

## ファイル: src/main.py

処理フロー:
1. 環境変数を読み込む（dotenv）: LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID, CAPITAL_JPY
2. データ取得: 過去90営業日+バッファ。open_df, close_df を取得。キャッシュ data/cache_prices.csv
3. 事前相関行列を読み込む: data/prior/C_full.npy
4. シグナル生成: target_date = 直近の共通営業日。generate_signal を呼ぶ
5. ロット計算: fetch_latest_prices → calculate_lots
6. LINE 通知: format_signal_message → send_line_message
7. 結果保存:
   - data/signals/{YYYY-MM-DD}.csv （シグナル詳細：date,ticker,score,rank,position,suggested_lots）
   - docs/data.json （ダッシュボード用、後述フォーマット）
8. ログ出力（標準出力）: 各ステップの開始・完了、例外時はトレースバック

エラーハンドリング: 各ステップで例外発生時は send_error_notification で LINE 通知し、
例外を再 raise して GitHub Actions のジョブも失敗扱いにする。

docs/data.json フォーマット:
{
  "last_updated": "ISO8601",
  "current_signal": {"date","long_basket","short_basket","factor_scores"},
  "history": [{"date","long","short"}, ...直近100営業日分...]
}
history は data/signals/ 以下の全 CSV を集約。

if __name__ == '__main__': main()

実装後、ローカルでの動作確認手順を提示してください。
```

**動作確認**: `python -m src.main` → LINE にメッセージが届く、`data/signals/{date}.csv` と `docs/data.json` が生成される

**Git コミット**:
```bash
git add src/main.py data/
git commit -m "Section 7: Integrate main entry point"
git push
```

---

# SECTION 8: リモート確認・README 更新

**目的**: リポジトリは既存のため「作成」は不要。リモート設定の確認と README の最新化のみ。

**プロンプト**:

```
GitHub リポジトリは既に存在し、SECTION 0〜7 をプッシュ済みです。
以下を実施してください。

## タスク1: リモート設定の確認手順
- git remote -v でリモートが正しく設定されているか確認するコマンド
- 未プッシュのコミットが無いか確認するコマンド（git status, git log --oneline origin/main..HEAD）

## タスク2: README.md の更新
SECTION 7 までの実装を反映した README.md を作成してください。含める内容:
- プロジェクト概要（個人用クオンツ・パイプラインであること）
- 26銘柄固定ユニバースであることの明記
- セットアップ手順（Python 3.11、venv、requirements.txt）
- 環境変数の説明（.env.example の各キー）
- ローカル実行方法（python -m src.main）
- ファイル構成（要件定義書 v3 §6.2 準拠）
- ライセンス（MIT）
- ⚠️ 免責事項: 個人用ツールであり投資助言を目的としない。投資判断は自己責任

実装後、README をコミット・プッシュするコマンドを提示してください。
```

**動作確認**: GitHub のリポジトリページで README が見やすく表示されている

**Git コミット**:
```bash
git add README.md
git commit -m "Section 8: Update README for v3"
git push
```

---

# SECTION 9: GitHub Actions ワークフロー

**目的**: 毎朝自動でシグナルが生成されるようにする。（v2 から実質変更なし）

**前提作業（あなたが手動でやること）**:
GitHub リポジトリ → Settings → Secrets and variables → Actions で以下を追加:
- `LINE_CHANNEL_ACCESS_TOKEN`
- `LINE_USER_ID`
- `CAPITAL_JPY`（例: 5000000）

**プロンプト**:

```
GitHub Actions ワークフローを作成してください。

## ファイル: .github/workflows/daily-signal.yml
要件:
1. cron: 平日のみ、21:00 UTC（= 翌日 06:00 JST）
2. 手動実行も可能（workflow_dispatch）
3. Python 3.11 環境、pip キャッシュを使う
4. requirements.txt から依存をインストール
5. src/main.py を実行（python -m src.main）
6. 環境変数として GitHub Secrets を渡す（LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID, CAPITAL_JPY）
7. 実行後 data/ と docs/ に変更があれば自動コミット&プッシュ
   コミットメッセージ: "Daily signal YYYY-MM-DD [skip ci]"
8. permissions: contents: write が必要。git config で github-actions[bot] を設定
9. 同日2回実行時は同名ファイル上書きで冪等

実装後、以下の確認手順を提示してください:
1. GitHub Secrets が設定されているかの確認方法
2. 「Run workflow」での手動トリガー方法
3. 実行ログの確認方法
```

**動作確認**: Actions タブから手動実行 → ジョブ成功、LINE にメッセージ、リポジトリに自動コミット

**Git コミット**:
```bash
git add .github/
git commit -m "Section 9: Add GitHub Actions workflow"
git push
```

---

# SECTION 10: GitHub Pages ダッシュボード

**目的**: ブラウザで履歴とパフォーマンスを確認できるようにする。（v2 から実質変更なし）

**前提作業**: リポジトリは Public（GitHub Pages を無料で使うため）。

**プロンプト**:

```
GitHub Pages 用の静的ダッシュボードを作成してください。
src/main.py が出力する docs/data.json を読み込んで描画します。

## docs/index.html （シングルページ）
1. ヘッダー: タイトル、最終更新日時、注意書き「個人用ツール。投資判断は自己責任で」
2. 現在のシグナル: 日付、ロング5銘柄（カード形式、業種名・スコア）、ショート5銘柄
3. 累積パフォーマンス（Plotly.js）: 理論P/L、コスト込みP/L、
   リバランス頻度切替（日次/週次/月次、JS側で再計算）
4. ファクタースコアの時系列（Plotly.js）: 3主成分の推移
5. 過去シグナル履歴（テーブル）: 直近30営業日
6. コスト設定パネル: 売買手数料/貸株料/スプレッド/スリッページ/税率、localStorage保存

## docs/style.css
ダークモード対応、レスポンシブ、システムフォント、シンプルなデザイン。

## docs/app.js
data.json を fetch、Plotly.js(CDN: https://cdn.plot.ly/plotly-2.27.0.min.js)で描画、
リバランス頻度切替の再計算、コスト設定の localStorage 保存、テーブルソート。

実装後、GitHub Pages 有効化手順（Settings → Pages → Deploy from branch → main /docs）を
提示してください。
```

**動作確認**: GitHub Pages の URL でダッシュボードが表示され、data.json の内容が反映されている

**Git コミット**:
```bash
git add docs/
git commit -m "Section 10: Add GitHub Pages dashboard"
git push
```

---

# SECTION 11: 動作確認と微調整

**目的**: 全体を通した動作確認と運用開始前の最終チェック。

**チェックリスト**:
- [ ] GitHub Actions の cron が実際に毎朝動くか（数日観察）
- [ ] LINE 通知が毎営業日届くか
- [ ] ダッシュボードが毎日更新されるか
- [ ] data/signals/ に CSV が日々追加されるか
- [ ] エラー時に LINE にエラー通知が届くか（わざとトークンを無効にしてテスト）
- [ ] yfinance のデータ欠損・遅延時の挙動（リトライが効くか）
- [ ] ロット計算が想定運用額に対して妥当か（手計算で1日分検算）
- [ ] シグナルが SECTION 2 のバックテストと整合しているか（同一日付でスポット照合）

**微調整プロンプト例**（必要に応じて）:
```
[具体的な不具合の症状] が発生しています。
関連すると思われるファイルは [ファイル名] です。
原因を調査し、修正案を提示してください。修正は最小限の変更にとどめてください。
```

---

## 補足: Claude Code（Sonnet 4.6）で進める際の注意

- **1 プロンプト = 1 関心事**。SECTION 2 のようにサブステップに割ったものは、必ずサブステップごとに渡す
- 各セクション完了時に **必ず動作確認 → コミット**。コミットせずに次へ進まない
- 不具合が出たら、そのセクション内で完結させて修正する。複数セクションをまたいで直さない
- Claude Code が要件定義書 v3 と矛盾する実装をしそうになったら、該当する §番号を引用して指摘する
- SECTION 2D の検証レイヤーが不合格のまま SECTION 3 以降に進まない。これが v3 で最も重要な規律
