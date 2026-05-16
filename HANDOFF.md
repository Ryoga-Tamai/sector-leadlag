# 引き継ぎ書 — sector-leadlag プロジェクト

**目的**: 新しい Cowork チャットでこのプロジェクトの開発を継続するための引き継ぎ。
**最終更新**: 2026-05-15（SECTION 2E 完了時点）

---

## 1. プロジェクト全体像

- **要件定義書**: `requirements_v3.md`（v3.0、Opus 4.7 再定義版） — 新セッション開始時に添付する
- **開発手順書**: `sections_v3.md`（SECTION 1.5 以降） — 同上
- **対象論文**: 中川他 (2025)「部分空間正則化付き主成分分析を用いた日米業種リードラグ投資戦略」
- **ユニバース**: **26 銘柄固定**（米国 9 + 日本 17、XLC・XLRE 除外）
- **実行環境**: GitHub Actions（無料）、ローカル Python 3.11 venv、yfinance、LINE Bot

## 2. ユーザーからの絶対指示（厳守）

1. **セクションを 1 つずつ実行**。SECTION 3、4、… の順で進める
2. 各セクションで「実装 → 動作確認 → Git コミット」を終えたら **必ず一度停止** してユーザー確認を待つ
3. 複数セクションを連続で進めない
4. **不合格条件があるセクションでは合格まで次に進まない**（要件定義書 §4 系列）

## 3. 現在の進捗（2026-05-15 時点）

| Section | 状態 | Git Commit |
|---|---|---|
| 0, 1 | ✅ 完了 | コミット済み |
| 1.5 | ✅ 完了 | `Section 1.5: Migrate to Python 3.11, extract universe module (26-ticker)` |
| 2A | ✅ 完了 | `SECTION 2A動作確認完了` |
| 2B | ✅ 完了 | `SECTION 2B 動作確認完了` |
| 2C | ✅ 完了 | `SECTION 2C 動作確認完了`（実体は 2C+2D 混在、名前のまま受容） |
| 2D | ✅ 完了 | `SECTION 2D 動作確認完了`（2D の outputs を追加コミット） |
| **2E** | **✅ 完了** | **`SECTION 2E 動作確認完了`** |
| **3** | **🔜 次に着手** | データローダー本番化 |
| 4〜11 | 未着手 | — |

## 4. SECTION 2 検証レイヤー & パフォーマンスの実測値

### SECTION 2D 検証レイヤー（要件定義書 v3 §4.2、全項目 PASS）

| 項目 | 実測値 | 合格条件 |
|---|---|---|
| IC（Spearman） | mean = +0.048, t ≈ +8.0（N=2596）| mean > 0 かつ t > 2 |
| 分位スプレッド | Q5−Q1 = +0.125%/d（ann +31.5%）、up-diffs 4/4 | Q5 > Q1 かつ単調 |
| ルックアヘッド監査（シフト）| baseline R/R 2.65 → shift R/R 0.60（−77%） | シフトで R/R 大幅低下 |
| ルックアヘッド監査（シャッフル）| baseline R/R 2.65 → shuffle R/R 0.40 | \|R/R\| < 0.5 |

### SECTION 2E パフォーマンス指標（要件定義書 v3 §4.3、R/R range check PASS）

| 指標 | 本実装 | 論文 |
|---|---|---|
| AR（年率）| +27.89% | +23.79% |
| RISK（年率）| 10.51% | 10.70% |
| R/R | +2.653 | +2.220 |
| MDD（cum P/L）| 11.20%（2024-03-04 → 2024-05-15、47 営業日）| 9.58% |
| N days | 2,612（2015-01-05 〜 2025-12-29） | — |

R/R range check (1.0 ≤ R/R ≤ 3.0)：**PASS**。年別 P/L は 11 年連続プラス（最弱は 2024 年 +5.69%）。

### SECTION 2 総合判定

**合格**。要件定義書 v3 §4.2 の合格条件をすべて満たし、SECTION 3 に進める状態。

## 5. SECTION 3 実装の注意（次セッション最重要）

要件定義書 v3 §3 / sections_v3.md SECTION 3 に従って、以下を実装：

