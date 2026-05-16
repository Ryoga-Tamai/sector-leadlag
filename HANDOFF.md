# 引き継ぎ書 — sector-leadlag プロジェクト

**目的**: 新しい Cowork チャットでこのプロジェクトの開発を継続するための引き継ぎ。
**最終更新**: 2026-05-16（SECTION 6 完了時点）

---

## 1. プロジェクト全体像

- **要件定義書**: `requirements_v3.md`（v3.0、Opus 4.7 再定義版） — 新セッション開始時に添付する
- **開発手順書**: `sections_v3.md`（SECTION 1.5 以降） — 同上
- **対象論文**: 中川他 (2025)「部分空間正則化付き主成分分析を用いた日米業種リードラグ投資戦略」
- **ユニバース**: **26 銘柄固定**（米国 9 + 日本 17、XLC・XLRE 除外）
- **実行環境**: GitHub Actions（無料）、ローカル Python 3.11 venv、yfinance、LINE Bot

## 2. ユーザーからの絶対指示（厳守）

1. **セクションを 1 つずつ実行**。SECTION 7、8、… の順で進める
2. 各セクションで「実装 → 動作確認 → Git コミット」を終えたら **必ず一度停止** してユーザー確認を待つ
3. 複数セクションを連続で進めない
4. **不合格条件があるセクションでは合格まで次に進まない**（要件定義書 §4 系列）
5. SECTION 7 では SECTION 3〜6 で構築した同一ロジックを使うこと（とくに index 規約は SECTION 2C 互換を維持）

## 3. 現在の進捗（2026-05-16 時点）

| Section | 状態 | Git Commit |
|---|---|---|
| 0, 1 | ✅ 完了 | コミット済み |
| 1.5 | ✅ 完了 | `4c1f103 Section 1.5: Migrate to Python 3.11, extract universe module (26-ticker)` |
| 2A〜2E | ✅ 完了 | `7d5d118` 〜 `2c9c40a` |
| 3 | ✅ 完了 | `c474bb3 Section 3: Implement returns module and production data loader` |
| 4 | ✅ 完了 | `9321ce8 Section 4: Implement signal generation (consistent with Section 2 backtest)` |
| 5 | ✅ 完了 | `2aa2f80 Section 5: Implement lot calculator` |
| **6** | **✅ 完了** | **`76141a1 Section 6: Implement LINE notifier`** |
| **7** | **🔜 次に着手** | メインスクリプト統合（`src/main.py`） |
| 8〜11 | 未着手 | — |

## 4. SECTION 3〜6 の実装サマリと検証結果

### SECTION 3（データローダー本番化）
- `src/returns.py`: `compute_cc_returns`（`pct_change(fill_method=None)`）、`compute_oc_returns`（同一日 Close/Open − 1）
- `src/data_loader.py`: `fetch_prices(start, end, tickers, cache_path)`（yfinance auto_adjust=True、Open/Close 両方、共通営業日インターセクション、staleness 両端 7d、3 回指数バックオフ・リトライ）、`get_common_calendar`
- 検証：実データ `data/cache_prices.csv` での Notebook セル 6・7 との parity が `close_df`・`open_df`・`cc_returns`・`oc_returns_jp` の 4 系列で完全一致（`values_eq=True`）

### SECTION 4（シグナル生成）
- `src/signal_generator.py`: `SignalConfig`（dataclass、`L=60, K=3, λ=0.9, q=0.3`）、`generate_signal(open_df, close_df, target_date, C0, config)`、`load_prior_correlation(path)`
- `scripts/check_signal.py`（CLI、`--target-date`、`--lookback-days`、`--cache-path`、`--prior-path`）
- **最重要保証**：`test_generate_signal_matches_backtest` で Notebook セル 11 のループ本体と bit-identical（合成データ 4 t-値、実データ 4 日付の両方で確認）
- 副次 bug-fix：`compute_cc_returns` を `fill_method=None` 明示（クリーン入力では legacy default と同一出力。SECTION 3 parity 維持）

### SECTION 5（ロット計算）
- `src/lot_calculator.py`: `calculate_lots(capital, long, short, prices, unit_size=10)`、`fetch_latest_prices(tickers)`（`yf.Ticker(tk).fast_info.last_price`）
- 配分：`target = capital * 0.5 / N`、`shares = floor(target/price)`、`lots = shares // unit_size`、戻り値に `total_gross_exposure` と `cash_remaining`

