/* =====================================================================
 * Sector Lead-Lag Dashboard — app.js
 * SECTION 10 (純フロントエンド): docs/data.json を fetch して描画する。
 *
 * docs/data.json スキーマ (SECTION 7 の src/main.py が出力):
 *   {
 *     "last_updated": "ISO 8601 (JST)",
 *     "basket_size":   5,                          // 任意。1銘柄あたり想定元本比率 = 1/basket_size
 *     "current_signal": {
 *       "date": "YYYY-MM-DD",
 *       "long_basket":  ["1618.T", ...],          // basket_size 銘柄, スコア降順
 *       "short_basket": ["1633.T", ...],          // basket_size 銘柄, スコア昇順
 *       "factor_scores": [PC1, PC2, PC3],
 *       "all_scores":    { "1617.T": float, ... } // 17 JP tickers
 *     },
 *     "history": [
 *       { "date": "YYYY-MM-DD",
 *         "long":  [...basket_size...],
 *         "short": [...basket_size...],
 *         "realized_return": 0.0123                // 任意。t+1 OC の long-short 実現リターン(小数)。
 *                                                  // 未確定（t+1 未観測）の場合は null。
 *       },
 *       ...                                          // 最大 100 営業日
 *     ]
 *   }
 *
 * 設計判断: 累積パフォーマンスは2本のラインで描画する。
 *   (1) コスト控除前 P/L = Σ realized_return (小数 → %換算、null はスキップ＝加算しない)
 *   (2) コスト控除後 P/L = (1) − 累積リバランスコスト
 * data.json 旧スキーマで realized_return が無い場合、(1) は 0 のフラットラインに退化する。
 * basket_size が無い場合は 1銘柄=元本10%（旧定数 0.10）にフォールバック。
 * (HANDOFF.md §5 / 仕様書 sections_v3.md SECTION 10 / 後継セクションの制約に基づく)
 * ===================================================================== */

