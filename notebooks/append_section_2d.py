"""Append SECTION 2D cells (validation layer) to 01_paper_replication.ipynb.

Idempotent: re-running removes previously appended SECTION 2D cells (identified
by the leading marker comment / heading) and re-appends fresh ones.

Requirements_v3.md §4 — Validation layer:
  Cell 13: Information Coefficient (IC) — Spearman, mean & t-stat
  Cell 14: Quintile spread (5 buckets, monotonicity)
  Cell 15: Look-ahead audit (shift signal by +1 day, recompute P/L)
  Cell 16: Look-ahead audit (shuffle signal across tickers, recompute P/L)
  Cell 17: Markdown verdict against §4.2 pass conditions
"""

from __future__ import annotations

import json
import os
import sys

NB_PATH = os.path.join(os.path.dirname(__file__), "01_paper_replication.ipynb")

# ---------------------------------------------------------------------------
# Cell sources (each is a list[str] suitable for the .ipynb "source" field)
# ---------------------------------------------------------------------------

CELL_13 = """# SECTION 2D — Cell 13: Information Coefficient (IC)
# 各営業日 t について、signal_t (17銘柄) と realized_oc[t+1] (17銘柄) の
# Spearman 順位相関を計算。全期間の IC 系列から平均・std・t値を算出する。
#
# 合格ライン (要件定義書 v3 §4.1):
#   - 平均 IC が正
#   - t 値 (mean / (std / sqrt(N))) > 2

# signal_df.index = date_t、realized_df.index = date_t1 (= t+1)
# 行は順序的に1:1対応している（同じバックテストループから生成）。
# 銘柄方向の順位相関なので、signal の値とリターンの値を行ごとに直接 spearmanr に渡す。
assert len(signal_df) == len(realized_df), "signal/realized length mismatch"
assert list(signal_df.columns) == list(realized_df.columns) == list(JP_TICKERS)

sig_arr = signal_df.to_numpy()        # (N, 17)
oc_arr  = realized_df.to_numpy()      # (N, 17)
N_BT = sig_arr.shape[0]

ic_values = np.empty(N_BT, dtype=float)
for i in range(N_BT):
    # 17 銘柄方向の Spearman 順位相関
    rho, _ = spearmanr(sig_arr[i], oc_arr[i])
    ic_values[i] = rho

# NaN 行（理論上は発生しないはずだが念のため）の除外
ic_clean = ic_values[~np.isnan(ic_values)]
ic_series = pd.Series(ic_values, index=signal_df.index, name="IC")

ic_mean = float(ic_clean.mean())
ic_std  = float(ic_clean.std(ddof=1))
ic_n    = int(ic_clean.size)
ic_t    = ic_mean / (ic_std / np.sqrt(ic_n)) if ic_std > 0 else np.nan

ic_pass_sign = ic_mean > 0.0
ic_pass_tval = ic_t > 2.0
ic_pass      = ic_pass_sign and ic_pass_tval

print(f"IC samples (non-NaN)  : {ic_n} / {N_BT}")
print(f"IC mean               : {ic_mean:+.6f}")
print(f"IC std  (ddof=1)      : {ic_std:.6f}")
print(f"IC t-stat (mean/SE)   : {ic_t:+.3f}    [pass: > 2]")
print(f"  pass (mean > 0)     : {ic_pass_sign}")
print(f"  pass (t  > 2)       : {ic_pass_tval}")
print(f"  → CELL 13 verdict   : {'PASS' if ic_pass else 'FAIL'}")

# 累積 IC の可視化（右肩上がりなら予測力が安定している）
fig, ax = plt.subplots(figsize=(10, 4))
ic_series.cumsum().plot(ax=ax, color="#1f77b4", linewidth=1.2)
ax.axhline(0, color="black", linewidth=0.6, linestyle="--")
ax.set_title(f"Cumulative IC (Spearman)  mean={ic_mean:+.4f}  t={ic_t:+.2f}  N={ic_n}")
ax.set_xlabel("date_t")
ax.set_ylabel("cum IC")
ax.grid(alpha=0.3)
plt.tight_layout()
plt.show()
"""

