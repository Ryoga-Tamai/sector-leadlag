# 引き継ぎ書 — sector-leadlag プロジェクト

**目的**: 新しい Cowork チャットでこのプロジェクトの開発を継続するための引き継ぎ。
**最終更新**: 2026-05-17（SECTION 9 完了時点）

---

## 1. プロジェクト全体像

- **要件定義書**: `requirements_v3.md`（v3.0、Opus 4.7 再定義版） — 新セッション開始時に添付（repo にも同梱済）
- **開発手順書**: `sections_v3.md`（SECTION 1.5 以降） — 同上
- **対象論文**: 中川他 (2025)「部分空間正則化付き主成分分析を用いた日米業種リードラグ投資戦略」
- **ユニバース**: **26 銘柄固定**（米国 9 + 日本 17、XLC・XLRE 除外）
- **実行環境**: GitHub Actions（無料）、ローカル Python 3.11 venv、yfinance、LINE Bot
- **GitHub Pages**: SECTION 10 で `docs/index.html` ベースのダッシュボードを実装予定（既に `docs/data.json` は SECTION 7 で出力済）

## 2. ユーザーからの絶対指示（厳守）

1. **セクションを 1 つずつ実行**。SECTION 10、11 の順で進める
2. 各セクションで「実装 → 動作確認 → Git コミット」を終えたら **必ず一度停止** してユーザー確認を待つ
3. 複数セクションを連続で進めない
4. **不合格条件があるセクションでは合格まで次に進まない**（要件定義書 §4 系列）
5. SECTION 10 では既に出力されている `docs/data.json` のスキーマに厳密に合わせる
6. サンドボックス側 git は **読み取りのみ** `git --no-optional-locks ...`。commit/push は **Mac 側 JupyterLab ターミナル** から実行

## 3. 現在の進捗（2026-05-17 時点）

| Section | 状態 | Git Commit |
|---|---|---|
| 0, 1 | ✅ 完了 | コミット済み |
| 1.5 | ✅ 完了 | `4c1f103 Section 1.5: Migrate to Python 3.11, extract universe module (26-ticker)` |
| 2A〜2E | ✅ 完了 | `7d5d118` 〜 `2c9c40a` |
| 3 | ✅ 完了 | `c474bb3 Section 3: Implement returns module and production data loader` |
| 4 | ✅ 完了 | `9321ce8 Section 4: Implement signal generation (consistent with Section 2 backtest)` |
| 5 | ✅ 完了 | `2aa2f80 Section 5: Implement lot calculator` |
| 6 | ✅ 完了 | `76141a1 Section 6: Implement LINE notifier` |
| 7 | ✅ 完了 | `409a407 Section 7: Integrate main entry point (orchestrator + first signal output)` |
| 8 | ✅ 完了 | `d6a6940 Section 8: Update README for v3; add LICENSE and spec docs` |
| 9 | ✅ 完了 | `c701e01 Section 9: Add GitHub Actions workflow (daily-signal.yml)` + `4d95f8e Section 9 patch: Bump actions to v6` |
| **10** | **🔜 次に着手** | GitHub Pages ダッシュボード（`docs/index.html` + `docs/app.js` + `docs/style.css`） |
| 11 | 未着手 | 動作確認と微調整（長期観察フェーズ） |

## 4. SECTION 3〜9 の実装サマリと検証結果

### SECTION 3（データローダー本番化）
- `src/returns.py`: `compute_cc_returns`（`pct_change(fill_method=None)`）、`compute_oc_returns`（同一日 Close/Open − 1）
- `src/data_loader.py`: `fetch_prices(start, end, tickers, cache_path)`（yfinance auto_adjust=True、Open/Close 両方、共通営業日インターセクション、staleness 両端 7d、3 回指数バックオフ・リトライ）、`get_common_calendar`
- 検証：実データ `data/cache_prices.csv` での Notebook セル 6・7 との parity が 4 系列で完全一致（`values_eq=True`）