### SECTION 6（LINE 通知）
- `src/line_notifier.py`: `format_signal_message`（業種名・lots・factor scores・exposure）、`send_line_message`（POST /v2/bot/message/push、10s timeout、never-throw、4xx/network-error/timeout で `False`）、`send_error_notification`（JST タイムスタンプ envelope、body は 4700 chars で truncate）
- `scripts/test_line_send.py`: `.env` の `LINE_CHANNEL_ACCESS_TOKEN` と `LINE_USER_ID` を読み、canned 送信または `--with-signal` で実シグナル全パイプライン送信

### 全体テストカウント（SECTION 6 完了時点、Mac venv）
- オフライン: 73 件 PASS（test_data_loader 15、test_line_notifier 15、test_lot_calculator 12、test_pca_engine 8、test_returns 9、test_signal_generator 14）
- network: 5 件 PASS（fetch_prices XLK、fetch_latest_prices XLK・1618.T、send_line_message_invalid_token、ほか）

## 5. SECTION 7 実装の注意（次セッション最重要）

要件定義書 v3 §3、sections_v3.md SECTION 7 に従って `src/main.py` を実装：

### 処理フロー
1. `dotenv.load_dotenv()` で環境変数読み込み：`LINE_CHANNEL_ACCESS_TOKEN`、`LINE_USER_ID`、`CAPITAL_JPY`
2. データ取得：過去 90 営業日 + バッファ。`open_df, close_df = fetch_prices(start, end, ALL_TICKERS, cache_path='data/cache_prices.csv')`
3. 事前相関行列：`C_full = load_prior_correlation('data/prior/C_full.npy')`、`C0 = build_target_correlation(V0, C_full)`
4. シグナル生成：`target_date = close_df.index[-1]`、`sig = generate_signal(...)`
5. ロット計算：`prices = fetch_latest_prices(sig['long_basket'] + sig['short_basket'])`、`lots = calculate_lots(CAPITAL_JPY, ...)`
6. LINE 通知：`msg = format_signal_message(sig, lots, CAPITAL_JPY)`、`send_line_message(msg, token, user_id)`
7. 結果保存：
   - `data/signals/{YYYY-MM-DD}.csv`（date, ticker, score, rank, position, suggested_lots の 17 行 + 9 行 = 必要に応じて構造設計）
   - `docs/data.json`（`{"last_updated", "current_signal", "history": [...直近100営業日...]}`、`history` は `data/signals/*.csv` を集約）
8. 各ステップで例外時は `send_error_notification(...)` で LINE 通知し、例外を再 raise（GitHub Actions ジョブも失敗扱い）

### 重要設計指針
- **`src/main.py` は orchestrator のみ**。ビジネスロジックは既存モジュールに委譲。
- **ログは `print` で stdout** に出す（GitHub Actions のログに残るため）。例外時は `traceback.format_exc()` を `send_error_notification` に渡す。
- **冪等性**：同日 2 回実行で同名 CSV 上書き、`docs/data.json` も上書き。GitHub Actions の `[skip ci]` 自動コミット連携を見据える。
- **テスト**：`tests/test_main.py` で `main()` を呼ぶ E2E をモック（`unittest.mock.patch`）して、各ステップが順番に呼ばれることを検証。`send_line_message` をモックすれば LINE 実送信なしで完走可能。

### 既存モジュールの import 規約
```python
from src.data_loader import fetch_prices
from src.lot_calculator import calculate_lots, fetch_latest_prices
from src.line_notifier import format_signal_message, send_line_message, send_error_notification
from src.pca_engine import build_prior_subspace, build_target_correlation
from src.signal_generator import SignalConfig, generate_signal, load_prior_correlation
from src.universe import ALL_TICKERS, N_JP, N_US, get_universe_masks
```

## 6. 既知の運用ノウハウ・落とし穴

### 6.1 `.git/index.lock` 残留問題（重要）

サンドボックスから git 読み取り操作を実行すると、マウント権限の問題で `.git/index.lock` が unlink できず残留することがある。Mac 側 `git add` / `git commit` が `fatal: Unable to create '.git/index.lock'` で失敗する。

**対処**:
- サンドボックス側の読み取り系 git コマンドは必ず `git --no-optional-locks ...` を使用
  - `git --no-optional-locks status`
  - `git --no-optional-locks log --oneline -5`
  - `git --no-optional-locks diff --stat <file>`（`--stat` は非オプション引数より前）