CELL_14 = """# SECTION 2D — Cell 14: Quintile spread
# 各日、signal_t で日本 17 銘柄を 5 分位に分割（rank-based、Q1 = 最低 〜 Q5 = 最高）。
# 各分位の平均翌日 OC リターンを全期間で集計し、単調性を確認する。
#
# 合格ライン (要件定義書 v3 §4.1):
#   - 上位分位 (Q5) > 下位分位 (Q1)
#   - 概ね単調（Q1 ≤ Q2 ≤ … ≤ Q5 が望ましい）

N_Q = 5
# 1 行 (=1 日) ごとに 17 銘柄を順位で 5 分位にビン分けする。
# scipy.stats.rankdata より numpy.argsort で十分（同値はランダム順だが影響は小さい）
# pandas.qcut を使うと境界の処理が分位サイズ非整数（17/5=3.4）でやや面倒なため、
# rank → floor((rank-1) / (17/5)) で安全にビン化する。
ranks = np.argsort(np.argsort(sig_arr, axis=1), axis=1)  # 0..16 ranks per row
bins  = np.minimum((ranks * N_Q) // sig_arr.shape[1], N_Q - 1)  # 0..N_Q-1

# 各分位の平均 OC リターン（全期間プール）
quintile_mean = np.empty(N_Q, dtype=float)
quintile_count = np.empty(N_Q, dtype=int)
for q in range(N_Q):
    mask = (bins == q)
    quintile_count[q] = int(mask.sum())
    quintile_mean[q]  = float(oc_arr[mask].mean()) if mask.any() else np.nan

# 単調性チェック
spread_q5_q1 = float(quintile_mean[N_Q - 1] - quintile_mean[0])
diffs        = np.diff(quintile_mean)
n_up         = int((diffs > 0).sum())
mono_pass    = (spread_q5_q1 > 0.0) and (n_up >= 3)  # 4 差分のうち 3 以上が正なら「概ね単調」

# 年率換算（参考表示用）：分位リターンは「ロング/ショート対象 1 銘柄あたり 1 日の OC」
ann_mean = quintile_mean * 252.0

print("Quintile (1=lowest signal, 5=highest)  daily OC mean (×100) :")
for q in range(N_Q):
    print(f"  Q{q+1}: count={quintile_count[q]:>7}  mean={quintile_mean[q]*100:+.4f}%  ann≈{ann_mean[q]*100:+.2f}%")
print(f"Q5 − Q1 spread (daily) : {spread_q5_q1*100:+.4f}%  (ann≈{spread_q5_q1*252*100:+.2f}%)")
print(f"Number of upward diffs : {n_up} / {N_Q - 1}")
print(f"  → CELL 14 verdict     : {'PASS' if mono_pass else 'FAIL'} (Q5>Q1 and ≥3 of 4 diffs positive)")

# 可視化
fig, ax = plt.subplots(figsize=(8, 4))
xs = np.arange(1, N_Q + 1)
colors = ["#d62728", "#ff7f0e", "#7f7f7f", "#2ca02c", "#1f77b4"]
ax.bar(xs, quintile_mean * 100, color=colors)
for x, v in zip(xs, quintile_mean * 100):
    ax.text(x, v + (0.001 if v >= 0 else -0.001), f"{v:+.3f}%", ha="center",
            va="bottom" if v >= 0 else "top", fontsize=9)
ax.axhline(0, color="black", linewidth=0.6)
ax.set_xticks(xs)
ax.set_xticklabels([f"Q{q}" for q in xs])
ax.set_ylabel("mean next-day OC return (%)")
ax.set_title(f"Quintile spread  Q5−Q1 = {spread_q5_q1*100:+.4f}%  ({'monotone' if mono_pass else 'non-monotone'})")
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.show()
"""