### SECTION 4（シグナル生成）
- `src/signal_generator.py`: `SignalConfig`（dataclass、`L=60, K=3, λ=0.9, q=0.3`）、`generate_signal(open_df, close_df, target_date, C0, config)`、`load_prior_correlation(path)`
- `scripts/check_signal.py`（CLI、`--target-date`、`--lookback-days`、`--cache-path`、`--prior-path`）
- **最重要保証**：`test_generate_signal_matches_backtest` で Notebook セル 11 のループ本体と bit-identical
- 副次 bug-fix：`compute_cc_returns` を `fill_method=None` 明示

### SECTION 5（ロット計算）
- `src/lot_calculator.py`: `calculate_lots(capital, long, short, prices, unit_size=10)`、`fetch_latest_prices(tickers)`（`yf.Ticker(tk).fast_info.last_price`）
- 配分：`target = capital * 0.5 / N`、`shares = floor(target/price)`、`lots = shares // unit_size`、戻り値に `total_gross_exposure` と `cash_remaining`

### SECTION 6（LINE 通知）
- `src/line_notifier.py`: `format_signal_message`（業種名・lots・factor scores・exposure）、`send_line_message`（POST /v2/bot/message/push、10s timeout、never-throw、4xx/network-error/timeout で `False`）、`send_error_notification`（JST タイムスタンプ envelope、body は 4700 chars で truncate）
- `scripts/test_line_send.py`: `.env` の `LINE_CHANNEL_ACCESS_TOKEN` と `LINE_USER_ID` を読み、canned 送信または `--with-signal` で実シグナル全パイプライン送信

### SECTION 7（メインスクリプト統合）
- `src/main.py`: 8 ステップの orchestrator のみ。ビジネスロジックは 100% 既存モジュールに委譲
  - 1. dotenv で env 読込 (`LINE_CHANNEL_ACCESS_TOKEN` / `LINE_USER_ID` / `CAPITAL_JPY`、既定 5,000,000)
  - 2. `fetch_prices`：lookback 180 営業日 → calendar `int(180 * 1.6) + 14` 日に換算
  - 3. `load_prior_correlation` + `build_prior_subspace` + `build_target_correlation`
  - 4. `generate_signal`（`target_date = close_df.index[-1]`）
  - 5. `fetch_latest_prices` + `calculate_lots`
  - 6. `format_signal_message` + `send_line_message`（creds 欠如時は WARN ログ、ファイル出力は継続）
  - 7. `data/signals/{YYYY-MM-DD}.csv`（17 JP 行、列 `date,ticker,score,rank,position,suggested_lots`）と `docs/data.json` を上書き
  - 8. ログは `print(flush=True)` で stdout（GHA に残る）。例外時は `send_error_notification` + re-raise
- `tests/test_main.py`: 19 件（_resolve_capital × 5、_write_signal_csv × 3、_build_history/data.json × 4、run_pipeline mocked × 5、main entry × 2）
- 実機検証：Mac venv で `python -m src.main` 完走、LINE 受信、`2026-05-15.csv` 17 行 + `data.json` 出力確認

### SECTION 8（README / LICENSE / spec docs）
- `README.md` 全面書き直し（v1 時代の `data_fetcher.py` 参照を一掃、v3 仕様準拠の構成・進捗表・免責事項に整備）
- `LICENSE`（MIT、GitHub サイドバーで自動認識）追加
- `requirements_v3.md` / `sections_v3.md` を repo に同梱（README リンクを生かす）

### SECTION 9（GitHub Actions ワークフロー + Node.js 24 patch）
- `.github/workflows/daily-signal.yml`：
  - cron: `0 21 * * 0-4` = UTC Sun-Thu = **JST Mon-Fri 06:00 固定**（JP 取引日朝に毎日発火）
  - `workflow_dispatch` で手動トリガー可
  - `permissions: contents: write`、`concurrency: daily-signal` で逐次実行
  - Python 3.11、pip キャッシュ、`requirements.txt` から install
  - env 経由で 3 つの Secrets を `python -m src.main` に渡す
  - auto-commit: `git add data/signals/ docs/` のみ（`data/cache_prices.csv` と `data/prior/` は除外）
  - commit message: `Daily signal {JST YYYY-MM-DD} [skip ci]` で自己ループ防止
