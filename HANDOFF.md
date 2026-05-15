# 引き継ぎ書 — sector-leadlag プロジェクト

**目的**: 新しい Cowork チャットでこのプロジェクトの開発を継続するための引き継ぎ。

---

## 1. プロジェクト全体像

- **要件定義書**: `requirements_v3.md`（v3.0、Opus 4.7 再定義版） — 同フォルダに添付するか前任ユーザーから渡される
- **開発手順書**: `sections_v3.md`（SECTION 1.5 以降） — 同上
- **対象論文**: 中川他 (2025)「部分空間正則化付き主成分分析を用いた日米業種リードラグ投資戦略」
- **ユニバース**: **26 銘柄固定**（米国 9 + 日本 17、XLC・XLRE 除外）
- **実行環境**: GitHub Actions（無料）、ローカル Python 3.11 venv、yfinance、LINE Bot

## 2. ユーザーからの絶対指示（厳守）

1. **セクションを 1 つずつ実行**。SECTION 1.5、2A、2B、… の順で進める
2. 各セクションで「実装 → 動作確認 → Git コミット」を終えたら **必ず一度停止** してユーザー確認を待つ
3. 複数セクションを連続で進めない
4. **SECTION 2D の検証レイヤーが不合格の場合は、SECTION 3 に進まず停止**（要件定義書 §4.2）

## 3. 現在の進捗（2026-05-15 時点）

| Section | 状態 | Git Commit |
|---|---|---|
| 0, 1 | ✅ 完了 | コミット済み（前任の Sonnet が実施） |
| **1.5** | ✅ 完了 | `Section 1.5: Migrate to Python 3.11, extract universe module (26-ticker)` |
| **2A** | ✅ 完了 | `Section 2A: Implement data fetch & common business-day intersection` |
| **2B** | ✅ 完了 | `Section 2B: Add CC/OC return computations (CC=26 tickers, OC=JP 17)` |
| **2C** | ✅ 完了 | `Section 2C: Add C_full prior, V0/C0, and lookahead-safe backtest loop` |
| **2D** | 🔜 **次に着手** | 検証レイヤー（IC・分位スプレッド・ルックアヘッド監査） |
| 2E〜11 | 未着手 | — |

## 4. 重要な数値（SECTION 2C までの実測値）

- **共通営業日数**: 3,796（採用期間 2010-01-04 〜 2025-12-30）
- **事前期間 C_full**: 2010-01-05 〜 2014-12-30、1,182 行、shape (26, 26)、対角 1.0、off-diag [+0.011, +0.903]
- **バックテスト期間**: 2015-01-05 〜 2025-12-29、2,612 日
- **戦略指標（サンドボックス側ドライランの参考値、SECTION 2E で正式計算）**:
  - AR = 27.87%
  - RISK = 10.51%
  - **R/R = 2.651**（論文値 2.22、要件 §4.3 範囲 [1.0, 3.0] 内）

## 5. SECTION 2D 実装の注意（次セッション最重要）

- 要件定義書 §4 を厳密に実装
- 4 つの検証指標すべてを実装:
  1. **IC**: Spearman 順位相関、平均 IC が正 & t 値 > 2 で合格
  2. **分位スプレッド**: 5 分位、上位 > 下位 かつ単調
  3. **ルックアヘッド監査（シフト）**: signal を +1 ずらすと R/R 大幅低下が必要
  4. **ルックアヘッド監査（シャッフル）**: 銘柄方向ランダムシャッフルで R/R ≒ 0 が必要
- **R/R 2.65 という強い値は警戒材料**。ルックアヘッドバグが残っていれば +1 シフトで崩れないはず → セル 15（シフト監査）の結果を最優先で確認
- 不合格なら **SECTION 3 に進まず**、原因調査
  - 最有力候補: cell 12（バックテストループ）の standardize で誤って t の統計量を使っていないか再確認

## 6. 既知の警戒ポイント

| 項目 | 内容 | 対応 |
|---|---|---|
| 1629.T の CC > 50% | 商社・卸売で 2 日分、ETF 単独で異常値 | 要件 §3.3 で警告のみ。SECTION 2D の IC・分位がおかしくなったら最初に疑う |
| 日本 17 銘柄の連続 6 日 NaN | 日本側祝日連続（GW・年末年始）、構造的に正常 | 共通営業日インターセクションで除外済み。問題なし |
| C0 の off-diag max 1.000 | V0 が rank-3 で C0 を再構築するため一部ペアが完全相関に近づく | 構造的に正しい。バグではない |

## 7. 作業環境

- **リポジトリパス**: `/Users/tamairyoga/Desktop/MacBook Pro/システム開発/sector-leadlag`
- **venv**: 同フォルダ内 `venv/`（Python 3.11.15）
- **Notebook**: `notebooks/01_paper_replication.ipynb`（現在 12 セル、SECTION 2C まで完了）
- **キャッシュ**: `data/cache_prices.csv`（3.5 MB、26 銘柄 × 2010-2025、コミット非対象推奨）
- **事前相関**: `data/prior/C_full.npy`（5.5 KB、コミット推奨）

## 8. ツール運用ノウハウ（前任から）

- **サンドボックス側 yfinance はプロキシブロック**（403）。本番データ取得は Mac 側 jupyter のみ
- **Git コミットは Mac 側でユーザー手動**。サンドボックスからは `.git/index.lock` 権限がない
- **Notebook 編集**: 既存セルは保ったまま末尾追加する `append_section_2X.py` パターンを使う
- **ブラウザ操作**: Claude in Chrome 接続前提。Jupyter は **localhost:8889** で起動推奨（token はその都度確認）
- **JupyterLab UI 操作**:
  - メニュー Y 座標: File/Edit/View/Run/Kernel/Settings = (49/96/144/150/199/261, 12)
  - Run メニュー: `Run All Cells` (199, 244)、`Restart Kernel and Run All Cells...` (290, 146)
  - Restart 確認ダイアログ: Cancel (415, 311)、Restart (499, 311)
  - 実行状態確認: JS で `document.querySelectorAll('.jp-Cell')` → `.jp-InputPrompt` の textContent (`[N]:` = 完了、`[*]:` = 実行中、`[ ]:` = 未実行)
  - **注意**: Restart Kernel and Run All を実行しても新追加セルが queued ([ ]:) のままになることがある → その場合は普通に Run All Cells を再実行
- **トークンを URL に含めるとブラウザ拡張で JS 実行ブロック**: URL から token を除去して再ナビゲートしてから JS 実行

## 9. ユーザー情報

- 名前: Ryoga（取締役、WEB システム開発バックグラウンド、論理的思考を好む）
- メール: r.t.mrs4392@gmail.com
- LINE Bot: SECTION 6 で実装予定
