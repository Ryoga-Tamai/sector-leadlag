# 日米業種リードラグ投資ツール

米国市場の業種パフォーマンスが日本市場の対応業種に先行する「リードラグ効果」を定量的に検出し、翌日の日本株業種 ETF への投資シグナルを生成するツールです。yfinance で米国・日本の業種 ETF データを取得し、クロス相関分析によってラグを推定、バックテストで有効性を検証した上で LINE 通知でシグナルを配信します。

## 開発手順概要

1. **環境構築** — Python 仮想環境を作成し依存パッケージをインストール
2. **データ取得** (`src/data_fetcher.py`) — yfinance で米日業種 ETF の日次リターンを取得
3. **シグナル生成** (`src/signal_engine.py`) — クロス相関分析でリードラグを推定しシグナルを計算
4. **バックテスト** (`src/backtester.py`) — シグナルの収益性・シャープレシオ等を検証
5. **通知** (`src/notifier.py`) — LINE Messaging API でシグナルを配信
6. **自動化** (`.github/workflows/`) — GitHub Actions で毎営業日夜に自動実行

## ディレクトリ構成

```
sector-leadlag/
├── src/            # メインロジック
├── tests/          # pytest テスト
├── notebooks/      # 探索的分析用 Jupyter ノートブック
├── data/
│   ├── signals/    # 生成されたシグナル履歴
│   ├── performance/# バックテスト結果
│   └── prior/      # ベイズ更新用事前分布パラメータ
└── docs/           # 設計ドキュメント
```