- **重要 patch** (`4d95f8e`)：`actions/checkout@v4` → `@v6`、`actions/setup-python@v5` → `@v6`
  - 理由：Node.js 20 deprecation。2026-06-02 forced upgrade、2026-09-16 removal
  - v6 は Node.js 24 ネイティブ。パラメータ互換性 OK（破壊的変更なし）
- 検証：Run #1（旧 v4/v5、warning あり）と Run #2（新 v6/v6、warning 完全消失）の両方で 50s/40s 完走、LINE 受信、auto-commit (`bc4f36d`, `668759a`) 反映

### 全体テストカウント（SECTION 9 完了時点、Mac venv）
- オフライン: **92 件 PASS**（test_data_loader 15、test_line_notifier 15、test_lot_calculator 12、test_main 19、test_pca_engine 8、test_returns 9、test_signal_generator 14）
- network: 5 件 PASS（fetch_prices XLK、fetch_latest_prices XLK・1618.T、send_line_message_invalid_token、ほか）

## 5. SECTION 10 実装の注意（次セッション最重要）

要件定義書 v3 §3 / §4、sections_v3.md SECTION 10 に従って GitHub Pages ダッシュボードを実装。

### 既存資産（SECTION 7-9 で完成）
- **`docs/data.json`**：GHA が毎営業日朝に自動更新。SECTION 10 はこれを fetch するだけ
  ```json
  {
    "last_updated": "ISO 8601 (JST)",
    "current_signal": {
      "date": "YYYY-MM-DD",
      "long_basket":  ["1618.T", ...],
      "short_basket": ["1633.T", ...],
      "factor_scores": [PC1, PC2, PC3],
      "all_scores":    { "1617.T": float, ... }    // 17 JP tickers
    },
    "history": [
      { "date": "YYYY-MM-DD", "long": [...], "short": [...] },
      ...   // 最大 100 営業日
    ]
  }
  ```
- **業種名マスタ**：JS 側で `src/universe.py` の `JP_SECTOR_NAMES` を二重定義する必要あり。または `docs/data.json` のスキーマを拡張するか、ハードコードするか SECTION 10 で判断

### 実装要件（sections_v3.md SECTION 10 から抜粋）
1. **ヘッダー**: タイトル、最終更新日時、注意書き「個人用ツール。投資判断は自己責任で」
2. **現在のシグナル**: 日付、ロング 5 銘柄（カード形式、業種名・スコア）、ショート 5 銘柄
3. **累積パフォーマンス（Plotly.js）**: 理論 P/L、コスト込み P/L、リバランス頻度切替（日次/週次/月次、JS 側で再計算）
4. **ファクタースコアの時系列（Plotly.js）**: 3 主成分の推移
5. **過去シグナル履歴（テーブル）**: 直近 30 営業日
6. **コスト設定パネル**: 売買手数料/貸株料/スプレッド/スリッページ/税率、localStorage 保存
7. **ダークモード対応、レスポンシブ、システムフォント、シンプルなデザイン**

### CDN（仕様書指定）
- Plotly.js: `https://cdn.plot.ly/plotly-2.27.0.min.js`（バージョン固定）

### localStorage キー命名（提案）
- 競合回避のため `slc:` プレフィックスを推奨：`slc:cost:fee`, `slc:cost:slippage`, `slc:cost:borrow`, `slc:cost:spread`, `slc:cost:tax`, `slc:rebalance_freq`

### GitHub Pages の有効化（取締役側の手動作業）
- Settings → Pages → "Build and deployment" → Source: **"Deploy from a branch"**
- Branch: **main**、Folder: **/docs**
- 反映先 URL: `https://ryoga-tamai.github.io/sector-leadlag/`

### history が現時点で 1 件しかない問題
- `docs/data.json` の `history` は SECTION 7 を実行した 1 日分しか入っていない
- GHA が毎営業日動けば自然に積み上がるが、ダッシュボード初期表示時に履歴が薄いのは仕様
- 累積 P/L プロットは history が増えるまでデモデータ or 空状態の UI が必要