- `git show HEAD:path` は lock を取らないのでそのまま使える
- それでも lock が残ったら Mac 側で `rm -f .git/index.lock`（事前に `ps aux | grep git` で並行 git プロセスが無いことを確認）
- **commit / push は Mac 側 JupyterLab ターミナルから実行する** のが安全（HANDOFF §6.6）

### 6.2 サンドボックスからの書き込み制限

- `git checkout HEAD -- path` → サンドボックスから実行すると "Operation not permitted" でファイル unlink 失敗する
- 代わりに `python3 -c "import subprocess; open(path,'w').write(subprocess.check_output(['git','show','HEAD:'+path]).decode())"` で上書き
- `rm` も権限不足で失敗することがある → Mac 側で削除

### 6.3 `data/cache_prices.csv` のドリフトと commit 戦略

- HANDOFF §7（旧 §6.4）：`data/cache_prices.csv` は **コミット非対象推奨**（要件定義書 §3.4）。.gitignore に追加するのが本来。現状は tracking 済み
- `scripts/check_signal.py` や `scripts/test_line_send.py --with-signal` を実行すると cache が再書き込みされ、byte 単位の差分が出る（中身は実質同じ）
- SECTION 3〜6 のコミットでは、毎回 `git checkout HEAD -- data/cache_prices.csv` で巻き戻してから `git add` する習慣を徹底済み

### 6.4 Notebook の編集パターン（SECTION 2 時代の遺産）

- 既存セルを保ったまま末尾追加する `notebooks/append_section_NX.py` パターンを使う
- 冪等化のため、フィルタはセルの先頭行（`startswith`）で判定する：

  ```python
  first_line = src.splitlines()[0] if src else ""
  if first_line.startswith("# SECTION NX —") or first_line.startswith("## セル N: タイトル"):
      continue
  ```

  **悪い例**: `"SECTION 2E" in src` のような部分一致 — 2D の verdict セル内の `print("...proceed to SECTION 2E / 3")` に誤マッチして 2D verdict を削除してしまった事故あり
- f-string で `\n` を triple-quoted 文字列内に書くと、Python パーサーが実改行に展開して syntax error → `print("")` で空行を出す or `\\n` でエスケープ
- nbconvert 用に各セルに UUID が必要：`{"id": uuid.uuid4().hex[:8]}` を `_code_cell` / `_markdown_cell` ヘルパー内で設定すること

### 6.5 サンドボックス Python と Mac venv の使い分け

- **サンドボックス側 yfinance はプロキシブロック**（403）。本番データ取得は Mac 側 jupyter のみ
- サンドボックスの `python3` は 3.10、追加依存は `pip install <pkg> --break-system-packages`
- Mac 側 venv は Python 3.11.15（broken symlink でサンドボックスから直接実行は不可、Mac 側ターミナルで `source venv/bin/activate` 経由）
- ロジック検証はサンドボックスで完結、network 必要な実機検証は Mac 側で実行
- **typical workflow**：
  1. サンドボックスで Read/Write/Edit → `pip install` → `pytest -m "not network"`
  2. Mac venv 起動 → `pytest tests/ -v`（network 込み）
  3. Mac venv で実機スモーク（`scripts/check_signal.py` や `scripts/test_line_send.py`）
  4. Mac 側 JupyterLab ターミナルから `git commit && git push`

### 6.6 JupyterLab 連携（Claude in Chrome 経由）

- Mac 側で起動: `cd <project> && source venv/bin/activate && jupyter lab --port=8889 --no-browser`
- 起動後、token 付き URL（`http://127.0.0.1:8889/lab?token=...`）を新セッションに貼ってもらう
- 既に動いている場合は `jupyter server list` で URL 再取得可能
- Claude in Chrome で `mcp__Claude_in_Chrome__navigate` → File menu の `+` → Other > Terminal で JupyterLab ターミナルを開く
- **そこから直接 `pytest`、`python scripts/...`、`git ...` を実行する**のが SECTION 3 以降の定番フロー
- 私（サンドボックス側 Claude）が `notebooks/01_paper_replication.ipynb` をディスク上で書き換えた直後は、ブラウザを `cmd+r` でリロードしないと反映されない（JupyterLab がメモリ内の旧版を auto-save で書き戻すリスク）

