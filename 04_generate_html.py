import json
import os
import re
import time

import pandas as pd

from config import (
    EXCESS_RETURN_PATH,
    NAV_DIR,
    INDEX_DIR,
    INDEX_NAMES,
    INDEX_AKSHARE_SYMBOLS,
)

OUTPUT_HTML = "output/index.html"
CHART_DAYS = 90  # 折线图展示最近多少个交易日


# ── 各周期对应的"成立不足X"说明 ──
PERIOD_HIERARCHY = [
    ("ytd_change",      "month_6_change",  "成立不足1年"),
    ("month_6_change",  "day_20_change",   "成立不足6月"),
    ("day_20_change",   "daily_change",    "成立不足20日"),
    ("daily_change",    None,              "无数据"),
]
PERIOD_HIERARCHY_EXCESS = [
    ("ytd_excess",      "month_6_excess",  "成立不足1年"),
    ("month_6_excess",  "day_20_excess",   "成立不足6月"),
    ("day_20_excess",   "daily_excess",    "成立不足20日"),
    ("daily_excess",    None,              "无数据"),
]

# 指数代码 → 本地 parquet 路径
INDEX_CODE_MAP = {"HS300": "HS300", "ZZ500": "ZZ500", "ZZ1000": "ZZ1000", "CSI_ALL": "CSI_ALL"}


def _get_empty_reason(col: str, row: pd.Series) -> str:
    for target, shorter, reason in PERIOD_HIERARCHY:
        if col == target:
            if shorter is None:
                return reason
            if pd.notna(row.get(shorter)):
                return reason
            continue
    for target, shorter, reason in PERIOD_HIERARCHY_EXCESS:
        if col == target:
            if shorter is None:
                return reason
            if pd.notna(row.get(shorter)):
                return reason
            continue
    return "暂无数据"


def format_pct(x):
    if pd.isna(x):
        return None
    val = x * 100
    if val > 0:
        color = "#f75454"
    elif val < 0:
        color = "#2ecc71"
    else:
        color = "#8899aa"
    return f'<span style="color:{color}">{val:+.2f}%</span>'


def _format_cell(val, col_name, row):
    if isinstance(val, str):
        return val
    reason = _get_empty_reason(col_name, row)
    return f'<span class="empty-reason">{reason}</span>'


def load_data():
    if not os.path.exists(EXCESS_RETURN_PATH):
        print(f"[ERROR] 没有找到超额收益文件: {EXCESS_RETURN_PATH}")
        return pd.DataFrame()
    df = pd.read_parquet(EXCESS_RETURN_PATH)
    print(f"读取基金数据: {len(df)} 条")

    # 加载成立时间 / 成立规模（从白名单 Excel）
    xls_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "fund_whitelist.xlsx")
    xls_path = os.path.normpath(xls_path)
    if os.path.exists(xls_path):
        launch_map = {}
        scale_map = {}
        for sheet in pd.ExcelFile(xls_path).sheet_names:
            sdf = pd.read_excel(xls_path, sheet_name=sheet, dtype=str)
            if sdf.shape[1] >= 3:
                for _, r in sdf.iterrows():
                    code = str(r.iloc[0]).strip().replace(".OF", "").zfill(6)
                    ld = str(r.iloc[2]) if pd.notna(r.iloc[2]) and str(r.iloc[2]) not in ("nan", "获取失败") else None
                    sc = str(r.iloc[3]) if sdf.shape[1] >= 4 and pd.notna(r.iloc[3]) and str(r.iloc[3]) not in ("nan", "获取失败") else None
                    if ld:
                        launch_map[code] = ld
                    if sc:
                        scale_map[code] = sc
        df["launch_date"] = df["fund_code"].map(launch_map)
        df["scale"] = df["fund_code"].map(scale_map)
        print(f"  已加载成立时间/规模信息 (from Excel)")

    return df