### 既存モジュールの再利用ポイント
- バックフィル（過去シグナルを一括生成）したい場合、`scripts/check_signal.py` を拡張して期間ループにする手もある（SECTION 10 でやるか SECTION 11 でやるかは判断）

## 6. 既知の運用ノウハウ・落とし穴

### 6.1 `.git/index.lock` 残留問題（重要）

サンドボックスから git 読み取り操作を実行すると、マウント権限の問題で `.git/index.lock` が unlink できず残留することがある。Mac 側 `git add` / `git commit` が `fatal: Unable to create '.git/index.lock'` で失敗する。

**対処**:
- サンドボックス側の読み取り系 git コマンドは必ず `git --no-optional-locks ...` を使用
- `git show HEAD:path` は lock を取らないのでそのまま使える
- それでも lock が残ったら Mac 側で `rm -f .git/index.lock`
- **commit / push は Mac 側 JupyterLab ターミナルから実行する** のが安全

### 6.2 サンドボックスからの書き込み制限

- `git checkout HEAD -- path` → サンドボックスから実行すると "Operation not permitted" でファイル unlink 失敗する
- 代わりに `python3 -c "import subprocess; open(path,'w').write(subprocess.check_output(['git','show','HEAD:'+path]).decode())"` で上書き
- `rm` も権限不足で失敗することがある → Mac 側で削除

### 6.3 `data/cache_prices.csv` のドリフトと commit 戦略

- `data/cache_prices.csv` は **コミット非対象推奨**（要件定義書 §3.4）。.gitignore に追加するのが本来。現状は tracking 済み
- `scripts/check_signal.py` や `python -m src.main` を実行すると cache が再書き込みされ、byte 単位の差分が出る
- SECTION 3〜7 のコミットでは、毎回 `git checkout HEAD -- data/cache_prices.csv` で巻き戻してから `git add` する習慣を徹底
- **SECTION 9 以降は GHA 自動コミットが `git add data/signals/ docs/` でパス指定するため、cache の問題は自動的に解決**（ローカル開発時のみ revert が必要）

### 6.4 Notebook の編集パターン（SECTION 2 時代の遺産）

- 既存セルを保ったまま末尾追加する `notebooks/append_section_NX.py` パターンを使う
- 冪等化のため、フィルタはセルの先頭行（`startswith`）で判定する
- f-string で `\n` を triple-quoted 文字列内に書くと、Python パーサーが実改行に展開して syntax error → `print("")` で空行を出す or `\\n` でエスケープ
- nbconvert 用に各セルに UUID が必要：`{"id": uuid.uuid4().hex[:8]}` を `_code_cell` / `_markdown_cell` ヘルパー内で設定

### 6.5 サンドボックス Python と Mac venv の使い分け

- **サンドボックス側 yfinance はプロキシブロック**（403）。本番データ取得は Mac 側 jupyter のみ
- サンドボックスの `python3` は 3.10、追加依存は `pip install <pkg> --break-system-packages`
- Mac 側 venv は Python 3.11.15（broken symlink でサンドボックスから直接実行は不可、Mac 側ターミナルで `source venv/bin/activate` 経由）
- ロジック検証はサンドボックスで完結、network 必要な実機検証は Mac 側で実行
- **typical workflow**：
  1. サンドボックスで Read/Write/Edit → `pip install` → `pytest -m "not network"`
  2. Mac venv 起動 → `pytest tests/ -v`（network 込み）
  3. Mac venv で実機スモーク（`scripts/check_signal.py` や `python -m src.main`）
  4. Mac 側 JupyterLab ターミナルから `git commit && git push`

### 6.6 JupyterLab 連携（Claude in Chrome 経由）