### 6.7 JupyterLab UI 操作の Tips

- メニュー位置（929×775 viewport 想定）: File/Edit/View/Run/Kernel/Tabs/Settings/Help = X 座標 53/93/137/181/230/282/339/396、Y=14
- Run メニューの「Run Selected Cell and All Below」: 開いた直後の Y=180 付近
- Kernel メニューの「Restart Kernel and Run All Cells...」: 開いた直後の Y=147 付近
- 確認ダイアログの「Restart」赤ボタン: 視覚で位置確認推奨（画面サイズ依存）
- 「Run Selected Cell and All Below」が止まる場合は、セルが syntax error 等で失敗している可能性 → `.jp-OutputArea-error` の有無を JS でチェック
- セルの実行状態を JS で取得:
  ```js
  Array.from(document.querySelectorAll('.jp-Cell')).map(c => (c.querySelector('.jp-InputPrompt')||{}).textContent)
  ```
  → `[N]:` 完了、`[*]:` 実行中、`[ ]:` 未実行、`""` markdown
- ターミナル開く操作：file browser の「+」ボタンで Launcher → "Other" セクション → "Terminal" をクリック
- `mcp__Claude_in_Chrome__computer.wait` は最大 10 秒。長時間処理を待つときは 10 秒の wait を複数回に分ける

### 6.8 Chrome 拡張のテキスト出力フィルタ

- 一部の出力テキストが `[BLOCKED: Cookie/query string data]` で取れないことがある（URL や token 風文字列が含まれる場合）
- このときは Notebook を Mac 側で `cmd+s` 保存 → サンドボックスから `.ipynb` を読み取って outputs を抽出する迂回路を使う
- nbconvert で HTML 化して読み取る方法もあり：`python3 -m nbconvert --to html ... && file://` だが file:// は Claude in Chrome で開けない制約あり

### 6.9 複数ブラウザ接続時の混同回避

- セッション途中で別 OS のブラウザ拡張が接続される場合あり（list_connected_browsers で複数表示される）
- 必ず元々使っていた deviceId を `select_browser` で指定し直す習慣にする
- 不明なブラウザが現れたらユーザに確認

### 6.10 `pd.DataFrame.pct_change` の `fill_method`

- pandas のデフォルト `fill_method='pad'` は NaN を前方補完してしまうため、SECTION 4 の NaN 検出契約に支障あり
- `src/returns.py` の `compute_cc_returns` は `fill_method=None` を明示
- クリーン入力（共通営業日インターセクション後）では出力が legacy default と完全一致なので SECTION 3 parity は保持

### 6.11 LINE Messaging API のセットアップ済み事項

- LINE Developers Console でプロバイダー＋ Messaging API チャネル作成済み
- 長期チャネルアクセストークン（有効期限なし、1 チャネル 1 個）発行済み
- ユーザー自身を Bot の友だちに追加済み、`U` で始まる 33 文字の `LINE_USER_ID` 取得済み
- `.env`（リポジトリ直下、gitignored）に `LINE_CHANNEL_ACCESS_TOKEN` と `LINE_USER_ID` 記入済み
- 動作確認済み：
  - `python scripts/test_line_send.py` → canned 通知が LINE に届く（200 OK）
  - `python scripts/test_line_send.py --with-signal` → 実シグナル全体が LINE に届く（200 OK）
- 漏洩疑い時の対処：LINE Developers Console の「再発行」ボタンで古いトークン無効化、`.env` 書き換え

### 6.12 `data/prior/C_full.npy` のコミット非対象問題

- HANDOFF §7：`data/prior/C_full.npy`（5.5 KB）も Notebook の再実行で byte 差分が出ることがある（中身は実質同じ）
- SECTION 3〜6 のコミット時は `data/cache_prices.csv` のみ revert で済んでいたが、SECTION 7 で `data/signals/*.csv` や `docs/data.json` を初めて生成・コミットすることになるので、追加の運用ルール（どのファイルをコミット、どれを除外）を SECTION 7 の中で決める

## 7. 作業環境