# 列名 → 表头中文映射
COLUMN_LABELS = {
    "fund_code": "基金代码",
    "fund_name": "基金简称",
    "benchmark_name": "指数名称",
    "launch_date": "成立时间",
    "scale": "成立规模",
    "daily_change": "日涨跌幅",
    "day_20_change": "20日涨跌幅",
    "ytd_change": "YTD",
    "daily_excess": "日超额",
    "day_20_excess": "20日超额",
    "ytd_excess": "YTD超额",
}

PCT_COLUMNS = [
    "daily_change", "day_20_change", "ytd_change",
    "daily_excess", "day_20_excess", "ytd_excess",
]

_AUX_COLUMNS = ["month_6_change", "month_6_excess"]


# ═══════════════════════════════════════════════════════════
#  折线图数据：为每只基金计算近 90 日累计收益序列
# ═══════════════════════════════════════════════════════════

def _load_index_history() -> dict:
    """加载四大指数的历史收盘价。缓存缺失或过期时自动从 AKShare 拉取。"""
    index_data = {}
    for idx_code in ["HS300", "ZZ500", "ZZ1000", "CSI_ALL"]:
        path = os.path.join(INDEX_DIR, f"{idx_code}.parquet")

        # ── 已有缓存且新鲜 → 直接用 ──
        if os.path.exists(path):
            df = pd.read_parquet(path)
            df["date"] = pd.to_datetime(df["date"]).dt.date
            df = df.sort_values("date").reset_index(drop=True)
            index_data[idx_code] = df
            continue

        # ── 无缓存 → 尝试 AKShare 拉取 ──
        symbol = INDEX_AKSHARE_SYMBOLS.get(idx_code)
        if symbol is None:
            continue
        try:
            import akshare as ak
            raw = ak.stock_zh_index_daily(symbol=symbol)
            if raw is None or raw.empty:
                continue
            # 找日期列和收盘列
            date_col = next((c for c in raw.columns if "date" in str(c) or "日期" in str(c)), None)
            close_col = next((c for c in raw.columns if "close" in str(c) or "收盘" in str(c)), None)
            if date_col is None or close_col is None:
                continue
            df = pd.DataFrame()
            df["date"] = pd.to_datetime(raw[date_col]).dt.date
            df["index_value"] = pd.to_numeric(raw[close_col], errors="coerce")
            df = df.dropna(subset=["date", "index_value"])
            df = df.sort_values("date").reset_index(drop=True)
            if len(df) > 0:
                df.to_parquet(path, index=False)
                index_data[idx_code] = df
                print(f"  [OK] 已拉取 {INDEX_NAMES.get(idx_code, idx_code)} 指数: {len(df)} 条")
        except Exception as e:
            print(f"  [WARN] 无法拉取 {INDEX_NAMES.get(idx_code, idx_code)} 指数: {e}")

    return index_data


def _compute_cumulative_return(nav_series: pd.Series) -> pd.Series:
    """将净值序列转为累计收益率（%，以首日为基准 0）"""
    base = nav_series.iloc[0]
    if base == 0:
        return pd.Series([0.0] * len(nav_series))
    return (nav_series / base - 1) * 100


