"""Append SECTION 2F cells (paper Table 2 baseline comparison) to 01_paper_replication.ipynb.

Idempotent: re-running removes any previously appended SECTION 2F cells (identified
by the leading marker comment / heading) and re-appends fresh ones.

Requirements_v3.md §4.3 / 論文 SIG-FIN-036-13 表2:
  Cell 21 (Markdown): Section header
  Cell 22 (Code):     Run MOM / PCA_PLAIN / DOUBLE backtests reusing existing
                      cc_np, oc_np, C0, signal_df, start_int, end_int, biz_idx;
                      build the 4-strategy comparison DataFrame vs paper table 2;
                      save CSV to data/performance/.
  Cell 23 (Code):     Plot cumulative return curves of all 4 strategies; save PNG;
                      print comparison table to stdout; one-line R/R commentary.

All baseline strategies obey the same look-ahead convention as cell 11:
  - Estimation window  W = cc_np[t-L : t]   (t exclusive)
  - Window statistics  μ_w, σ_w  with ddof=1
  - Signal generated at t
  - Return realized via oc_np[t+1]
"""

from __future__ import annotations

import json
import os
import uuid

NB_PATH = os.path.join(os.path.dirname(__file__), "01_paper_replication.ipynb")

# ---------------------------------------------------------------------------
# Cell sources
# ---------------------------------------------------------------------------

CELL_21_MD = """## SECTION 2F: 論文 表2 ベースライン戦略との比較

論文 SIG-FIN-036-13 表2 は、提案手法 **PCA_SUB** をベースライン3戦略と比較している：

1. **MOM**（単純モメンタム）: 日本側17銘柄について、推定ウィンドウ内のCCリターン平均 m_{j,t} = (1/L) Σ r_{j,τ} (τ ∈ W_t) をシグナルとする。米国側は使わない。
2. **PCA_PLAIN**: PCA_SUB と同じパイプラインだが λ=0（C_reg = C_t、事前部分空間 C0 は使わない）。
3. **PCA_SUB**: 実装済み（λ=0.9）。既存の `strategy_returns` を流用する。
4. **DOUBLE**: MOM シグナルと PCA_SUB シグナルをそれぞれメディアンで High/Low に二分し、High×High をロング、Low×Low をショートする 2×2 ソート。

ベースライン3戦略も SECTION 2C の規約（ウィンドウは `cc_np[t-L:t]`、シグナルは t 生成 → リターンは t+1 の OC で実現）を厳守する。MDD は (a) 論文式(30)準拠の **複利累積版** W_t = ∏(1+R_t) でのピーク比下落率 と (b) 既存 notebook の **単純和版** の両方を計算し、**論文比較は (a) を用いる**。
"""