CELL_15 = """# SECTION 2D — Cell 15: Look-ahead audit (shift)
# signal 系列を +1 営業日ずらすと、シグナル date_t を 1 日「遅らせて」評価する形になる。
# つまり「本来 t+1 のリターンを取るべきシグナルを t+2 のリターンに合わせる」ことで、
# 元の信号→翌日リターンという正しい時間関係を崩す。
# リーク (未来情報の混入) があれば、ずらしてもパフォーマンスが崩れない or 改善する。
#
# 合格ライン (要件定義書 v3 §4.1): シフトでパフォーマンスが大きく低下する。

def _ann_metrics(daily: np.ndarray) -> dict:
    daily = np.asarray(daily, dtype=float)
    daily = daily[~np.isnan(daily)]
    if daily.size == 0:
        return dict(AR=np.nan, RISK=np.nan, RR=np.nan, N=0)
    ar   = float(daily.mean() * 252.0)
    risk = float(daily.std(ddof=1) * np.sqrt(252.0))
    rr   = ar / risk if risk > 0 else np.nan
    return dict(AR=ar, RISK=risk, RR=rr, N=int(daily.size))

def _strategy_returns_from_signal(sig: np.ndarray, oc: np.ndarray,
                                  q_long: int = 5, q_short: int = 5) -> np.ndarray:
    \"\"\"sig[i] と oc[i] を行単位で対応させてロングショート P/L を計算する。

    sig: (N, 17)  ある時点 t における日本側スコア
    oc : (N, 17)  対応する時点で実現させる OC リターン (シフト試験では再アサインする)
    戻り値: shape (N,) の戦略リターン系列。
    \"\"\"
    assert sig.shape == oc.shape
    n_days, n_stk = sig.shape
    w_long  = +1.0 / q_long
    w_short = -1.0 / q_short
    out = np.empty(n_days, dtype=float)
    for i in range(n_days):
        order = np.argsort(-sig[i])
        long_idx  = order[:q_long]
        short_idx = order[-q_short:]
        w = np.zeros(n_stk)
        w[long_idx]  = w_long
        w[short_idx] = w_short
        out[i] = float(np.dot(w, oc[i]))
    return out

# (a) ベースライン：そのまま再計算（strategy_returns と一致するはず）
base_pnl = _strategy_returns_from_signal(sig_arr, oc_arr)
base_chk = np.allclose(base_pnl, strategy_returns.to_numpy())
assert base_chk, "Reconstructed baseline P/L does not match strategy_returns — implementation drift"

# (b) シフト：signal を 1 行先（未来）の OC に合わせる
#     具体的には oc_arr を 1 行ずらす（i 番目のシグナルに i+1 番目の OC を当てる）。
#     これにより signal_date < return_date は維持されるが「ペアが正しくない」状態になる。
sig_shift = sig_arr[:-1]            # 最後の 1 行を捨てる
oc_shift  = oc_arr[1:]              # 1 行先の OC
shift_pnl = _strategy_returns_from_signal(sig_shift, oc_shift)

m_base  = _ann_metrics(base_pnl)
m_shift = _ann_metrics(shift_pnl)
delta_rr = m_shift["RR"] - m_base["RR"]
shift_pass = (m_shift["RR"] < 0.5 * m_base["RR"]) if (m_base["RR"] is not np.nan and m_base["RR"] > 0) else False

print("Look-ahead audit (shift)")
print(f"  baseline       : AR={m_base['AR']*100:+.2f}%  RISK={m_base['RISK']*100:.2f}%  R/R={m_base['RR']:+.3f}  (N={m_base['N']})")
print(f"  shifted (+1)   : AR={m_shift['AR']*100:+.2f}%  RISK={m_shift['RISK']*100:.2f}%  R/R={m_shift['RR']:+.3f}  (N={m_shift['N']})")
print(f"  Δ R/R          : {delta_rr:+.3f}")
print(f"  baseline reproduces strategy_returns: {base_chk}")
print(f"  → CELL 15 verdict : {'PASS' if shift_pass else 'FAIL'}  (shifted R/R must be < 0.5 × baseline)")
"""

CELL_16 = """# SECTION 2D — Cell 16: Look-ahead audit (shuffle)
# 各日の signal を「銘柄方向に」ランダム並べ替え (per-row shuffle) して P/L 再計算する。
# 銘柄と OC リターンの正しい対応が壊れるため、IC・分位スプレッドが期待値ゼロになり、
# 結果として R/R もほぼゼロに収束するはず。
# シャッフルしても R/R が高いままなら、signal が銘柄情報を使っていない or 別の経路で
# 情報が漏れている疑い。
#
# 合格ライン (要件定義書 v3 §4.1): シャッフル後の R/R ≒ 0

rng_local = np.random.default_rng(RNG_SEED)   # seed 固定で再現性確保

# 各行（日）の銘柄インデックスを独立にシャッフル
sig_shuffled = sig_arr.copy()
for i in range(sig_shuffled.shape[0]):
    perm = rng_local.permutation(sig_shuffled.shape[1])
    sig_shuffled[i] = sig_arr[i, perm]

shuffle_pnl = _strategy_returns_from_signal(sig_shuffled, oc_arr)

m_shuf = _ann_metrics(shuffle_pnl)
shuffle_pass = abs(m_shuf["RR"]) < 0.5   # |R/R| < 0.5 をほぼゼロとみなす

print("Look-ahead audit (shuffle, seed=RNG_SEED)")
print(f"  baseline       : AR={m_base['AR']*100:+.2f}%  RISK={m_base['RISK']*100:.2f}%  R/R={m_base['RR']:+.3f}")
print(f"  shuffled       : AR={m_shuf['AR']*100:+.2f}%  RISK={m_shuf['RISK']*100:.2f}%  R/R={m_shuf['RR']:+.3f}  (N={m_shuf['N']})")
print(f"  → CELL 16 verdict : {'PASS' if shuffle_pass else 'FAIL'}  (|shuffled R/R| < 0.5)")
"""