def build_chart_data(df: pd.DataFrame) -> dict:
    """
    为每只基金构建折线图 JSON 数据。
    返回: {fund_code: {dates: [...], fund: [...], benchmark: [...], index_name: ...}}
    """
    print("构建折线图数据...")

    # 加载指数数据
    index_data = _load_index_history()
    if not index_data:
        print("  [WARN] 无指数数据，跳过折线图")
        return {}

    chart_json = {}
    total = len(df)
    skipped = 0

    for i, (_, row) in enumerate(df.iterrows()):
        code = row["fund_code"]
        bench_idx = row.get("benchmark_index", "")
        bench_code = INDEX_CODE_MAP.get(bench_idx)

        # ── 加载基金净值 ──
        nav_path = os.path.join(NAV_DIR, f"{code}.parquet")
        if not os.path.exists(nav_path):
            skipped += 1
            continue
        try:
            nav = pd.read_parquet(nav_path)
            nav["date"] = pd.to_datetime(nav["date"]).dt.date
            nav = nav.dropna(subset=["unit_nav"]).sort_values("date")
            if len(nav) < 10:
                skipped += 1
                continue

            # 取最近 CHART_DAYS 个交易日
            nav = nav.tail(CHART_DAYS)
            dates = nav["date"].tolist()
            fund_cum = _compute_cumulative_return(nav["unit_nav"]).round(4).tolist()

            # ── 对齐基准指数 ──
            bench_cum = None
            if bench_code and bench_code in index_data:
                idx_df = index_data[bench_code]
                date_set = set(dates)
                idx_df = idx_df[idx_df["date"].isin(date_set)]
                if len(idx_df) >= 5:
                    idx_values = idx_df.set_index("date")["index_value"]
                    # 只保留基金有数据的日期
                    aligned = [idx_values.get(d) for d in dates]
                    aligned_series = pd.Series(aligned).interpolate().bfill().ffill()
                    if aligned_series.notna().sum() >= 5:
                        bench_cum = _compute_cumulative_return(
                            pd.Series(aligned_series.values)
                        ).round(4).tolist()

            chart_json[code] = {
                "dates": [str(d) for d in dates],
                "fund": fund_cum,
                "benchmark": bench_cum,
                "indexName": INDEX_NAMES.get(bench_idx, str(bench_idx)),
            }

        except Exception:
            skipped += 1

        if (i + 1) % 100 == 0:
            print(f"  [{i + 1}/{total}] ...")

    print(f"  折线图数据: {len(chart_json)} 只基金, 跳过 {skipped} 只")
    return chart_json


# ═══════════════════════════════════════════════════════════
#  表格准备 & HTML 生成
# ═══════════════════════════════════════════════════════════

def prepare_table(df):
    """筛选最新日期、排序、格式化（空值标注原因）"""
    latest = df["date"].max()
    df = df[df["date"] == latest].copy()
    df = df.sort_values("fund_code", ascending=True)

    columns = [
        "fund_code", "fund_name", "benchmark_index", "benchmark_name",
        "launch_date", "scale",
        "daily_change", "day_20_change", "ytd_change",
        "daily_excess", "day_20_excess", "ytd_excess",
    ]

    aux = [c for c in _AUX_COLUMNS if c in df.columns]
    df = df[[c for c in columns + aux if c in df.columns]]

    for c in PCT_COLUMNS:
        if c in df.columns:
            df[c] = df[c].apply(format_pct)

    for c in PCT_COLUMNS:
        if c in df.columns:
            df[c] = df.apply(lambda row: _format_cell(row[c], c, row), axis=1)

    df = df[[c for c in columns if c in df.columns]]
    return df, latest