- Mac 側で起動: `cd <project> && source venv/bin/activate && jupyter lab --port=8889 --no-browser`
- 起動後、token 付き URL（`http://127.0.0.1:8889/lab?token=...`）を新セッションに貼ってもらう
- 既に動いている場合は `jupyter server list` で URL 再取得可能
- Claude in Chrome で `mcp__Claude_in_Chrome__navigate` → File menu の `+` → Other > Terminal で JupyterLab ターミナルを開く
- **そこから直接 `pytest`、`python scripts/...`、`git ...` を実行する**のが定番フロー
- サンドボックス側 Claude が `notebooks/01_paper_replication.ipynb` をディスク上で書き換えた直後は、ブラウザを `cmd+r` でリロードしないと反映されない

### 6.7 JupyterLab UI 操作の Tips

- メニュー位置（929×775 viewport 想定）: File/Edit/View/Run/Kernel/Tabs/Settings/Help = X 座標 53/93/137/181/230/282/339/396、Y=14
- Run メニューの「Run Selected Cell and All Below」: 開いた直後の Y=180 付近
- Kernel メニューの「Restart Kernel and Run All Cells...」: 開いた直後の Y=147 付近
- 「Run Selected Cell and All Below」が止まる場合は、セルが syntax error 等で失敗している可能性
- ターミナル開く操作：file browser の「+」ボタンで Launcher → "Other" セクション → "Terminal" をクリック
- `mcp__Claude_in_Chrome__computer.wait` は最大 10 秒。長時間処理を待つときは 10 秒の wait を複数回に分ける

### 6.8 Chrome 拡張のテキスト出力フィルタ

- 一部の出力テキストが `[BLOCKED: Cookie/query string data]` で取れないことがある（URL や token 風文字列が含まれる場合）
- このときは Notebook を Mac 側で `cmd+s` 保存 → サンドボックスから `.ipynb` を読み取って outputs を抽出する迂回路を使う

### 6.9 複数ブラウザ接続時の混同回避

- セッション途中で別 OS のブラウザ拡張が接続される場合あり（list_connected_browsers で複数表示される）
- 必ず元々使っていた deviceId を `select_browser` で指定し直す習慣にする

### 6.10 `pd.DataFrame.pct_change` の `fill_method`

- pandas のデフォルト `fill_method='pad'` は NaN を前方補完してしまうため、SECTION 4 の NaN 検出契約に支障あり
- `src/returns.py` の `compute_cc_returns` は `fill_method=None` を明示
- クリーン入力（共通営業日インターセクション後）では出力が legacy default と完全一致なので SECTION 3 parity は保持

### 6.11 LINE Messaging API のセットアップ済み事項

- LINE Developers Console でプロバイダー＋ Messaging API チャネル作成済み
- 長期チャネルアクセストークン発行済み、`.env` に記入済み、`LINE_USER_ID` も取得済み
- 動作確認済み：`scripts/test_line_send.py`、`scripts/test_line_send.py --with-signal`、`python -m src.main`、GHA workflow から実機 LINE 受信
- 漏洩疑い時の対処：LINE Developers Console の「再発行」ボタンで古いトークン無効化、`.env` と GitHub Secrets を書き換え

### 6.12 `data/prior/C_full.npy` のコミット非対象問題

- `data/prior/C_full.npy`（5.5 KB）は Notebook の再実行で byte 差分が出ることがある（中身は実質同じ）
- SECTION 9 の GHA auto-commit は `git add data/signals/ docs/` のパス指定で C_full.npy を除外しているので問題なし
- ローカル Notebook 再実行時のみ手動 `git checkout HEAD -- data/prior/C_full.npy` で revert

### 6.13 GHA auto-commit 後の Mac 側 push 競合（NEW・SECTION 9 で観測）

- 手動トリガーや cron で GHA が auto-commit (`github-actions[bot]`) を push すると、Mac ローカルが 1 コミット遅れる
- 続けて Mac 側で commit & push しようとすると `! [rejected] main -> main (non-fast-forward)` でエラー
- **対処**: `git pull --rebase origin main && git push origin main`
- **予防**: Mac 側で commit する前に `git --no-optional-locks fetch && git --no-optional-locks status` で `origin/main` の先行を確認する
- SECTION 9 patch 時に実際に遭遇 → rebase で同期して `4d95f8e` を push

### 6.14 GitHub Actions の action バージョン管理（NEW・SECTION 9 patch で確立）