CELL_17 = """## セル 17: 検証レイヤー合否判定（要件定義書 v3 §4.2）

| # | 検証項目 | 合格条件 | 実測値 | 判定 |
|---|---|---|---|---|
| 13 | IC | 平均 IC > 0 かつ t 値 > 2 | mean={ic_mean:+.4f}, t={ic_t:+.2f} | {ic_v} |
| 14 | 分位スプレッド | Q5 > Q1 かつ概ね単調（4 差分中 3 以上が正） | Q5−Q1 = {q_spread:+.4f}%/d (ann {q_ann:+.2f}%), up-diffs={n_up}/4 | {mono_v} |
| 15 | ルックアヘッド (シフト) | シフトで R/R が大幅低下 (< 0.5× baseline) | base R/R={rr_base:+.2f} → shift R/R={rr_shift:+.2f} | {sh_v} |
| 16 | ルックアヘッド (シャッフル) | シャッフルで \\|R/R\\| < 0.5 | shuf R/R={rr_shuf:+.2f} | {shf_v} |

**総合判定: {overall}**

{verdict_note}
"""

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _code_cell(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "id": "",
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


def _markdown_cell(source: str) -> dict:
    return {
        "cell_type": "markdown",
        "id": "",
        "metadata": {},
        "source": source.splitlines(keepends=True),
    }


CELL_17_HEADER_MD = """## セル 17: 検証レイヤー合否判定（要件定義書 v3 §4.2）

このセルは Markdown で書かれているが、合否表は実行時の値で埋まらないため、
**判定ロジックは以下の Python セルで実行され、その出力を見て確認する**。
（Notebook の再現性を保つため、結果値はセル 13〜16 の実行後に出力される。）
"""

CELL_17_PY = """# SECTION 2D — Cell 17: Final verdict (Python)
# セル 13〜16 のフラグを集約し、合否を判定する。
# 要件定義書 v3 §4.2 の合格条件 4 つすべてを満たす必要がある。

verdicts = {
    \"IC (mean>0 & t>2)\"       : (ic_pass,      f\"mean={ic_mean:+.4f}, t={ic_t:+.2f}\"),
    \"Quintile spread monotone\": (mono_pass,    f\"Q5-Q1={spread_q5_q1*100:+.4f}%/d, up-diffs={n_up}/4\"),
    \"Look-ahead shift\"        : (shift_pass,   f\"baseline R/R={m_base['RR']:+.2f} → shift R/R={m_shift['RR']:+.2f}\"),
    \"Look-ahead shuffle\"      : (shuffle_pass, f\"shuffled R/R={m_shuf['RR']:+.2f}\"),
}

overall = all(v[0] for v in verdicts.values())

print(\"=\" * 72)
print(\"SECTION 2D — Validation layer verdict (requirements_v3 §4.2)\")
print(\"=\" * 72)
for k, (ok, msg) in verdicts.items():
    print(f\"  [{'PASS' if ok else 'FAIL'}]  {k:30s}  {msg}\")
print(\"-\" * 72)
print(f\"  OVERALL : {'PASS — proceed to SECTION 2E / 3' if overall else 'FAIL — do NOT proceed to SECTION 3 (requirements_v3 §4.2)'}\")
print(\"=\" * 72)

if not overall:
    print(\"\\nHypotheses for failure (highest priority first):\")
    if not shift_pass:
        print(\"  - Look-ahead bug: re-audit cell 11 standardization. The window\")
        print(\"    statistics (mu_w, sigma_w) must NOT include data at index t.\")
    if not shuffle_pass:
        print(\"  - Signal may not depend on ticker identity. Check that V_J columns\")
        print(\"    differ across rows (i.e. PCA is actually using JP block).\")
    if not ic_pass:
        print(\"  - IC near zero or negative: predictive power absent. Re-check the\")
        print(\"    sign convention in compute_lead_lag_signal and ranking direction.\")
    if not mono_pass:
        print(\"  - Quintile spread non-monotone: signal direction may be inconsistent.\")
"""


def main() -> None:
    with open(NB_PATH, "r", encoding="utf-8") as f:
        nb = json.load(f)

    # 1. Remove any previously-appended SECTION 2D cells (idempotent).
    keep = []
    for cell in nb["cells"]:
        src = "".join(cell.get("source", []))
        if "SECTION 2D" in src or "セル 17: 検証レイヤー合否判定" in src:
            continue
        keep.append(cell)
    nb["cells"] = keep

    # 2. Append fresh SECTION 2D cells.
    new_cells = [
        _code_cell(CELL_13),
        _code_cell(CELL_14),
        _code_cell(CELL_15),
        _code_cell(CELL_16),
        _markdown_cell(CELL_17_HEADER_MD),
        _code_cell(CELL_17_PY),
    ]
    nb["cells"].extend(new_cells)

    with open(NB_PATH, "w", encoding="utf-8") as f:
        json.dump(nb, f, ensure_ascii=False, indent=1)
        f.write("\n")

    print(f"Appended {len(new_cells)} cells to {NB_PATH}")
    print(f"Total cells now: {len(nb['cells'])}")


if __name__ == "__main__":
    main()