def generate_html(df, latest_date, chart_data: dict):
    os.makedirs(os.path.dirname(OUTPUT_HTML), exist_ok=True)

    date_str = str(latest_date)
    labels = COLUMN_LABELS.copy()

    display_df = df.rename(columns=labels)
    # 不展示 benchmark_index 原始列
    if "benchmark_index" in display_df.columns:
        display_df = display_df.drop(columns=["benchmark_index"])

    benchmarks = ["HS300", "ZZ500", "ZZ1000", "CSI_ALL"]

    # ── 辅助：为单个 group 生成 <table> HTML ──
    def _build_group_table(g_df, g_display):
        """g_df: 含原始列（fund_code 等）；g_display: 已重命名列"""
        codes = g_df["fund_code"].tolist()
        table_html = g_display.to_html(
            index=False, escape=False, classes="fund-table", border=0
        )

        # 在 <tr> 上注入 data-code / data-chart 属性
        idx = 0

        def add_data_code(m):
            nonlocal idx
            code = codes[idx] if idx < len(codes) else ""
            idx += 1
            has_chart = "true" if code in chart_data else "false"
            return f'<tr data-code="{code}" data-chart="{has_chart}" class="{"clickable" if has_chart else ""}" style="cursor:{"pointer" if has_chart else "default"}">'

        parts = table_html.split("<tbody>")
        if len(parts) == 2:
            before_tbody = parts[0]
            after_tbody = parts[1]
            idx = 0
            after_tbody = re.sub(r"<tr>", add_data_code, after_tbody)
        else:
            before_tbody = table_html
            after_tbody = ""

        idx = 0
        after_tbody = re.sub(r"<tr>", add_data_code, after_tbody)
        return before_tbody + "<tbody>" + after_tbody

    # ── 构建各组表格 ──
    tables = {}
    counts = {}
    for bm in benchmarks:
        g_df = df[df["benchmark_index"] == bm]
        if g_df.empty:
            continue
        g_df = g_df.sort_values("fund_code")
        g_display = display_df.loc[g_df.index]
        tables[bm] = _build_group_table(g_df, g_display)
        counts[bm] = len(g_df)

    # ── 统计空值（用新字段名） ──
    empty_counts = {}
    for key in ["ytd_change", "day_20_change", "daily_change"]:
        col_label = labels.get(key, key)
        if col_label not in display_df.columns:
            continue
        non_pct = display_df[col_label].apply(
            lambda x: x if isinstance(x, str) and "empty-reason" in x else pd.NA
        )
        non_pct = non_pct.dropna()
        if len(non_pct) > 0:
            empty_counts[col_label] = len(non_pct)

    empty_note = ""
    if empty_counts:
        empty_note = '<div class="footnote"><p>说明：部分基金因成立时间不足，对应周期涨跌幅/超额为空，已在格内标注原因（如"成立不足1年"）。点击基金行可查看近 90 日累计收益走势图。</p></div>'

    chart_json_str = json.dumps(chart_data, ensure_ascii=False)

    # ── 构造 Tab 按钮 ──
    tab_btns = []
    tab_wrappers = []
    for i, bm in enumerate(benchmarks):
        if bm not in tables:
            continue
        active = " active" if i == 0 else ""
        tab_btns.append(
            f'<div class="tab-btn{active}" data-tab="{bm}">'
            f'{INDEX_NAMES.get(bm, bm)} ({counts[bm]})</div>'
        )
        tab_wrappers.append(
            f'<div class="table-wrapper{active}" id="table-{bm}">\n'
            f'{tables[bm]}\n</div>'
        )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>沪深300·中证500·中证1000·中证全指 指数增强基金绩效看板</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: "Microsoft YaHei", "PingFang SC", "Helvetica Neue", Arial, sans-serif;
        background: #0f1923; color: #d0d6dc;
        padding: 24px 36px; min-height: 100vh;
    }}
    .header {{
        text-align: center; margin-bottom: 20px; padding-bottom: 16px;
        border-bottom: 2px solid #1a2d3d;
    }}
    .header h1 {{ font-size: 24px; font-weight: 600; color: #e8ecf1; letter-spacing: 2px; }}
    .header .meta {{ font-size: 13px; color: #d0d6dc; margin-top: 8px; }}

    /* ── Tabs ── */
    .tabs {{ display: flex; gap: 4px; margin-bottom: 16px; flex-wrap: wrap; }}
    .tab-btn {{
        padding: 8px 20px; border: 1px solid #1e3040; border-radius: 4px 4px 0 0;
        background: #152028; color: #6a8090; cursor: pointer; font-size: 13px;
        transition: all 0.2s; font-family: inherit;
    }}
    .tab-btn:hover {{ color: #b0c0d0; border-color: #253d50; }}
    .tab-btn.active {{ background: #1a2e3d; color: #e8ecf1; border-color: #3d7eff; border-bottom-color: #1a2e3d; }}

    .table-wrapper {{
        background: #152028; border: 1px solid #1e3040; border-radius: 0 6px 6px 6px;
        overflow-x: auto; display: none;
    }}
    .table-wrapper.active {{ display: block; }}

    table {{ border-collapse: collapse; width: 100%; table-layout: auto; min-width: 1000px; }}
    thead th {{
        background: #1a2e3d; color: #8899aa;
        font-size: 12px; font-weight: 500; text-transform: uppercase;
        letter-spacing: 0.5px; padding: 12px 8px; text-align: center;
        border-bottom: 2px solid #253d50;
        position: sticky; top: 0; z-index: 10; white-space: nowrap;
    }}

    tbody td {{
        padding: 8px 6px; font-size: 12px; text-align: center;
        border-bottom: 1px solid #1a2a35;
        font-variant-numeric: tabular-nums; color: #c8d0d8;
    }}
    tbody tr {{ transition: background 0.15s; }}
    tbody tr:nth-child(even) {{ background: #182530; }}
    tbody tr:hover {{ background: #1c3040; }}
    tbody tr.clickable:hover {{ background: #1a3045; box-shadow: inset 2px 0 0 #3d7eff; }}

    tbody td:first-child {{
        color: #6a8090; font-family: "SF Mono", "Consolas", "Menlo", monospace;
        font-size: 13px; letter-spacing: 0.5px;
    }}
    tbody td:nth-child(2) {{ color: #d8dfe6; font-weight: 450; }}

    .empty-reason {{ color: #4a5d6e; font-size: 11px; font-weight: 400; }}

    /* ── 排序按钮 ── */
    .sort-btns {{
        display: inline-flex; flex-direction: column; vertical-align: middle;
        margin-left: 4px; line-height: 1; cursor: pointer; user-select: none;
    }}
    .sort-btn {{
        font-size: 10px; color: #3d5060; line-height: 1; padding: 0;
        transition: color 0.15s;
    }}
    .sort-btn:hover {{ color: #8899aa; }}
    .sort-btn.active {{ color: #3d7eff; }}
    th.sortable {{ cursor: pointer; }}
    th.sortable:hover {{ color: #b0c0d0; }}

    .footnote {{
        margin-top: 16px; padding: 10px 16px;
        background: #152028; border: 1px solid #1e3040; border-radius: 4px;
        color: #5a6f80; font-size: 11px;
    }}
    .footnote p {{ margin: 0; }}

    /* ── 弹窗 ── */
    .modal-overlay {{
        display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0;
        background: rgba(0,0,0,0.75); z-index: 1000;
        justify-content: center; align-items: center;
    }}
    .modal-overlay.active {{ display: flex; }}
    .modal {{
        background: #152028; border: 1px solid #253d50; border-radius: 8px;
        width: 860px; max-width: 95vw; max-height: 85vh;
        overflow: hidden; display: flex; flex-direction: column;
    }}
    .modal-header {{
        display: flex; justify-content: space-between; align-items: center;
        padding: 16px 24px; border-bottom: 1px solid #1e3040;
    }}
    .modal-header h2 {{ font-size: 16px; color: #e8ecf1; font-weight: 500; }}
    .modal-header .close-btn {{
        background: none; border: none; color: #5a6f80; font-size: 24px;
        cursor: pointer; padding: 0 4px; line-height: 1;
    }}
    .modal-header .close-btn:hover {{ color: #a0b0c0; }}
    .modal-body {{ padding: 8px 16px 16px 16px; flex: 1; min-height: 480px; }}
    #chart-container {{ width: 100%; height: 460px; }}

</style>
</head>
<body>

<div class="header">
    <h1>沪深300 · 中证500 · 中证1000 · 中证全指 指数增强基金</h1>
    <span class="meta">数据日期: {date_str} &nbsp;|&nbsp; 共 {len(display_df)} 只基金 &nbsp;|&nbsp;
      {", ".join(f"{INDEX_NAMES.get(bm, bm)} {counts.get(bm, 0)}只" for bm in benchmarks if bm in tables)}</span>
</div>

<div class="tabs">
    {"".join(tab_btns)}
</div>

{"".join(tab_wrappers)}

{empty_note}

<!-- ── 弹窗 ── -->
<div class="modal-overlay" id="modal-overlay">
  <div class="modal">
    <div class="modal-header">
      <h2 id="modal-title">累计收益走势</h2>
      <button class="close-btn" id="modal-close">&times;</button>
    </div>
    <div class="modal-body">
      <div id="chart-container"></div>
    </div>
  </div>
</div>

<script>
// ── 折线图数据 ──
var CHART_DATA = {chart_json_str};

// ── ECharts 实例 ──
var chartDom = document.getElementById('chart-container');
var myChart = echarts.init(chartDom, 'dark');
var modalOverlay = document.getElementById('modal-overlay');
var modalTitle = document.getElementById('modal-title');

// ── 弹窗开关 ──
function openModal(fundCode, fundName) {{
    var data = CHART_DATA[fundCode];
    if (!data) return;

    modalTitle.textContent = fundCode + ' ' + fundName;
    modalOverlay.classList.add('active');

    var series = [{{
        name: '基金累计收益',
        type: 'line',
        data: data.fund,
        smooth: true,
        symbol: 'none',
        lineStyle: {{ color: '#3d7eff', width: 2 }},
        areaStyle: {{
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                {{ offset: 0, color: 'rgba(61,126,255,0.15)' }},
                {{ offset: 1, color: 'rgba(61,126,255,0.02)' }}
            ])
        }},
    }}];

    if (data.benchmark) {{
        series.push({{
            name: data.indexName + ' (基准)',
            type: 'line',
            data: data.benchmark,
            smooth: true,
            symbol: 'none',
            lineStyle: {{ color: '#8899aa', width: 1.5, type: 'dashed' }},
        }});
    }}

    var option = {{
        backgroundColor: 'transparent',
        grid: {{ left: '8%', right: '5%', top: 20, bottom: 55 }},
        tooltip: {{
            trigger: 'axis',
            backgroundColor: '#1a2e3d',
            borderColor: '#253d50',
            textStyle: {{ color: '#d0d6dc', fontSize: 12 }},
            formatter: function(params) {{
                var html = '<b>' + params[0].axisValue + '</b><br/>';
                params.forEach(function(p) {{
                    html += '<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:' + p.color + ';margin-right:6px;"></span>';
                    html += p.seriesName + ': <b>' + (p.value >= 0 ? '+' : '') + p.value.toFixed(2) + '%</b><br/>';
                }});
                return html;
            }}
        }},
        xAxis: {{
            type: 'category',
            data: data.dates,
            axisLine: {{ lineStyle: {{ color: '#253d50' }} }},
            axisLabel: {{ color: '#5a6f80', fontSize: 10, rotate: 30,
                formatter: function(v) {{ return v.slice(5); }}
            }},
            axisTick: {{ show: false }},
            splitLine: {{ show: false }},
        }},
        yAxis: {{
            type: 'value',
            name: '%',
            axisLine: {{ show: false }},
            axisLabel: {{ color: '#5a6f80', fontSize: 11,
                formatter: function(v) {{ return (v >= 0 ? '+' : '') + v.toFixed(1) + '%'; }}
            }},
            splitLine: {{ lineStyle: {{ color: '#1a2a35' }} }},
        }},
        series: series,
        legend: {{
            bottom: 2,
            textStyle: {{ color: '#8899aa', fontSize: 11 }},
            data: series.map(function(s) {{ return s.name; }}),
        }},
    }};

    myChart.setOption(option, true);
    setTimeout(function() {{ myChart.resize(); }}, 100);
}}

function closeModal() {{
    modalOverlay.classList.remove('active');
}}

document.getElementById('modal-close').addEventListener('click', closeModal);
modalOverlay.addEventListener('click', function(e) {{
    if (e.target === modalOverlay) closeModal();
}});
document.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape') closeModal();
}});

// ── 表格行点击 ──
document.querySelectorAll('tr[data-chart="true"]').forEach(function(tr) {{
    tr.addEventListener('click', function() {{
        var code = this.getAttribute('data-code');
        var name = this.querySelector('td:nth-child(2)').textContent.trim();
        openModal(code, name);
    }});
}});

// ── 窗口缩放时重绘 ──
window.addEventListener('resize', function() {{
    if (modalOverlay.classList.contains('active')) myChart.resize();
}});

// ── Tab 切换 ──
(function() {{
    var tabBtns = document.querySelectorAll('.tab-btn');
    tabBtns.forEach(function(btn) {{
        btn.addEventListener('click', function() {{
            var tab = this.getAttribute('data-tab');
            tabBtns.forEach(function(b) {{ b.classList.remove('active'); }});
            this.classList.add('active');
            document.querySelectorAll('.table-wrapper').forEach(function(t) {{ t.classList.remove('active'); }});
            document.getElementById('table-' + tab).classList.add('active');
        }});
    }});
}})();

// ── 表格排序（每张表独立） ──
(function() {{
    document.querySelectorAll('.fund-table').forEach(function(table) {{
        var tbody = table.querySelector('tbody');
        var headers = table.querySelectorAll('th');
        var sortState = {{}};

        headers.forEach(function(th, colIdx) {{
            if (colIdx < 3) return; // 跳过代码、简称、指数

            th.classList.add('sortable');
            var btns = document.createElement('span');
            btns.className = 'sort-btns';
            btns.innerHTML = '<span class="sort-btn sort-asc">&#9650;</span><span class="sort-btn sort-desc">&#9660;</span>';
            th.appendChild(document.createTextNode(' '));
            th.appendChild(btns);

            var ascBtn = btns.querySelector('.sort-asc');
            var descBtn = btns.querySelector('.sort-desc');

            ascBtn.addEventListener('click', function(e) {{
                e.stopPropagation();
                Object.keys(sortState).forEach(function(k) {{ sortState[k] = null; }});
                resetAllArrows(table);
                sortState[colIdx] = 'asc';
                ascBtn.classList.add('active');
                sortTable(table, colIdx, 'asc');
            }});

            descBtn.addEventListener('click', function(e) {{
                e.stopPropagation();
                Object.keys(sortState).forEach(function(k) {{ sortState[k] = null; }});
                resetAllArrows(table);
                sortState[colIdx] = 'desc';
                descBtn.classList.add('active');
                sortTable(table, colIdx, 'desc');
            }});

            th.addEventListener('click', function(e) {{
                Object.keys(sortState).forEach(function(k) {{ sortState[k] = null; }});
                resetAllArrows(table);
                sortTable(table, 0, null);
            }});
        }});
    }});

    function resetAllArrows(table) {{
        table.querySelectorAll('.sort-btn').forEach(function(b) {{ b.classList.remove('active'); }});
    }}

    function parseCellValue(td) {{
        var span = td.querySelector('span');
        var text = span ? span.textContent.trim() : td.textContent.trim();
        var pctMatch = text.match(/^([+-]?\\d+\\.?\\d*)%?$/);
        if (pctMatch) return parseFloat(pctMatch[1]);
        if (text && !text.match(/^[+-]?\\d/)) return -Infinity;
        var num = parseFloat(text);
        return isNaN(num) ? -Infinity : num;
    }}

    function sortTable(table, colIdx, dir) {{
        var tbody = table.querySelector('tbody');
        var rows = Array.from(tbody.querySelectorAll('tr'));
        if (!dir) {{
            rows.sort(function(a, b) {{
                var aCode = a.querySelector('td:first-child').textContent.trim();
                var bCode = b.querySelector('td:first-child').textContent.trim();
                return aCode.localeCompare(bCode);
            }});
        }} else {{
            rows.sort(function(a, b) {{
                var aVal = parseCellValue(a.querySelectorAll('td')[colIdx]);
                var bVal = parseCellValue(b.querySelectorAll('td')[colIdx]);
                if (dir === 'asc') return aVal - bVal;
                return bVal - aVal;
            }});
        }}
        rows.forEach(function(r) {{ tbody.appendChild(r); }});
    }}
}})();
</script>
</body>
</html>
"""

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    if empty_counts:
        print()
        print("  空值标注统计:")
        for col_label, count in empty_counts.items():
            print(f"    {col_label}: {count} 只")
    print(f"  折线图覆盖: {len(chart_data)} 只基金")
    print(f"[OK] HTML 已生成: {OUTPUT_HTML}")


def main():
    print("=" * 60)
    print("Step 4  生成基金网页")
    print("=" * 60)

    df = load_data()
    if df.empty:
        return

    table, latest_date = prepare_table(df)

    # 构建折线图数据
    chart_data = build_chart_data(df)

    generate_html(table, latest_date, chart_data)

    print("\n完成!")


if __name__ == "__main__":
    main()