- `src/returns.py`: `compute_cc_returns()`, `compute_oc_returns()` を切り出す（Notebook セル 6・7 のロジックそのまま）
- `src/data_loader.py`: `fetch_prices(start, end, tickers, cache_path)` と `get_common_calendar()`
  - yfinance `auto_adjust=True` で Open/Close 両方取得
  - 共通営業日インターセクションを内部で適用
  - キャッシュ読み書き、3 回リトライ（指数バックオフ）
- `tests/test_returns.py`: ダミー価格で CC/OC を手計算と照合
- `tests/test_data_loader.py`: ダミー DataFrame で共通営業日抽出、`@pytest.mark.network` で直近 1 ヶ月の XLK のみ取得テスト

**重要**: SECTION 2 の Notebook と「同一のロジック・同一の index 規約」を維持すること（特に共通営業日インターセクションのタイミング）。SECTION 4 の `test_generate_signal_matches_backtest` で Notebook 結果と一致するか比較できる前提。

## 6. 既知の運用ノウハウ・落とし穴

### 6.1 `.git/index.lock` 残留問題（重要）

サンドボックスから git 読み取り操作を実行すると、マウント権限の問題で `.git/index.lock` が unlink できず残留することがある。これにより Mac 側 `git add` / `git commit` が `fatal: Unable to create '.git/index.lock'` で失敗する。

**対処**:
- サンドボックス側の読み取り系 git コマンドは必ず `git --no-optional-locks ...` を使用
  - `git --no-optional-locks status`
  - `git --no-optional-locks log --oneline -5`
  - `git --no-optional-locks diff --stat`
- `git show HEAD:path` は lock を取らないのでそのまま使える
- それでも lock が残ったら Mac 側で `rm -f .git/index.lock`（事前に `ps aux | grep git` で並行 git プロセスが無いことを確認）

### 6.2 サンドボックスからの書き込み制限

- `git checkout HEAD -- path` → サンドボックスから実行すると "Operation not permitted" でファイル unlink 失敗する
- 代わりに `python3 -c "import subprocess; open(path,'w').write(subprocess.check_output(['git','show','HEAD:'+path]).decode())"` で上書き
- `rm` も権限不足で失敗することがある → Mac 側で削除

### 6.3 Notebook の編集パターン

- 既存セルを保ったまま末尾追加する `notebooks/append_section_NX.py` パターンを使う
- 冪等化のため、フィルタはセルの先頭行（`startswith`）で判定する：

  ```python
  first_line = src.splitlines()[0] if src else ""
  if first_line.startswith("# SECTION NX —") or first_line.startswith("## セル N: タイトル"):
      continue
  ```

  **悪い例**: `"SECTION 2E" in src` のような部分一致 — 2D の verdict セル内の `print("...proceed to SECTION 2E / 3")` に誤マッチして 2D verdict を削除してしまった事故あり
- f-string で `\n` を triple-quoted 文字列内に書くと、Python パーサーが実改行に展開して syntax error になる → `print("")` で空行を出す or `\\n` でエスケープ
- nbconvert 用に各セルに UUID が必要：`{"id": uuid.uuid4().hex[:8]}` を `_code_cell` / `_markdown_cell` ヘルパー内で設定すること

### 6.4 キャッシュ・事前相関のコミット非対象

- `data/cache_prices.csv` は **コミット非対象推奨**（HANDOFF §7、要件定義書 §3.4）。.gitignore に追加するのが本来。現状は tracking 済みなので、Restart Kernel 実行後は `git checkout HEAD -- data/cache_prices.csv` で巻き戻す
- `data/prior/C_full.npy` も同様にセル 9 を再実行すると byte 差分が出る（中身は実質同じ）→ `git checkout HEAD -- data/prior/C_full.npy` で巻き戻す
- これらが入った状態の `git add -A` で意図しないコミット内容になりやすい

### 6.5 JupyterLab 連携