- **Node.js 20 actions は 2026-06-02 forced upgrade、2026-09-16 removal**（GitHub 公式アナウンス）
- 現在の固定版（SECTION 9 patch 後）：
  - `actions/checkout@v6`（最新タグ v6.0.2、2026-01-10）— Node.js 24 ネイティブ
  - `actions/setup-python@v6`（最新タグ v6.2.0、2026-01-22）— Node.js 24 ネイティブ
- バンプ手順：YAML の `uses:` 行を変更 → `git add .github/ && git commit -m "..."` → push → Actions タブで Run workflow 手動トリガー → annotations 欄が空になることを確認
- 将来の bump：GitHub の deprecation 通知（Actions タブの annotations、メールアラート）を契機に判断

### 6.15 GHA cron の timezone 解釈（NEW・SECTION 9 で確立）

- GitHub Actions の cron は **UTC** のみ。`POSIX TZ` は使えない
- 現行: `0 21 * * 0-4`（UTC Sun-Thu 21:00）= **JST Mon-Fri 06:00**（JP 取引日朝固定）
- sections_v3.md SECTION 9 の文言「平日のみ、21:00 UTC」を JST 平日と解釈
- `0 21 * * 1-5`（UTC Mon-Fri）にすると JST Tue-Sat 06:00 になり、JP Mon 取引時に signal が 2 日古くなるアンチパターン
- GHA cron は 10-30 分の遅延あり。`fetch_prices` の `staleness_tol_days=7` で吸収

### 6.16 SECTION 7 で生成される data/signals の運用（NEW）

- `data/signals/{YYYY-MM-DD}.csv` は signal_generator の `target_date.strftime("%Y-%m-%d")` を使う = **最新の共通営業日**の日付
- GHA の commit message `Daily signal {JST date} [skip ci]` は実行日（JST）の日付なので、CSV のファイル名と一致しない場合がある
  - 例: 月曜 06:00 JST 実行 → commit message は月曜の日付、CSV ファイル名は前週金曜の日付
- これは**仕様通り**（投資判断対象日と実行日が異なる）。混乱しないよう設計時に意識

## 7. 作業環境

- **リポジトリパス**: `/Users/tamairyoga/Desktop/MacBook Pro/システム開発/sector-leadlag`
- **GitHub remote**: `https://github.com/Ryoga-Tamai/sector-leadlag.git`
- **GitHub Pages URL (SECTION 10 反映後)**: `https://ryoga-tamai.github.io/sector-leadlag/`
- **venv**: 同フォルダ内 `venv/`（Python 3.11.15）
- **Notebook**: `notebooks/01_paper_replication.ipynb`（SECTION 2E まで完了、SECTION 3 以降は本番モジュールに移行）
- **キャッシュ**: `data/cache_prices.csv`（3.5 MB、コミット非対象推奨だが現状 tracking 済み）
- **事前相関**: `data/prior/C_full.npy`（5.5 KB、コミット推奨）
- **シグナル履歴**: `data/signals/YYYY-MM-DD.csv`（GHA で毎営業日生成・コミット）
- **ダッシュボード入力**: `docs/data.json`（SECTION 7 が出力、SECTION 10 が消費）
- **GHA ワークフロー**: `.github/workflows/daily-signal.yml`（SECTION 9）
- **ヘルパースクリプト**:
  - `notebooks/append_section_2d.py`、`notebooks/append_section_2e.py`（SECTION 2 用、コミット済み）
  - `scripts/check_signal.py`（SECTION 4 用、コミット済み）
  - `scripts/test_line_send.py`（SECTION 6 用、コミット済み）
- **検証 HTML**: `.gitignore` で除外済み
- **テスト一覧**:
  - `tests/test_pca_engine.py`（SECTION 1）
  - `tests/test_returns.py`、`tests/test_data_loader.py`（SECTION 3）
  - `tests/test_signal_generator.py`（SECTION 4）
  - `tests/test_lot_calculator.py`（SECTION 5）
  - `tests/test_line_notifier.py`（SECTION 6）
  - `tests/test_main.py`（SECTION 7、新規 19 件）