CELL_22 = """# SECTION 2F — Cell 22: Baseline backtests (MOM / PCA_PLAIN / DOUBLE) and comparison table
# ルックアヘッド規約は cell 11 と同一: W = cc_np[t-L:t] (t排他)、シグナル t 生成 → 翌日 OC で実現。
# 既存 PCA_SUB の strategy_returns はそのまま流用し、cell 11 の出力には触れない。

# ---- 出力先 ----
PERF_DIR = os.path.join(REPO_ROOT, "data", "performance")
os.makedirs(PERF_DIR, exist_ok=True)

# ---- ベースライン3戦略のバックテストループ ----
# 既存 cell 11 と完全に同じ [start_int, end_int) を回す。
# MOM / PCA_PLAIN / DOUBLE のシグナルを毎日生成し、t+1 の OC で実現リターンに変換する。
# PCA_SUB のシグナルは既存 signal_df (date_t 索引) を流用する。
mom_dates_t1   = []
mom_returns    = []
plain_dates_t1 = []
plain_returns  = []
double_dates_t1   = []
double_returns    = []
double_long_sizes  = []
double_short_sizes = []

# シグナル系列（DOUBLE の構成に使う & 任意で監査用に保持）
mom_signal_rows   = []
plain_signal_rows = []

# 等ウェイト weight 構成は cell 11 と同じ (Q_LONG = Q_SHORT = 5)
w_long_5  = +1.0 / Q_LONG
w_short_5 = -1.0 / Q_SHORT

for t in range(start_int, end_int):
    # ---- ウィンドウ（cell 11 と同一の規約） ----
    W = cc_np[t - L : t]                        # (60, 26), t を含まない
    assert W.shape == (L, N_TOTAL)
    assert not np.isnan(W).any(), f"NaN in window at t={t}"

    # ===========================================================
    # 戦略 1: MOM — 日本側 CC リターンのウィンドウ平均（米国は使わない）
    # ===========================================================
    mom_signal_jp = W[:, N_US:N_TOTAL].mean(axis=0)        # (17,)

    # 上位 5 ロング・下位 5 ショート（cell 11 と同じランキング規約）
    rank_mom = np.argsort(-mom_signal_jp)
    long_mom_idx  = rank_mom[:Q_LONG]
    short_mom_idx = rank_mom[-Q_SHORT:]
    w_mom = np.zeros(N_JP)
    w_mom[long_mom_idx]  = w_long_5
    w_mom[short_mom_idx] = w_short_5

    # ===========================================================
    # 戦略 2: PCA_PLAIN — λ=0 の場合（C_reg = C_t、事前 C0 は使わない）
    # ===========================================================
    mu_w    = W.mean(axis=0)
    sigma_w = W.std(axis=0, ddof=1)
    if (sigma_w == 0).any():
        raise RuntimeError(f"Zero-variance ticker in window ending at t={t}")
    Z_w  = (W - mu_w) / sigma_w
    C_t  = (Z_w.T @ Z_w) / (L - 1)

    # λ=0 のときは C_reg = C_t（C0 は寄与しない）
    C_reg_plain = compute_regularized_correlation(C_t, C0, lam=0.0)
    assert np.allclose(C_reg_plain, C_t), "λ=0 must yield C_reg == C_t"

    V_U_p, V_J_p = extract_top_eigenvectors(C_reg_plain, K, N_US)

    # 当日 t の US CC リターンをウィンドウ統計量で標準化（t 自身の統計量は使わない）
    cc_t = cc_np[t]
    assert not np.isnan(cc_t).any(), f"NaN in cc on t={t}"
    z_t  = (cc_t - mu_w) / sigma_w
    z_us_t = z_t[:N_US]
    plain_signal_jp = compute_lead_lag_signal(z_us_t, V_U_p, V_J_p)

    rank_plain = np.argsort(-plain_signal_jp)
    long_plain_idx  = rank_plain[:Q_LONG]
    short_plain_idx = rank_plain[-Q_SHORT:]
    w_plain = np.zeros(N_JP)
    w_plain[long_plain_idx]  = w_long_5
    w_plain[short_plain_idx] = w_short_5

    # ===========================================================
    # 戦略 4: DOUBLE — MOM と PCA_SUB の 2×2 メディアン分割
    # ===========================================================
    # PCA_SUB のシグナルは signal_df の t 行を再利用（cell 11 出力）
    signal_date = biz_idx[t]
    sub_signal_jp = signal_df.loc[signal_date].to_numpy()  # (17,)

    med_mom = np.median(mom_signal_jp)
    med_sub = np.median(sub_signal_jp)
    high_mom = mom_signal_jp > med_mom        # 厳密に大きい（メディアン銘柄は中立）
    low_mom  = mom_signal_jp < med_mom
    high_sub = sub_signal_jp > med_sub
    low_sub  = sub_signal_jp < med_sub

    long_double  = high_mom & high_sub        # High×High
    short_double = low_mom  & low_sub         # Low×Low
    n_long_d  = int(long_double.sum())
    n_short_d = int(short_double.sum())

    w_double = np.zeros(N_JP)
    # 片側がゼロ銘柄になった日は、その側はノーポジ（重み 0）にする
    if n_long_d  > 0: w_double[long_double]  = +1.0 / n_long_d
    if n_short_d > 0: w_double[short_double] = -1.0 / n_short_d

    # ===========================================================
    # 翌日 t+1 の OC で全戦略の実現リターン
    # ===========================================================
    r_oc_next = oc_np[t + 1]
    assert not np.isnan(r_oc_next).any(), f"NaN in oc at t+1={t+1}"
    return_date = biz_idx[t + 1]
    assert signal_date < return_date, "Lookahead violation"

    mom_returns.append(float(np.dot(w_mom,    r_oc_next)))
    plain_returns.append(float(np.dot(w_plain,  r_oc_next)))
    double_returns.append(float(np.dot(w_double, r_oc_next)))
    mom_dates_t1.append(return_date)
    plain_dates_t1.append(return_date)
    double_dates_t1.append(return_date)
    double_long_sizes.append(n_long_d)
    double_short_sizes.append(n_short_d)
    mom_signal_rows.append(mom_signal_jp)
    plain_signal_rows.append(plain_signal_jp)

mom_returns_s    = pd.Series(mom_returns,    index=pd.DatetimeIndex(mom_dates_t1,    name="date_t1"), name="mom")
plain_returns_s  = pd.Series(plain_returns,  index=pd.DatetimeIndex(plain_dates_t1,  name="date_t1"), name="pca_plain")
double_returns_s = pd.Series(double_returns, index=pd.DatetimeIndex(double_dates_t1, name="date_t1"), name="double")

# index 整合性チェック（PCA_SUB の strategy_returns と同じ日付列であること）
assert mom_returns_s.index.equals(strategy_returns.index),    "MOM    index mismatch vs strategy_returns"
assert plain_returns_s.index.equals(strategy_returns.index),  "PLAIN  index mismatch vs strategy_returns"
assert double_returns_s.index.equals(strategy_returns.index), "DOUBLE index mismatch vs strategy_returns"

print(f"baseline backtests done. days={len(mom_returns_s)}")
print(f"  date range : {mom_returns_s.index[0].date()} → {mom_returns_s.index[-1].date()}")
print(f"  DOUBLE basket sizes (long ): min={min(double_long_sizes)}, median={int(np.median(double_long_sizes))}, max={max(double_long_sizes)}")
print(f"  DOUBLE basket sizes (short): min={min(double_short_sizes)}, median={int(np.median(double_short_sizes))}, max={max(double_short_sizes)}")

# ---- 指標計算ヘルパー ----
ANN_FACTOR = 252.0

def _metrics(daily: np.ndarray) -> dict:
    \"\"\"AR, RISK, R/R と 2通りの MDD を返す。
    MDD_compound: 論文式(30) 準拠。W_t = ∏(1+R_τ) のピーク比最大下落率（正の値）。
    MDD_simple  : 既存 notebook 流の累積和ベース。peak - cum の最大値（正の値）。
    \"\"\"
    n = daily.size
    mean_d = float(daily.mean())
    std_d  = float(daily.std(ddof=1))
    ar     = mean_d * ANN_FACTOR
    risk   = std_d  * np.sqrt(ANN_FACTOR)
    rr     = ar / risk if risk > 0 else float('nan')

    # (a) compounded MDD (paper eq.30)
    wealth = np.cumprod(1.0 + daily)
    peak_w = np.maximum.accumulate(wealth)
    dd_w   = wealth / peak_w - 1.0           # ≤ 0
    mdd_compound = float(-dd_w.min())

    # (b) simple-sum MDD (notebook §2E 流儀)
    cum_s  = np.cumsum(daily)
    peak_s = np.maximum.accumulate(cum_s)
    mdd_simple = float((peak_s - cum_s).max())

    return dict(n=n, AR=ar, RISK=risk, RR=rr,
                MDD_compound=mdd_compound, MDD_simple=mdd_simple)

# ---- 4戦略のメトリクスを計算 ----
all_returns = {
    "MOM":       mom_returns_s,
    "PCA_PLAIN": plain_returns_s,
    "PCA_SUB":   strategy_returns,     # 既存 cell 11 出力をそのまま流用
    "DOUBLE":    double_returns_s,
}
metrics = {name: _metrics(s.to_numpy()) for name, s in all_returns.items()}

# ---- 論文 表2 の値（SIG-FIN-036-13, p.81）— % 単位（R/R のみ無次元） ----
PAPER_TABLE2 = {
    "MOM":       dict(AR=0.0563, RISK=0.1059, RR=0.53, MDD=0.1697),
    "PCA_PLAIN": dict(AR=0.0624, RISK=0.0994, RR=0.62, MDD=0.2365),
    "PCA_SUB":   dict(AR=0.2379, RISK=0.1070, RR=2.22, MDD=0.0958),
    "DOUBLE":    dict(AR=0.1886, RISK=0.1116, RR=1.69, MDD=0.1210),
}

# ---- 比較 DataFrame（パーセント表示） ----
rows = []
for name in ["MOM", "PCA_PLAIN", "PCA_SUB", "DOUBLE"]:
    m = metrics[name]
    p = PAPER_TABLE2[name]
    rows.append({
        ("Implementation", "AR (%)"):      m["AR"]   * 100,
        ("Implementation", "RISK (%)"):    m["RISK"] * 100,
        ("Implementation", "R/R"):         m["RR"],
        ("Implementation", "MDD_c (%)"):   m["MDD_compound"] * 100,
        ("Implementation", "MDD_s (%)"):   m["MDD_simple"]   * 100,
        ("Paper Table 2", "AR (%)"):       p["AR"]   * 100,
        ("Paper Table 2", "RISK (%)"):     p["RISK"] * 100,
        ("Paper Table 2", "R/R"):          p["RR"],
        ("Paper Table 2", "MDD (%)"):      p["MDD"]  * 100,
    })
comparison_df = pd.DataFrame(rows, index=["MOM", "PCA_PLAIN", "PCA_SUB", "DOUBLE"])
comparison_df.columns = pd.MultiIndex.from_tuples(comparison_df.columns)
comparison_df.index.name = "strategy"

# ---- CSV 保存 ----
csv_path = os.path.join(PERF_DIR, "baseline_comparison.csv")
comparison_df.to_csv(csv_path, float_format="%.4f")
print(f"\\nSaved comparison CSV: {csv_path}")
print("\\n=== 4戦略 × 論文表2 比較 ===")
print(comparison_df.round(2).to_string())
"""