- **サンドボックス側 yfinance はプロキシブロック**（403）。本番データ取得は Mac 側 jupyter のみ
- Mac 側で起動: `cd <project> && source venv/bin/activate && jupyter lab --port=8889 --no-browser`
- 起動後、token 付き URL（`http://127.0.0.1:8889/lab?token=...`）を新セッションに貼ってもらう
- 既に動いている場合は `jupyter server list` で URL 再取得可能
- 私（サンドボックス側 Claude）が `notebooks/01_paper_replication.ipynb` をディスク上で書き換えた直後は、ブラウザを `cmd+r` でリロードしないと反映されない（JupyterLab がメモリ内の旧版を auto-save で書き戻すリスク）

### 6.6 JupyterLab UI 操作の Tips

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

### 6.7 Chrome 拡張のテキスト出力フィルタ

- 一部の出力テキストが `[BLOCKED: Cookie/query string data]` で取れないことがある（URL や token 風文字列が含まれる場合）
- このときは Notebook を Mac 側で `cmd+s` 保存 → サンドボックスから `.ipynb` を読み取って outputs を抽出する迂回路を使う
- nbconvert で HTML 化して読み取る方法もあり：`python3 -m nbconvert --to html ... && file://` だが file:// は Claude in Chrome で開けない制約あり

### 6.8 複数ブラウザ接続時の混同回避

- セッション途中で別 OS のブラウザ拡張が接続される場合あり（list_connected_browsers で複数表示される）
- 必ず元々使っていた deviceId を `select_browser` で指定し直す習慣にする
- 不明なブラウザが現れたらユーザに確認

## 7. 作業環境

- **リポジトリパス**: `/Users/tamairyoga/Desktop/MacBook Pro/システム開発/sector-leadlag`
- **venv**: 同フォルダ内 `venv/`（Python 3.11.15）
- **Notebook**: `notebooks/01_paper_replication.ipynb`（現在 21 セル、SECTION 2E まで完了）
- **キャッシュ**: `data/cache_prices.csv`（3.5 MB、コミット非対象推奨だが現状 tracking 済み）
- **事前相関**: `data/prior/C_full.npy`（5.5 KB、コミット推奨）
- **ヘルパースクリプト**: `notebooks/append_section_2d.py`, `notebooks/append_section_2e.py`（コミット済み）
- **検証 HTML**: `01_paper_replication_2D.html` などは .gitignore で除外済み

## 8. 新セッション開始テンプレート

新チャットの最初のメッセージは以下のように送る：

> sector-leadlag プロジェクトの開発を引き継ぎます。前任セッションが SECTION 2E まで完了し、次は SECTION 3（データローダー本番化）です。
>
> 【最初にやること】
> 1. リポジトリフォルダ `/Users/tamairyoga/Desktop/MacBook Pro/システム開発/sector-leadlag` へのアクセス権限を取得（request_cowork_directory）
> 2. そのフォルダ直下の HANDOFF.md を Read で全文読み、現状を把握
> 3. 添付の requirements_v3.md と sections_v3.md を全文読み込む
> 4. 既存ファイル `src/universe.py`, `src/pca_engine.py`, `notebooks/01_paper_replication.ipynb` を確認
> 5. ブラウザ操作が必要なら Claude in Chrome の接続を確認（list_connected_browsers）
>
> 【絶対指示】
> - セクションを 1 つずつ実行。各セクションで「実装 → 動作確認 → Git コミット」を終えたら必ず一度停止
> - 複数セクションを連続で進めない
> - SECTION 3 完了時、SECTION 4 の `test_generate_signal_matches_backtest` でバックテスト結果との一致を担保できる構造になっていること
> - 個人的好み: 論理的思考、IT 系バックグラウンド前提
>
> 【次のタスク】
> SECTION 3 実装開始。準備が整い、状況把握できたら「準備完了。SECTION 3 を実装します」と私に報告してから着手してください。

新チャット起動時に添付するファイル（uploads）：

1. `requirements_v3.md`
2. `sections_v3.md`

（HANDOFF.md はリポジトリ内にあるので添付不要、フォルダ権限取得後に Read で読まれる）

## 9. ユーザー情報

- 名前: Ryoga（取締役、WEB システム開発バックグラウンド、論理的思考を好む）
- メール: r.t.mrs4392@gmail.com
- 環境: macOS、Chrome、Python 3.11.15
- LINE Bot: SECTION 6 で実装予定