- **リポジトリパス**: `/Users/tamairyoga/Desktop/MacBook Pro/システム開発/sector-leadlag`
- **GitHub remote**: `https://github.com/Ryoga-Tamai/sector-leadlag.git`
- **venv**: 同フォルダ内 `venv/`（Python 3.11.15）
- **Notebook**: `notebooks/01_paper_replication.ipynb`（SECTION 2E まで完了、SECTION 3 以降は本番モジュールに移行）
- **キャッシュ**: `data/cache_prices.csv`（3.5 MB、コミット非対象推奨だが現状 tracking 済み）
- **事前相関**: `data/prior/C_full.npy`（5.5 KB、コミット推奨）
- **ヘルパースクリプト**:
  - `notebooks/append_section_2d.py`、`notebooks/append_section_2e.py`（コミット済み、SECTION 2 用）
  - `scripts/check_signal.py`（SECTION 4 用、コミット済み）
  - `scripts/test_line_send.py`（SECTION 6 用、コミット済み）
- **検証 HTML**: `01_paper_replication_2D.html` などは .gitignore で除外済み
- **テスト一覧**:
  - `tests/test_pca_engine.py`（SECTION 1）
  - `tests/test_returns.py`、`tests/test_data_loader.py`（SECTION 3）
  - `tests/test_signal_generator.py`（SECTION 4）
  - `tests/test_lot_calculator.py`（SECTION 5）
  - `tests/test_line_notifier.py`（SECTION 6）
- **`.env`**（gitignored）: `LINE_CHANNEL_ACCESS_TOKEN`、`LINE_USER_ID`、（SECTION 7 で `CAPITAL_JPY` も追加予定）
- **`pytest.ini`**: `network` マーカー定義済み（SECTION 3 で追加）

## 8. 新セッション開始テンプレート

新チャットの最初のメッセージは以下のように送る：

> sector-leadlag プロジェクトの開発を引き継ぎます。前任セッションが SECTION 6 まで完了し、次は SECTION 7（メインスクリプト統合 `src/main.py`）です。
>
> 【最初にやること】
> 1. リポジトリフォルダ `/Users/tamairyoga/Desktop/MacBook Pro/システム開発/sector-leadlag` へのアクセス権限を取得（request_cowork_directory）
> 2. そのフォルダ直下の `HANDOFF.md` を Read で全文読み、現状と運用ノウハウを把握
> 3. 添付の `requirements_v3.md` と `sections_v3.md` を全文読み込む
> 4. 既存ファイル `src/universe.py`、`src/pca_engine.py`、`src/data_loader.py`、`src/returns.py`、`src/signal_generator.py`、`src/lot_calculator.py`、`src/line_notifier.py` を確認
> 5. Mac 側 JupyterLab を経由した実機検証を行うため、Claude in Chrome の接続を確認（list_connected_browsers）
>
> 【絶対指示】
> - セクションを 1 つずつ実行。各セクションで「実装 → 動作確認 → Git コミット」を終えたら必ず一度停止
> - 複数セクションを連続で進めない
> - SECTION 7 は `src/main.py` の orchestrator 実装。ビジネスロジックは既存モジュールに委譲し、`src/main.py` は連結とエラーハンドリングのみに集中
> - サンドボックスからの読み取り系 git は必ず `git --no-optional-locks ...` を使う（HANDOFF §6.1）
> - 個人的好み: 論理的思考、IT 系バックグラウンド前提
>
> 【次のタスク】
> SECTION 7 実装開始。準備が整い、状況把握できたら「準備完了。SECTION 7 を実装します」と私に報告してから着手してください。

新チャット起動時に添付するファイル（uploads）：

1. `requirements_v3.md`
2. `sections_v3.md`

（HANDOFF.md はリポジトリ内にあるので添付不要、フォルダ権限取得後に Read で読まれる）

新チャット開始前の Mac 側準備：

```bash
cd "/Users/tamairyoga/Desktop/MacBook Pro/システム開発/sector-leadlag"
source venv/bin/activate
jupyter lab --port=8889 --no-browser
```

起動後の token 付き URL を新セッションに貼って渡す。

## 9. ユーザー情報

- 名前: Ryoga（取締役、WEB システム開発バックグラウンド、論理的思考を好む）
- メール: r.t.mrs4392@gmail.com
- 環境: macOS、Chrome、Python 3.11.15
- LINE Bot: SECTION 6 で実装・動作確認完了済み（`.env` に token と userId 設定済み）
- 投資運用想定額: SECTION 7 で `CAPITAL_JPY` 環境変数として `.env` に追加する想定（既定 5,000,000）