CELL_23 = """# SECTION 2F — Cell 23: Cumulative return curves + R/R commentary
# 4戦略の複利累積リターン（W_t = ∏(1+R_t)）を1枚のグラフに描画して PNG 保存。
# 論文は複利累積（式30 と同じ W_t）でドローダウンを評価しているため、可視化も複利で揃える。

fig, ax = plt.subplots(figsize=(11, 5))

colors = {"MOM": "#888888", "PCA_PLAIN": "#1f77b4", "PCA_SUB": "#d62728", "DOUBLE": "#2ca02c"}
linestyles = {"MOM": "--", "PCA_PLAIN": ":", "PCA_SUB": "-", "DOUBLE": "-."}

for name in ["MOM", "PCA_PLAIN", "PCA_SUB", "DOUBLE"]:
    s = all_returns[name].to_numpy()
    wealth = np.cumprod(1.0 + s)
    ax.plot(all_returns[name].index, (wealth - 1.0) * 100,
            color=colors[name], linestyle=linestyles[name], linewidth=1.4,
            label=f"{name}  (AR={metrics[name]['AR']*100:+.2f}%, R/R={metrics[name]['RR']:+.3f})")

ax.axhline(0, color="black", linewidth=0.4)
ax.set_xlabel("date (t+1, OC realised)")
ax.set_ylabel("compounded cumulative P/L (%)  —  W_t − 1")
ax.set_title("Baseline comparison — 4 strategies (compounded cumulative return)")
ax.grid(alpha=0.3)
ax.legend(loc="upper left", fontsize=9)
plt.tight_layout()

png_path = os.path.join(PERF_DIR, "baseline_comparison.png")
plt.savefig(png_path, dpi=150, bbox_inches="tight")
print(f"Saved cumulative-return PNG: {png_path}")
plt.show()

# ---- R/R 一言コメント ----
rr_sub = metrics["PCA_SUB"]["RR"]
others = {k: v["RR"] for k, v in metrics.items() if k != "PCA_SUB"}
sub_wins = all(rr_sub > v for v in others.values())
print("")
print(f"R/R: MOM={others['MOM']:+.3f}, PCA_PLAIN={others['PCA_PLAIN']:+.3f}, "
      f"PCA_SUB={rr_sub:+.3f}, DOUBLE={others['DOUBLE']:+.3f}")
if sub_wins:
    print("→ コメント: PCA_SUB は他3戦略 (MOM / PCA_PLAIN / DOUBLE) を R/R で上回っている。")
else:
    losers = [k for k, v in others.items() if v >= rr_sub]
    print(f"→ コメント: PCA_SUB は R/R で他3戦略のうち {losers} を上回れていない。")
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _code_cell(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "id": uuid.uuid4().hex[:8],
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


def _markdown_cell(source: str) -> dict:
    return {
        "cell_type": "markdown",
        "id": uuid.uuid4().hex[:8],
        "metadata": {},
        "source": source.splitlines(keepends=True),
    }


def main() -> None:
    with open(NB_PATH, "r", encoding="utf-8") as f:
        nb = json.load(f)

    # Remove any previously-appended SECTION 2F cells (idempotent).
    keep = []
    for cell in nb["cells"]:
        src = "".join(cell.get("source", []))
        first_line = src.splitlines()[0] if src else ""
        if (first_line.startswith("# SECTION 2F —")
                or first_line.startswith("## SECTION 2F:")):
            continue
        keep.append(cell)
    nb["cells"] = keep

    new_cells = [
        _markdown_cell(CELL_21_MD),
        _code_cell(CELL_22),
        _code_cell(CELL_23),
    ]
    nb["cells"].extend(new_cells)

    with open(NB_PATH, "w", encoding="utf-8") as f:
        json.dump(nb, f, ensure_ascii=False, indent=1)
        f.write("\n")

    print(f"Appended {len(new_cells)} cells. Total cells now: {len(nb['cells'])}")


if __name__ == "__main__":
    main()