(function () {
  "use strict";

  // ------------------------------------------------------------
  // 定数
  // ------------------------------------------------------------

  // ※ src/universe.py の JP_SECTOR_NAMES と同期させること
  //   (純フロントエンド作業のため二重定義。業種コードが変わったら両方を更新)
  const JP_SECTOR_NAMES = {
    "1617.T": "食品",
    "1618.T": "エネルギー資源",
    "1619.T": "建設・資材",
    "1620.T": "素材・化学",
    "1621.T": "医薬品",
    "1622.T": "自動車・輸送機",
    "1623.T": "鉄鋼・非鉄",
    "1624.T": "機械",
    "1625.T": "電機・精密",
    "1626.T": "情報通信・サービスその他",
    "1627.T": "電力・ガス",
    "1628.T": "運輸・物流",
    "1629.T": "商社・卸売",
    "1630.T": "小売",
    "1631.T": "銀行",
    "1632.T": "金融（除く銀行）",
    "1633.T": "不動産",
  };

  // localStorage キー (slc: プレフィックスで衝突回避)
  const LS_KEYS = {
    fee:      "slc:cost:fee",
    spread:   "slc:cost:spread",
    slippage: "slc:cost:slippage",
    borrow:   "slc:cost:borrow",
    tax:      "slc:cost:tax",
    rebalanceFreq: "slc:rebalance_freq",
  };

  // 既定値 (HTML の value 属性と一致させる)
  const COST_DEFAULTS = {
    fee:      0.05,    // 売買手数料 (往復合計, %)
    spread:   0.02,    // スプレッド (%)
    slippage: 0.03,    // スリッページ (%)
    borrow:   1.5,     // 貸株料 (年率 %)
    tax:      20.315,  // 税率 (%)
  };

  const HISTORY_ROWS = 30;       // 過去シグナル履歴テーブル表示行数
  const TRADING_DAYS = 252;      // 年率化係数 (要件 v3 §0 C5)

  // ------------------------------------------------------------
  // ユーティリティ
  // ------------------------------------------------------------

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  function fmtNumber(x, digits) {
    if (x === null || x === undefined || Number.isNaN(x)) return "—";
    return Number(x).toFixed(digits != null ? digits : 4);
  }

  function fmtDate(isoStr) {
    if (!isoStr) return "—";
    try {
      const d = new Date(isoStr);
      if (Number.isNaN(d.getTime())) return isoStr;
      const yyyy = d.getFullYear();
      const mm = String(d.getMonth() + 1).padStart(2, "0");
      const dd = String(d.getDate()).padStart(2, "0");
      const hh = String(d.getHours()).padStart(2, "0");
      const mi = String(d.getMinutes()).padStart(2, "0");
      return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
    } catch (e) {
      return isoStr;
    }
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function sectorName(ticker) {
    return JP_SECTOR_NAMES[ticker] || ticker;
  }

  // Plotly のテーマを prefers-color-scheme に追従させる
  function getPlotlyTheme() {
    const dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    return dark
      ? {
          paper_bgcolor: "transparent",
          plot_bgcolor: "transparent",
          font: { color: "#e8eaed" },
          xaxis: { gridcolor: "#2a2f38", linecolor: "#3a414c", zerolinecolor: "#3a414c" },
          yaxis: { gridcolor: "#2a2f38", linecolor: "#3a414c", zerolinecolor: "#3a414c" },
        }
      : {
          paper_bgcolor: "transparent",
          plot_bgcolor: "transparent",
          font: { color: "#1a1a1a" },
          xaxis: { gridcolor: "#e3e6eb", linecolor: "#c8ccd4", zerolinecolor: "#c8ccd4" },
          yaxis: { gridcolor: "#e3e6eb", linecolor: "#c8ccd4", zerolinecolor: "#c8ccd4" },
        };
  }

  // ------------------------------------------------------------
  // データ取得
  // ------------------------------------------------------------

  async function fetchData() {
    // キャッシュ回避のためクエリ文字列を付与
    const url = `./data.json?_=${Date.now()}`;
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status} on ${url}`);
    }
    return res.json();
  }

  function showFatalError(err) {
    console.error("[dashboard] fetch failed:", err);
    const msg = `データ読み込みに失敗しました: ${err.message}`;
    const banner = document.createElement("div");
    banner.className = "disclaimer";
    banner.style.margin = "16px 0";
    banner.textContent = msg;
    const main = $("main.container");
    if (main) main.prepend(banner);
  }

  // ------------------------------------------------------------
  // 描画: ヘッダー
  // ------------------------------------------------------------

  function renderHeader(data) {
    $("#last-updated").textContent = fmtDate(data.last_updated);
  }

  // ------------------------------------------------------------
  // 描画: 現在のシグナル
  // ------------------------------------------------------------

  function renderCurrentSignal(data) {
    const cs = data.current_signal || {};
    $("#signal-date").textContent = cs.date || "—";

    const allScores = cs.all_scores || {};

    const renderBasket = (ulId, tickers) => {
      const ul = $(ulId);
      ul.innerHTML = "";
      if (!Array.isArray(tickers) || tickers.length === 0) {
        ul.innerHTML = '<li class="basket-item"><span class="basket-item-main">データなし</span></li>';
        return;
      }
      for (const tk of tickers) {
        const score = allScores[tk];
        const li = document.createElement("li");
        li.className = "basket-item";
        li.innerHTML = `
          <span class="basket-item-main">
            <span class="basket-item-name">${escapeHtml(sectorName(tk))}</span>
            <span class="basket-item-ticker">${escapeHtml(tk)}</span>
          </span>
          <span class="basket-item-score" title="スコア">${fmtNumber(score, 4)}</span>
        `;
        ul.appendChild(li);
      }
    };

    renderBasket("#long-basket",  cs.long_basket);
    renderBasket("#short-basket", cs.short_basket);
  }

  // ------------------------------------------------------------
  // 描画: ファクタースコア棒グラフ
  // ------------------------------------------------------------

  function renderFactorScores(data) {
    const fs = (data.current_signal && data.current_signal.factor_scores) || [];
    const labels = ["PC1", "PC2", "PC3"];
    const values = labels.map((_, i) => (fs[i] != null ? fs[i] : 0));

    const theme = getPlotlyTheme();
    const trace = {
      type: "bar",
      x: labels,
      y: values,
      text: values.map((v) => fmtNumber(v, 3)),
      textposition: "outside",
      marker: {
        color: values.map((v) => (v >= 0 ? "#3b82f6" : "#dc2626")),
      },
      hovertemplate: "%{x}: %{y:.4f}<extra></extra>",
    };

    const layout = Object.assign({}, theme, {
      margin: { l: 50, r: 20, t: 20, b: 40 },
      xaxis: Object.assign({}, theme.xaxis, { title: "" }),
      yaxis: Object.assign({}, theme.yaxis, {
        title: "ファクタースコア",
        zeroline: true,
        zerolinewidth: 1,
      }),
      bargap: 0.4,
    });

    Plotly.newPlot("factor-scores-chart", [trace], layout, {
      displayModeBar: false,
      responsive: true,
    });
  }

  // ------------------------------------------------------------
  // 計算: turnover (前営業日との銘柄入替数)
  // ------------------------------------------------------------

  /**
   * history を日付昇順に整列し、各営業日について前日との銘柄入替数を計算する。
   * 入替数 = |today_long \ prev_long| + |today_short \ prev_short|  (片側の新規流入合計)
   *
   * 累積コストは「グロスエクスポージャー 200% に対して、当日入替された
   * 銘柄分のコストを発生させる」モデル:
   *   今日の取引比率 = (入替数 / 5) * 50%  (片側 50% グロスの片側を入替分だけ)
   *   両側合計コスト = 取引比率 * (fee + spread + slippage)  ※ % 表記
   *
   * 貸株料は連日のショート保有に対して 252 営業日按分で控除。
   *
   * @returns Array<{date: string, turnover: number, dailyCostPct: number}>
   *          (turnover はロング側+ショート側の新規流入数合計、最大 10)
   */
  function computeTurnoverSeries(history) {
    if (!Array.isArray(history) || history.length === 0) return [];
    // 日付昇順
    const sorted = history.slice().sort((a, b) => a.date.localeCompare(b.date));
    const result = [];
    let prevLong = null, prevShort = null;
    for (const row of sorted) {
      const longSet  = new Set(row.long  || []);
      const shortSet = new Set(row.short || []);
      let turnover;
      if (prevLong === null) {
        // 初日は全銘柄が新規 (ロング 5 + ショート 5 = 10)
        turnover = longSet.size + shortSet.size;
      } else {
        let newLong = 0, newShort = 0;
        for (const tk of longSet)  if (!prevLong.has(tk))  newLong++;
        for (const tk of shortSet) if (!prevShort.has(tk)) newShort++;
        turnover = newLong + newShort;
      }
      result.push({ date: row.date, turnover, longCount: longSet.size, shortCount: shortSet.size });
      prevLong = longSet;
      prevShort = shortSet;
    }
    return result;
  }

  /**
   * リバランス頻度に応じて turnover を間引きする。
   * - daily:   そのまま
   * - weekly:  ISO 週ごとに最後の営業日のみ採用、入替数は週内合計
   * - monthly: 年-月ごとに最後の営業日のみ採用、入替数は月内合計
   *
   * 「リバランス頻度を落とすほど 1 回あたりの入替が増えるが回数が減る」モデル。
   * 実運用では中間日のシグナルを「無視」するため、その期間の累積入替を 1 回の
   * リバランスで処理する近似。
   */
  function resampleByFrequency(series, freq) {
    if (freq === "daily" || !series.length) return series.slice();
    const groups = new Map(); // key -> { date, turnoverSum, longCount, shortCount }
    const keyFn = (dateStr) => {
      const [y, m, d] = dateStr.split("-").map(Number);
      const dt = new Date(Date.UTC(y, m - 1, d));
      if (freq === "monthly") {
        return `${y}-${String(m).padStart(2, "0")}`;
      }
      // weekly: ISO week
      const target = new Date(dt);
      const dayNum = (target.getUTCDay() + 6) % 7; // Mon=0..Sun=6
      target.setUTCDate(target.getUTCDate() - dayNum + 3);
      const firstThursday = new Date(Date.UTC(target.getUTCFullYear(), 0, 4));
      const diff = (target - firstThursday) / 86400000;
      const week = 1 + Math.round((diff - 3 + ((firstThursday.getUTCDay() + 6) % 7)) / 7);
      return `${target.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
    };

    for (const row of series) {
      const k = keyFn(row.date);
      if (!groups.has(k)) {
        groups.set(k, { date: row.date, turnover: 0, longCount: row.longCount, shortCount: row.shortCount });
      }
      const g = groups.get(k);
      g.turnover += row.turnover;
      g.date = row.date; // 期間内最後の日付を保持
      g.longCount = row.longCount;
      g.shortCount = row.shortCount;
    }
    return Array.from(groups.values()).sort((a, b) => a.date.localeCompare(b.date));
  }

  /**
   * 1銘柄あたりの想定元本比率を返す。
   *   data.json に basket_size があれば 1/basket_size、無ければ旧仕様の 0.10。
   * フォールバック 0.10 は basket_size=10 相当 (= 旧コードのハードコード値)。
   */
  function perNameNotionalFraction(basketSize) {
    return (typeof basketSize === "number" && basketSize > 0)
      ? 1 / basketSize
      : 0.10;
  }

  /**
   * リバランス頻度別に、累積コスト系列を組み立てる。
   * - 1銘柄入替の取引相当 = 入替数 × (1/basket_size) [= perNameNotionalFraction]
   *   ※ basket_size が無い場合は 0.10 (= 1銘柄=10% notional の旧定数) にフォールバック。
   * - 貸株料は保有日数比例: 各リバランス期間の経過営業日数 × (borrow_annual / 252) × 50% (ショート側グロス)
   *
   * @param series      resampled series
   * @param costs       { fee, spread, slippage, borrow, tax } in percent
   * @param freq        "daily" | "weekly" | "monthly"
   * @param basketSize  data.basket_size (任意; 未定義の場合は perNameNotionalFraction が 0.10 にフォールバック)
   * @returns Array<{date: string, cumCostPct: number, tradeCostPct: number, borrowCostPct: number}>
   */
  function buildCostSeries(series, costs, freq, basketSize) {
    if (!series.length) return [];
    const tradingDaysBetween = (a, b) => {
      // 単純近似: カレンダー差 × 5/7
      const da = new Date(a), db = new Date(b);
      const days = Math.max(0, Math.round((db - da) / 86400000));
      return Math.max(1, Math.round(days * 5 / 7));
    };

    const txCostPct = costs.fee + costs.spread + costs.slippage; // % per 100% notional traded
    const perName = perNameNotionalFraction(basketSize);
    const out = [];
    let cumCost = 0;
    let prevDate = null;
    for (const row of series) {
      // 取引コスト: 入替 1 銘柄 = perName 相当の notional
      const tradedFraction = row.turnover * perName;
      const tradeCostPct = tradedFraction * txCostPct;
      // 貸株料: 期間の営業日数 × (borrow/252) × 50% グロス
      let borrowDays;
      if (prevDate === null) {
        borrowDays = freq === "monthly" ? 21 : freq === "weekly" ? 5 : 1;
      } else {
        borrowDays = tradingDaysBetween(prevDate, row.date);
      }
      const borrowCostPct = (costs.borrow / TRADING_DAYS) * borrowDays * 0.5;
      cumCost += tradeCostPct + borrowCostPct;
      out.push({ date: row.date, cumCostPct: cumCost, tradeCostPct, borrowCostPct });
      prevDate = row.date;
    }
    return out;
  }

  // ------------------------------------------------------------
  // 計算: 累積実現 P/L (history.realized_return の単純和)
  // ------------------------------------------------------------

  /**
   * history を日付昇順に整列し、各営業日について realized_return の累積和（%表示）を返す。
   * realized_return が null/undefined/非数の場合はその日の加算をスキップ（累積値は前日を踏襲）。
   *
   * @returns Array<{date: string, cumReturnPct: number, hadRealized: boolean}>
   *   hadRealized は「その日までに少なくとも 1 つ realized_return が観測されたか」。
   *   全期間 false の場合、cumReturnPct はすべて 0（旧「理論 P/L = 0 ライン」相当の挙動）。
   */
  function buildCumulativeRealizedPL(history) {
    if (!Array.isArray(history) || !history.length) return [];
    const sorted = history.slice().sort((a, b) => a.date.localeCompare(b.date));
    const out = [];
    let cum = 0;
    let hadAny = false;
    for (const row of sorted) {
      const r = row.realized_return;
      if (r != null && Number.isFinite(r)) {
        cum += Number(r) * 100; // 小数 → %
        hadAny = true;
      }
      out.push({ date: row.date, cumReturnPct: cum, hadRealized: hadAny });
    }
    return out;
  }

  /**
   * costSeries（リサンプリング済み、稀な日付列）を P/L 系列の日付列に
   * 前方フィル（step-function）で揃える。各 plDate について、それ以下の
   * 最新 costSeries エントリの cumCostPct を返す。
   *
   * @param costSeries Array<{date, cumCostPct}>（日付昇順）
   * @param plDates    string[]（日付昇順）
   * @returns number[]（plDates と同じ長さ。先頭で対応するコストが無い場合は 0）
   */
  function alignCostToDates(costSeries, plDates) {
    const result = new Array(plDates.length).fill(0);
    if (!costSeries.length) return result;
    let i = 0;
    let lastCost = 0;
    for (let j = 0; j < plDates.length; j++) {
      while (i < costSeries.length && costSeries[i].date <= plDates[j]) {
        lastCost = costSeries[i].cumCostPct;
        i++;
      }
      result[j] = lastCost;
    }
    return result;
  }

  // ------------------------------------------------------------
  // 描画: 累積パフォーマンス（コスト控除前後）
  // ------------------------------------------------------------

  function renderPerformance(data, costs, freq) {
    const history = data.history || [];
    const basketSize = data.basket_size;
    const turnoverRaw = computeTurnoverSeries(history);
    const resampled  = resampleByFrequency(turnoverRaw, freq);
    const costSeries = buildCostSeries(resampled, costs, freq, basketSize);
    const plSeries   = buildCumulativeRealizedPL(history);

    const theme = getPlotlyTheme();
    const noteEl = $("#performance-note");

    if (!history.length) {
      Plotly.purge("performance-chart");
      $("#performance-chart").innerHTML =
        '<p style="padding:48px 16px;text-align:center;color:var(--fg-subtle);">' +
        'history データなし。GitHub Actions が毎営業日 06:00 JST に実行されるたびに蓄積されます。' +
        '</p>';
      noteEl.textContent = "";
      return;
    }

    // x 軸は history 全営業日（plSeries の日付）に統一し、コスト系列は前方フィルで揃える。
    const dates = plSeries.map((r) => r.date);
    const beforeCostY = plSeries.map((r) => r.cumReturnPct);
    const alignedCost = alignCostToDates(costSeries, dates);
    const afterCostY  = beforeCostY.map((bc, i) => bc - alignedCost[i]);

    const hasRealized = plSeries.length > 0 && plSeries[plSeries.length - 1].hadRealized;
    const lastCumCost = alignedCost.length ? alignedCost[alignedCost.length - 1] : 0;
    const lastBefore  = beforeCostY.length ? beforeCostY[beforeCostY.length - 1] : 0;
    const lastAfter   = afterCostY.length  ? afterCostY[afterCostY.length - 1]  : 0;

    if (dates.length === 1) {
      noteEl.textContent =
        "履歴が 1 営業日分のみです。turnover 計算は前日比のため、複数日蓄積されてから本格的な可視化が可能になります。";
    } else if (!hasRealized) {
      noteEl.textContent =
        `${dates.length} データポイント / ${freq} リバランス想定。` +
        `realized_return 未蓄積のため控除前 P/L は 0 ライン、控除後 P/L = -累積コスト (${lastCumCost.toFixed(3)}%)。`;
    } else {
      noteEl.textContent =
        `${dates.length} データポイント / ${freq} リバランス想定。` +
        `控除前 P/L = ${lastBefore.toFixed(3)}% / 累積コスト = ${lastCumCost.toFixed(3)}% / 控除後 P/L = ${lastAfter.toFixed(3)}%。`;
    }

    const traceBefore = {
      type: "scatter",
      mode: "lines+markers",
      name: "コスト控除前 P/L (累積実現リターン)",
      x: dates,
      y: beforeCostY,
      line: { color: "#3b82f6", width: 2 },
      marker: { size: 5 },
      hovertemplate: "%{x}<br>控除前 P/L: %{y:.3f}%<extra></extra>",
    };
    const traceAfter = {
      type: "scatter",
      mode: "lines+markers",
      name: "コスト控除後 P/L (= 控除前 − 累積コスト)",
      x: dates,
      y: afterCostY,
      line: { color: "#dc2626", width: 2 },
      marker: { size: 5 },
      hovertemplate: "%{x}<br>累積コスト: %{customdata:.3f}%<br>控除後 P/L: %{y:.3f}%<extra></extra>",
      customdata: alignedCost,
    };

    const layout = Object.assign({}, theme, {
      margin: { l: 60, r: 20, t: 20, b: 60 },
      xaxis: Object.assign({}, theme.xaxis, { title: "日付", tickangle: -30 }),
      yaxis: Object.assign({}, theme.yaxis, {
        title: "累積 P/L (%)",
        zeroline: true,
        zerolinewidth: 1,
      }),
      legend: { orientation: "h", y: -0.22, x: 0 },
      hovermode: "x unified",
    });

    Plotly.react("performance-chart", [traceBefore, traceAfter], layout, {
      displayModeBar: false,
      responsive: true,
    });
  }

  // ------------------------------------------------------------
  // 描画: 履歴テーブル
  // ------------------------------------------------------------

  let historySortKey = "date";
  let historySortDir = "desc"; // "asc" | "desc"
  let cachedHistoryRows = [];  // {date, long, short, turnover}

  function buildHistoryRows(data) {
    const turnoverMap = new Map();
    const turnoverSeries = computeTurnoverSeries(data.history || []);
    for (const row of turnoverSeries) turnoverMap.set(row.date, row.turnover);

    return (data.history || []).map((r) => ({
      date:  r.date,
      long:  (r.long  || []).slice(),
      short: (r.short || []).slice(),
      turnover: turnoverMap.get(r.date) != null ? turnoverMap.get(r.date) : null,
    }));
  }

  function renderHistoryTable() {
    const tbody = $("#history-tbody");
    tbody.innerHTML = "";

    if (!cachedHistoryRows.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="empty">履歴データはまだありません。</td></tr>';
      return;
    }

    const sorted = cachedHistoryRows.slice().sort((a, b) => {
      let va, vb;
      switch (historySortKey) {
        case "long":
          va = (a.long || []).join(",");
          vb = (b.long || []).join(",");
          break;
        case "short":
          va = (a.short || []).join(",");
          vb = (b.short || []).join(",");
          break;
        case "turnover":
          va = a.turnover != null ? a.turnover : -1;
          vb = b.turnover != null ? b.turnover : -1;
          break;
        case "date":
        default:
          va = a.date;
          vb = b.date;
      }
      if (va < vb) return historySortDir === "asc" ? -1 : 1;
      if (va > vb) return historySortDir === "asc" ? 1 : -1;
      return 0;
    });

    const top = sorted.slice(0, HISTORY_ROWS);
    for (const r of top) {
      const longHtml  = (r.long  || []).map((tk) => `<span class="long">${escapeHtml(tk)}</span>`).join(" ");
      const shortHtml = (r.short || []).map((tk) => `<span class="short">${escapeHtml(tk)}</span>`).join(" ");
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${escapeHtml(r.date)}</td>
        <td><span class="ticker-list">${longHtml}</span></td>
        <td><span class="ticker-list">${shortHtml}</span></td>
        <td>${r.turnover != null ? r.turnover : "—"}</td>
      `;
      tbody.appendChild(tr);
    }

    // ヘッダの sort indicator 更新
    $$("#history-table th").forEach((th) => {
      const k = th.dataset.sortKey;
      let label = th.textContent.replace(/\s[▾▴]$/, "").trim();
      if (k === historySortKey) {
        th.textContent = `${label} ${historySortDir === "asc" ? "▴" : "▾"}`;
        th.setAttribute("aria-sort", historySortDir === "asc" ? "ascending" : "descending");
      } else {
        th.textContent = label;
        th.setAttribute("aria-sort", "none");
      }
    });
  }

  function setupHistorySort() {
    $$("#history-table th").forEach((th) => {
      th.addEventListener("click", () => {
        const k = th.dataset.sortKey;
        if (!k) return;
        if (historySortKey === k) {
          historySortDir = historySortDir === "asc" ? "desc" : "asc";
        } else {
          historySortKey = k;
          historySortDir = k === "date" ? "desc" : "asc";
        }
        renderHistoryTable();
      });
    });
  }

  // ------------------------------------------------------------
  // コスト設定パネル (localStorage 連動)
  // ------------------------------------------------------------

  function loadCosts() {
    const out = {};
    for (const key of Object.keys(COST_DEFAULTS)) {
      const stored = localStorage.getItem(LS_KEYS[key]);
      const parsed = stored !== null ? Number(stored) : NaN;
      out[key] = Number.isFinite(parsed) ? parsed : COST_DEFAULTS[key];
    }
    return out;
  }

  function applyCostsToForm(costs) {
    $("#cost-fee").value      = costs.fee;
    $("#cost-spread").value   = costs.spread;
    $("#cost-slippage").value = costs.slippage;
    $("#cost-borrow").value   = costs.borrow;
    $("#cost-tax").value      = costs.tax;
  }

  function loadFreq() {
    const stored = localStorage.getItem(LS_KEYS.rebalanceFreq);
    if (stored === "daily" || stored === "weekly" || stored === "monthly") return stored;
    return "daily";
  }

  function applyFreqToForm(freq) {
    const el = document.querySelector(`input[name="rebalance-freq"][value="${freq}"]`);
    if (el) el.checked = true;
  }

  function setupCostForm(data) {
    const costs = loadCosts();
    applyCostsToForm(costs);

    const handler = () => {
      const newCosts = {
        fee:      Math.max(0, Number($("#cost-fee").value)      || 0),
        spread:   Math.max(0, Number($("#cost-spread").value)   || 0),
        slippage: Math.max(0, Number($("#cost-slippage").value) || 0),
        borrow:   Math.max(0, Number($("#cost-borrow").value)   || 0),
        tax:      Math.max(0, Number($("#cost-tax").value)      || 0),
      };
      localStorage.setItem(LS_KEYS.fee,      String(newCosts.fee));
      localStorage.setItem(LS_KEYS.spread,   String(newCosts.spread));
      localStorage.setItem(LS_KEYS.slippage, String(newCosts.slippage));
      localStorage.setItem(LS_KEYS.borrow,   String(newCosts.borrow));
      localStorage.setItem(LS_KEYS.tax,      String(newCosts.tax));
      renderPerformance(data, newCosts, getActiveFreq());
    };

    ["#cost-fee", "#cost-spread", "#cost-slippage", "#cost-borrow", "#cost-tax"]
      .forEach((sel) => $(sel).addEventListener("input", handler));

    $("#cost-reset").addEventListener("click", () => {
      applyCostsToForm(COST_DEFAULTS);
      handler();
    });
  }

  function setupFreqRadios(data) {
    const freq = loadFreq();
    applyFreqToForm(freq);
    $$('input[name="rebalance-freq"]').forEach((el) => {
      el.addEventListener("change", () => {
        if (!el.checked) return;
        localStorage.setItem(LS_KEYS.rebalanceFreq, el.value);
        renderPerformance(data, loadCosts(), el.value);
      });
    });
  }

  function getActiveFreq() {
    const el = document.querySelector('input[name="rebalance-freq"]:checked');
    return el ? el.value : "daily";
  }

  // ------------------------------------------------------------
  // エントリポイント
  // ------------------------------------------------------------

  async function main() {
    let data;
    try {
      data = await fetchData();
    } catch (err) {
      showFatalError(err);
      return;
    }

    renderHeader(data);
    renderCurrentSignal(data);
    renderFactorScores(data);

    cachedHistoryRows = buildHistoryRows(data);
    setupHistorySort();
    renderHistoryTable();

    setupCostForm(data);
    setupFreqRadios(data);
    renderPerformance(data, loadCosts(), loadFreq());

    // ダーク/ライトモード切替に追従して Plotly を再描画
    if (window.matchMedia) {
      const mql = window.matchMedia("(prefers-color-scheme: dark)");
      const onChange = () => {
        renderFactorScores(data);
        renderPerformance(data, loadCosts(), getActiveFreq());
      };
      if (mql.addEventListener) mql.addEventListener("change", onChange);
      else if (mql.addListener) mql.addListener(onChange); // older Safari
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", main);
  } else {
    main();
  }
})();