- **`.env`**（gitignored）: `LINE_CHANNEL_ACCESS_TOKEN`、`LINE_USER_ID`、`CAPITAL_JPY` の 3 件
- **GitHub Secrets**: 上記 3 件と同名で登録済み（SECTION 9 で設定確認）
- **`pytest.ini`**: `network` マーカー定義済み
- **新規追加（SECTION 8）**: `LICENSE`（MIT）、`requirements_v3.md`、`sections_v3.md` を repo に同梱

## 8. 新セッション開始テンプレート

新チャットの最初のメッセージは以下のように送る：

> sector-leadlag プロジェクトの開発を引き継ぎます。前任セッションが SECTION 9 まで完了し、次は SECTION 10（GitHub Pages ダッシュボード `docs/index.html` + `docs/app.js` + `docs/style.css`）です。
>
> 【最初にやること】
> 1. リポジトリフォルダ `/Users/tamairyoga/Desktop/MacBook Pro/システム開発/sector-leadlag` へのアクセス権限を取得（request_cowork_directory）
> 2. そのフォルダ直下の `HANDOFF.md` を Read で全文読み、現状と運用ノウハウを把握
> 3. 既存 `docs/data.json` を Read で確認（SECTION 10 の入力スキーマ）
> 4. 添付の `requirements_v3.md`（§4 検証指標、§6.2 ファイル構成）と `sections_v3.md` SECTION 10 を全文読み込む
> 5. 既存 `src/universe.py` を確認（`JP_SECTOR_NAMES` をダッシュボードで二重定義する想定）
> 6. Mac 側 JupyterLab を経由した実機検証を行うため、Claude in Chrome の接続を確認（list_connected_browsers）
>
> 【絶対指示】
> - セクションを 1 つずつ実行。各セクションで「実装 → 動作確認 → Git コミット」を終えたら必ず一度停止
> - SECTION 10 は純フロントエンド作業。既存 `docs/data.json` のスキーマに厳密に合わせる
> - Plotly.js は CDN バージョン固定 (`https://cdn.plot.ly/plotly-2.27.0.min.js`)
> - localStorage キーは `slc:` プレフィックスで衝突回避
> - サンドボックスからの読み取り系 git は必ず `git --no-optional-locks ...` を使う（HANDOFF §6.1）
> - GHA auto-commit による origin 先行に注意（HANDOFF §6.13）。Mac 側 commit 前に `git fetch && git status` で確認
> - 個人的好み: 論理的思考、IT 系バックグラウンド前提、WEB システム開発（HTML & CSS / JavaScript / PHP）バックグラウンドあり
>
> 【次のタスク】
> SECTION 10 実装開始。準備が整い、状況把握できたら「準備完了。SECTION 10 を実装します」と私に報告してから着手してください。

新チャット起動時に添付するファイル（uploads）：

1. `requirements_v3.md`（repo にもあるが、UI 側にも置いておく方がアクセス早い）
2. `sections_v3.md`（同上）

（HANDOFF.md はリポジトリ内にあるので添付不要、フォルダ権限取得後に Read で読まれる）

新チャット開始前の Mac 側準備：

```bash
cd "/Users/tamairyoga/Desktop/MacBook Pro/システム開発/sector-leadlag"
source venv/bin/activate
jupyter lab --port=8889 --no-browser
```

起動後の token 付き URL を新セッションに貼って渡す。

## 9. ユーザー情報

- 名前: Ryoga（取締役、WEB システム開発バックグラウンド：HTML & CSS / JavaScript / PHP、論理的思考を好む）
- メール: r.t.mrs4392@gmail.com
- 環境: macOS、Chrome、Python 3.11.15
- LINE Bot: SECTION 6 で実装・動作確認完了、SECTION 9 で GHA から実機 LINE 受信確認済
- 投資運用想定額: `.env` および GitHub Secrets に `CAPITAL_JPY` 登録済（既定 5,000,000 が fallback）
- GitHub Pages: SECTION 10 完了後に Settings → Pages → Source = main /docs で公開を有効化する手動作業が残る
