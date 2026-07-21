import calendar
import os
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
import akshare as ak

from config import (
    DATA_DIR,
    NAV_DIR,
    INDEX_DIR,
    RETURN_DIR,
    FUND_MASTER_PATH,
    FUND_RETURN_PATH,
    INDEX_RETURN_PATH,
    EXCESS_RETURN_PATH,
    INDEX_NAMES,
    INDEX_AKSHARE_SYMBOLS,
    INDEX_CSI_CODES,
    INDEX_CACHE_MAX_AGE_HOURS,
    REQUEST_DELAY,
    MAX_RETRIES,
)
from utils import (
    find_col,
    format_seconds,
    safe_read_parquet,
    safe_write_parquet,
)


def _subtract_months(d: date, n: int) -> date:
    """日期往回推 n 个自然月，自动做月末截断"""
    year = d.year
    month = d.month - n
    while month <= 0:
        month += 12
        year -= 1
    max_day = calendar.monthrange(year, month)[1]
    day = min(d.day, max_day)
    return date(year, month, day)


def _find_nearest_trading_day(dates: pd.Series, target: date) -> date | None:
    """在交易日序列中找到 ≤ target 的最近一个日期（二分查找，O(log n)）"""
    # dates 已在 _calculate_performance 中确保升序排列
    pos = np.searchsorted(dates.values, target, side="right") - 1
    if pos < 0:
        return None
    return dates.iloc[pos]


def ensure_dirs():
    for d in [DATA_DIR, NAV_DIR, INDEX_DIR, RETURN_DIR]:
        os.makedirs(d, exist_ok=True)


# 1. 加载基金池

def load_fund_master() -> pd.DataFrame:
    df = safe_read_parquet(FUND_MASTER_PATH)
    if df is None:
        print(f"✗ 基金主表不存在: {FUND_MASTER_PATH}")
        print("  请先运行 01_build_fund_pool.py")
        return pd.DataFrame()
    df["fund_code"] = df["fund_code"].astype(str).str.zfill(6)

    print(f"读取基金池: {FUND_MASTER_PATH}")
    print(f"共 {len(df)} 只基金\n")

    for idx_code in ["HS300", "ZZ500", "ZZ1000", "CSI_ALL"]:
        count = len(df[df["benchmark_index"] == idx_code])
        if count > 0:
            label = INDEX_NAMES.get(idx_code, idx_code)
            print(f"  {label:<8} {count:>4} 只")

    print()
    return df


# 2. 区间涨跌幅计算（App 口径）

def _calculate_max_drawdown(df: pd.DataFrame) -> float | None:
    """从复权净值序列计算历史最大回撤（负值，如 -0.15 表示 15% 回撤）"""
    adj = df["adj_nav"].dropna()
    if len(adj) < 2:
        return None
    peak = adj.expanding().max()
    drawdown = (adj / peak - 1).min()
    return float(drawdown)


def _calculate_risk_metrics(df: pd.DataFrame, max_drawdown: float | None) -> dict:
    """
    计算年化收益率、年化波动率、夏普比率、卡玛比率。

    基于全量复权净值的日收益率序列。
    返回 dict 含 annual_return, annual_volatility, sharpe_ratio, calmar_ratio。
    """
    result = {
        "annual_return": None,
        "annual_volatility": None,
        "sharpe_ratio": None,
        "calmar_ratio": None,
    }

    adj = df["adj_nav"].dropna()
    if len(adj) < 20:
        return result

    daily_returns = adj.pct_change().dropna()
    N = len(daily_returns)
    if N < 10:
        return result

    # 年化收益率（几何年化）
    cumulative = adj.iloc[-1] / adj.iloc[0] - 1
    annual_return = (1 + cumulative) ** (252 / N) - 1
    result["annual_return"] = float(annual_return)

    # 年化波动率
    annual_vol = float(daily_returns.std()) * np.sqrt(252)
    result["annual_volatility"] = float(annual_vol)

    # 夏普比率
    from config import RISK_FREE_RATE
    if annual_vol > 0:
        result["sharpe_ratio"] = float((annual_return - RISK_FREE_RATE) / annual_vol)

    # 卡玛比率
    if max_drawdown is not None and max_drawdown < 0:
        result["calmar_ratio"] = float(annual_return / abs(max_drawdown))

    return result


def _calculate_performance(
    nav_df: pd.DataFrame,
) -> dict:
 
    df = nav_df.sort_values("date").reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    # 去重：同一天保留最后一条（避免重复日期导致 dict 覆盖异常）
    df = df.drop_duplicates(subset=["date"], keep="last")

    latest_date: date = df["date"].max()
    dates: pd.Series = df["date"]

    # 提前建索引，避免每次 _change 内重复 dict(zip(...))
    unit_values: dict = dict(zip(df["date"], df["unit_nav"])) if "unit_nav" in df.columns else {}
    adj_values: dict = dict(zip(df["date"], df["adj_nav"])) if "adj_nav" in df.columns else {}

    # 提前取 latest 净值，避免闭包内重复 dict 查找
    latest_unit: float | None = unit_values.get(latest_date) if unit_values else None
    latest_adj: float | None = adj_values.get(latest_date) if adj_values else None

    def _change(target: date | None, values: dict, latest_val: float | None) -> float | None:
        """给定起始日期和净值字典，计算 (latest / base - 1)"""
        if target is None or latest_val is None:
            return None
        t = _find_nearest_trading_day(dates, target)
        if t is None:
            return None
        base = values.get(t)
        if base is None or base == 0:
            return None
        return latest_val / base - 1

    result: dict = {"date": latest_date}

    # ── 短期：单位净值 ──
    if unit_values and latest_unit is not None:
        # 日涨跌
        prev_dates = dates[dates < latest_date]
        if len(prev_dates) > 0:
            prev_date = prev_dates.max()
            prev_val = unit_values.get(prev_date)
            if prev_val and prev_val != 0:
                result["daily_change"] = latest_unit / prev_val - 1
            else:
                result["daily_change"] = None
        else:
            result["daily_change"] = None

        # 近一周
        result["week_change"] = _change(
            latest_date - timedelta(days=7), unit_values, latest_unit
        )
    else:
        result["daily_change"] = None
        result["week_change"] = None

    # ── 中长期：复权净值 ──
    if adj_values and latest_adj is not None:
        result["month_1_change"] = _change(
            _subtract_months(latest_date, 1), adj_values, latest_adj
        )
        result["month_3_change"] = _change(
            _subtract_months(latest_date, 3), adj_values, latest_adj
        )
        result["month_6_change"] = _change(
            _subtract_months(latest_date, 6), adj_values, latest_adj
        )
        result["ytd_change"] = _change(
            date(latest_date.year - 1, 12, 31), adj_values, latest_adj
        )
        result["year_1_change"] = _change(
            _subtract_months(latest_date, 12), adj_values, latest_adj
        )
        result["year_3_change"] = _change(
            _subtract_months(latest_date, 36), adj_values, latest_adj
        )
        result["year_5_change"] = _change(
            _subtract_months(latest_date, 60), adj_values, latest_adj
        )

        # 成立以来：取第一条 adj_nav 非空的日期
        first_valid_date: date = (
            df.dropna(subset=["adj_nav"])["date"].min()
        )
        if (
            first_valid_date
            and first_valid_date in adj_values
            and first_valid_date != latest_date
        ):
            result["since_launch_change"] = (
                latest_adj / adj_values[first_valid_date] - 1
            )
        else:
            result["since_launch_change"] = None
    else:
        for key in [
            "month_1_change", "month_3_change", "month_6_change",
            "ytd_change", "year_1_change", "year_3_change", "year_5_change",
            "since_launch_change",
        ]:
            result[key] = None

    # ── 最大回撤（基于全量复权净值） ──
    result["max_drawdown"] = _calculate_max_drawdown(df)

    # ── 风险调整指标（年化收益 / 波动率 / Sharpe / Calmar） ──
    risk = _calculate_risk_metrics(df, result["max_drawdown"])
    result.update(risk)

    return result


def _load_fund_nav(fund_code: str) -> pd.DataFrame | None:
    path = os.path.join(NAV_DIR, f"{fund_code}.parquet")
    df = safe_read_parquet(path)
    if df is not None:
        df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def calculate_fund_performance(fund_master: pd.DataFrame) -> pd.DataFrame:
    """批量计算所有基金的区间涨跌幅（每只基金一行）"""
    print("=" * 60)
    print("Step 1 / 4  计算基金涨跌幅（App 口径）")
    print("=" * 60)

    # 加载已有涨跌幅缓存（避免重复计算 NAV 未变化的基金）
    cached_returns: dict[str, dict] = {}
    existing_return = safe_read_parquet(FUND_RETURN_PATH)
    if existing_return is not None and not existing_return.empty:
        for _, r in existing_return.iterrows():
            cached_returns[r["fund_code"]] = r.to_dict()
        print(f"  已缓存涨跌幅: {len(cached_returns)} 只基金")

    results: list[dict] = []
    skipped: list[str] = []
    cached_skip = 0
    total = len(fund_master)
    t_start = time.time()

    for i, (_, row) in enumerate(fund_master.iterrows()):
        code = row["fund_code"]

        elapsed = time.time() - t_start
        avg = elapsed / (i + 1) if i > 0 else 0
        eta = format_seconds(avg * (total - i - 1))
        pct = (i + 1) / total * 100

        print(
            f"\r  [{i + 1:>4}/{total} {pct:>4.0f}%]  "
            f"✓{len(results):>4}  ↻{cached_skip:>3}  ✗{len(skipped):>3}  "
            f"剩余≈{eta:<8s}  "
            f"{code}",
            end="", flush=True,
        )

        nav = _load_fund_nav(code)
        if nav is None or nav.empty:
            skipped.append(code)
            continue

        # 至少需要 unit_nav（短期）或 adj_nav（中长期）之一
        has_unit = "unit_nav" in nav.columns
        has_adj = "adj_nav" in nav.columns
        if not has_unit and not has_adj:
            skipped.append(code)
            continue

        keep_cols = ["date"]
        if has_unit:
            keep_cols.append("unit_nav")
        if has_adj:
            keep_cols.append("adj_nav")
        nav_filtered = nav[keep_cols].dropna(
            subset=[c for c in keep_cols if c != "date"], how="all"
        )

        if len(nav_filtered) < 2:
            skipped.append(code)
            continue

        nav_last_date = nav_filtered["date"].max()
        nav_rows = len(nav_filtered)

        # 检查缓存：日期一致 & 行数一致 → 复用
        if code in cached_returns:
            cached = cached_returns[code]
            if (cached.get("date") == nav_last_date
                    and cached.get("_nav_rows", 0) == nav_rows):
                results.append(cached)
                cached_skip += 1
                continue

        try:
            perf = _calculate_performance(nav_filtered)
            perf["fund_code"] = code
            perf["_nav_rows"] = nav_rows  # 辅助缓存校验，不会写入最终输出
            results.append(perf)
        except Exception:
            skipped.append(code)

    print()

    elapsed = time.time() - t_start
    print(f"\n  耗时: {format_seconds(elapsed)}")
    print(f"  ✓ 新计算: {len(results) - cached_skip} 只")
    print(f"  ↻ 缓存复用: {cached_skip} 只")
    print(f"  ✗ 跳过: {len(skipped)} 只")

    if skipped:
        print(f"  跳过示例: {skipped[:10]}")

    if not results:
        print("\n⚠ 没有基金可计算涨跌幅\n")
        return pd.DataFrame()

    df = pd.DataFrame(results)
    # 去掉缓存校验辅助列
    if "_nav_rows" in df.columns:
        df = df.drop(columns=["_nav_rows"])
    print(f"  最新日期: {df['date'].max()}\n")
    return df


# 3. 指数涨跌幅计算

def _fetch_index_history(index_code: str) -> pd.DataFrame | None:
    symbol = INDEX_AKSHARE_SYMBOLS.get(index_code)
    if symbol is None:
        print(f"  ✗ 未知指数代码: {index_code}")
        return None

    for attempt in range(1 + MAX_RETRIES):
        try:
            df = ak.stock_zh_index_daily(symbol=symbol)
            if df is None or df.empty:
                return None

            date_col = find_col(df, "date", "日期")
            close_col = find_col(df, "close", "收盘")

            if date_col is None or close_col is None:
                return None

            result = pd.DataFrame()
            result["date"] = pd.to_datetime(df[date_col]).dt.date
            result["index_value"] = pd.to_numeric(
                df[close_col], errors="coerce"
            )
            result = result.dropna(subset=["date", "index_value"])
            result = result.sort_values("date").reset_index(drop=True)
            return result

        except Exception:
            if attempt < MAX_RETRIES:
                time.sleep(REQUEST_DELAY * 2)

    return None


def _load_or_fetch_index(index_code: str) -> pd.DataFrame | None:
    path = os.path.join(INDEX_DIR, f"{index_code}.parquet")
    label = INDEX_NAMES.get(index_code, index_code)

    existing = safe_read_parquet(path)
    if existing is not None and not existing.empty:
        df = existing
        df["date"] = pd.to_datetime(df["date"]).dt.date
        latest_data_date = df["date"].max()
        days_since_data = (date.today() - latest_data_date).days

        # 策略: 如果缓存的最新数据日期在 1 天内（今天/昨天），直接复用
        # 这覆盖了周末场景（周五数据，周六运行 → days=1，不重新下载）
        if days_since_data <= 1:
            return df

        # 数据滞后 > 1 天，且文件修改时间 < 24h → 可能是今天已经试过但市场没开盘
        age_hours = (time.time() - os.path.getmtime(path)) / 3600
        if age_hours < INDEX_CACHE_MAX_AGE_HOURS:
            return df

        print(f"  ⏳ {label} 缓存滞后 {days_since_data}d（{age_hours:.0f}h），重新获取...")
    else:
        print(f"  ⏳ {label} 本地无数据，从 AKShare 获取...")

    time.sleep(REQUEST_DELAY)

    df = _fetch_index_history(index_code)
    if df is None or df.empty:
        print(f"  ✗ {label} 获取失败")
        return None

    safe_write_parquet(df, path)
    print(f"  ✓ {label} 已保存: {path}（{len(df)} 条）")
    return df


def _read_dividend_yield_cache() -> dict[str, float]:
    """读取股息率缓存，返回 {index_code: dividend_yield}（仅当天有效）"""
    cache_path = os.path.join(INDEX_DIR, "dividend_yield.parquet")
    cache = safe_read_parquet(cache_path)
    if cache is None or cache.empty:
        return {}
    result: dict[str, float] = {}
    today_val = date.today()
    for _, row in cache.iterrows():
        cache_date = pd.Timestamp(row["cache_date"]).date()
        if cache_date == today_val:
            result[row["index_code"]] = float(row["dividend_yield"])
    return result


def _write_dividend_yield_cache(data: dict[str, float | None]):
    """批量写入股息率缓存（一次写盘）"""
    cache_path = os.path.join(INDEX_DIR, "dividend_yield.parquet")
    rows = []
    today_val = date.today()
    for index_code, dy in data.items():
        if dy is not None:
            rows.append({
                "index_code": index_code,
                "dividend_yield": dy,
                "cache_date": today_val,
            })
    if not rows:
        return
    new_df = pd.DataFrame(rows)
    safe_write_parquet(new_df, cache_path)


def _fetch_index_dividend_yield(index_code: str) -> float | None:
    """从中证指数公司获取指数最新股息率（小数），不含缓存逻辑。"""
    csi_code = INDEX_CSI_CODES.get(index_code)
    if csi_code is None:
        return None

    for attempt in range(1 + MAX_RETRIES):
        try:
            df = ak.stock_zh_index_value_csindex(symbol=csi_code)
            if df is None or df.empty:
                return None

            # 列名: 日期 / 市盈率1 / 市盈率2 / 股息率1 / 股息率2
            dy_col = find_col(df, "股息率1")
            if dy_col is None:
                return None

            latest = df[dy_col].dropna()
            if latest.empty:
                return None
            return float(latest.iloc[-1]) / 100  # 百分比转小数
        except Exception:
            if attempt < MAX_RETRIES:
                time.sleep(REQUEST_DELAY * 2)

    return None


def calculate_index_performance() -> pd.DataFrame:
    """
    计算四大指数的区间涨跌幅 + 股息率（每个指数一行）。

    Alpha 解释:
    - 基金使用 adj_nav（含分红再投资），指数使用 price index（不含分红）
    - 因此 fund_return - index_return ≈ 增强收益 + 分红收益
    - 本函数额外获取指数股息率，供超额计算做股息修正
    """
    print("=" * 60)
    print("Step 2 / 4  计算指数涨跌幅（App 口径）")
    print("=" * 60)

    # 先读股息率缓存（当天有效）
    dy_cache = _read_dividend_yield_cache()
    dy_new: dict[str, float | None] = {}  # 本次新获取的，最后批量写盘

    results: list[dict] = []

    for index_code in ["HS300", "ZZ500", "ZZ1000", "CSI_ALL"]:
        label = INDEX_NAMES.get(index_code, index_code)

        nav = _load_or_fetch_index(index_code)
        if nav is None or nav.empty:
            print(f"  ✗ {label} 跳过（无数据）")
            continue

        try:
            # 指数收盘价同时充当 unit_nav 和 adj_nav
            nav = nav.rename(columns={"index_value": "adj_nav"})
            nav["unit_nav"] = nav["adj_nav"]
            perf = _calculate_performance(nav)

            # 获取股息率：缓存优先，未命中则请求 API
            if index_code in dy_cache:
                dy = dy_cache[index_code]
            else:
                dy = _fetch_index_dividend_yield(index_code)
                dy_new[index_code] = dy

            if dy is not None:
                print(f"  ✓ {label}  日期: {perf['date']}  股息率: {dy * 100:.2f}%")
            else:
                print(f"  ✓ {label}  日期: {perf['date']}  股息率: N/A")

            perf["index_code"] = index_code
            perf["index_name"] = label
            perf["dividend_yield"] = dy
            results.append(perf)
        except Exception as e:
            print(f"  ✗ {label} 计算失败: {e}")

    # 批量写入本次新获取的股息率
    if dy_new:
        _write_dividend_yield_cache(dy_new)

    print()

    if not results:
        print("⚠ 没有指数数据可计算\n")
        return pd.DataFrame()

    df = pd.DataFrame(results)
    return df


# 4. 超额（Alpha）计算

# 基金与指数共有的涨跌幅字段（不含 since_launch）
_PERF_FIELDS = [
    "daily_change", "week_change",
    "month_1_change", "month_3_change", "month_6_change",
    "ytd_change",
    "year_1_change", "year_3_change", "year_5_change",
]

_EXCESS_FIELDS = [
    "daily_excess", "week_excess",
    "month_1_excess", "month_3_excess", "month_6_excess",
    "ytd_excess",
    "year_1_excess", "year_3_excess", "year_5_excess",
]

# 各区间对应的近似年限（用于股息修正）
_PERIOD_YEARS_FIXED: dict[str, float] = {
    "daily_change": 1 / 252,       # ~1 个交易日
    "week_change": 5 / 252,        # ~5 个交易日
    "month_1_change": 1 / 12,
    "month_3_change": 3 / 12,
    "month_6_change": 6 / 12,
    "year_1_change": 1.0,
    "year_3_change": 3.0,
    "year_5_change": 5.0,
    # ytd_change: 根据实际日期动态计算（见下文）
}


def _ytd_year_fraction(latest_date: date) -> float:
    """YTD 已过去年份比例（用于股息修正），例如 7 月中旬 ≈ 0.54"""
    year_start = date(latest_date.year, 1, 1)
    year_end = date(latest_date.year, 12, 31)
    days_elapsed = (latest_date - year_start).days
    days_total = (year_end - year_start).days + 1
    return max(days_elapsed / days_total, 0.01)


def calculate_excess_performance(
    fund_perf: pd.DataFrame,
    index_perf: pd.DataFrame,
    fund_master: pd.DataFrame,
) -> pd.DataFrame:
    """
    计算超额收益（Alpha）。

    两个口径：
    1. excess（总超额）= 基金复权收益 - 价格指数收益
       = 增强收益 + 分红收益（含权）
    2. alpha（纯增强超额）= excess - 股息率修正
       ≈ 剔除分红贡献后的增强收益

    短期（日/周）股息修正可忽略不计。
    """
    print("=" * 60)
    print("Step 3 / 4  计算超额（Alpha）")
    print("=" * 60)

    if fund_perf.empty:
        print("✗ 基金数据为空\n")
        return pd.DataFrame()
    if index_perf.empty:
        print("✗ 指数数据为空\n")
        return pd.DataFrame()

    # 基金元信息
    info = fund_master[[
        "fund_code", "fund_name", "share_class",
        "benchmark_index", "benchmark_name",
    ]].copy()
    info["fund_code"] = info["fund_code"].astype(str).str.zfill(6)

    # 基金涨跌幅 + 元信息
    merged = fund_perf.merge(info, on="fund_code", how="left")

    # 股息率映射
    dy_map: dict[str, float] = {}
    if "dividend_yield" in index_perf.columns:
        dy_map = index_perf.set_index("index_code")["dividend_yield"].to_dict()
    merged["dividend_yield"] = merged["benchmark_index"].map(dy_map)

    # 最新日期（用于 YTD 动态年限）
    latest_date_val: date = fund_perf["date"].max()
    ytd_frac = _ytd_year_fraction(latest_date_val)

    # 向量化计算超额 & 纯 Alpha
    for perf_field, excess_field in zip(_PERF_FIELDS, _EXCESS_FIELDS):
        # 指数涨跌幅映射
        idx_map = index_perf.set_index("index_code")[perf_field].to_dict()

        # 总超额
        merged[excess_field] = (
            merged[perf_field] - merged["benchmark_index"].map(idx_map)
        )

        # 纯增强 Alpha = 总超额 - 股息复利修正
        # 使用复利: (1 + dy)^years - 1，而非线性 dy * years
        # 短期（日/周）股息修正 ≈ 0，长期复利效应不可忽略
        if perf_field == "ytd_change":
            years = ytd_frac
        else:
            years = _PERIOD_YEARS_FIXED.get(perf_field, 0)

        alpha_field = excess_field.replace("excess", "alpha")
        merged[alpha_field] = (
            merged[excess_field]
            - (
                (1.0 + merged["dividend_yield"].fillna(0)) ** years
                - 1.0
            )
        )

    # 输出列
    _ALPHA_FIELDS = [f.replace("excess", "alpha") for f in _EXCESS_FIELDS]
    out_cols = [
        "fund_code", "fund_name", "share_class",
        "benchmark_index", "benchmark_name", "date",
        "dividend_yield",
        *_PERF_FIELDS,
        "since_launch_change", "max_drawdown",
        "annual_return", "annual_volatility", "sharpe_ratio", "calmar_ratio",
        *_EXCESS_FIELDS,
        *_ALPHA_FIELDS,
    ]
    out_cols = [c for c in out_cols if c in merged.columns]
    result = merged[out_cols].copy()

    # 排序
    idx_order = {"HS300": 0, "ZZ500": 1, "ZZ1000": 2, "CSI_ALL": 3}
    result["_sort"] = result["benchmark_index"].map(idx_order).fillna(9)
    result = result.sort_values(["_sort", "fund_code"]).drop(
        columns=["_sort"]
    ).reset_index(drop=True)

    codes = result["fund_code"].nunique()
    latest = result["date"].max()
    print(f"  基金数: {codes}  最新日期: {latest}")
    print(f"  超额时段: {len(_PERF_FIELDS)} 个")
    if dy_map:
        print(f"  股息修正: 已应用（{len(dy_map)} 个指数有股息率数据）")
    print()

    return result


# 5. 保存

def _pct(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "     N/A"
    return f"{v * 100:>+7.2f}%"


def save_results(
    fund_perf: pd.DataFrame,
    index_perf: pd.DataFrame,
    excess_perf: pd.DataFrame,
):
    """保存三类涨跌幅数据到 data/return/"""
    print("=" * 60)
    print("Step 4 / 4  保存结果")
    print("=" * 60)

    os.makedirs(RETURN_DIR, exist_ok=True)

    if not fund_perf.empty:
        safe_write_parquet(fund_perf, FUND_RETURN_PATH)
        print(f"✓ 基金涨跌幅: {FUND_RETURN_PATH}")
        print(f"  {len(fund_perf)} 只基金, 最新日期 {fund_perf['date'].max()}")
    else:
        print("⚠ 基金数据为空，跳过")

    if not index_perf.empty:
        safe_write_parquet(index_perf, INDEX_RETURN_PATH)
        print(f"✓ 指数涨跌幅: {INDEX_RETURN_PATH}")
        print(f"  {len(index_perf)} 个指数")
    else:
        print("⚠ 指数数据为空，跳过")

    if not excess_perf.empty:
        safe_write_parquet(excess_perf, EXCESS_RETURN_PATH)
        print(f"✓ 超额收益 (Alpha): {EXCESS_RETURN_PATH}")
        print(f"  {len(excess_perf)} 只基金")

        latest = excess_perf["date"].max()
        latest_df = excess_perf[excess_perf["date"] == latest]

        print(f"\n{'─' * 140}")
        print(f"预览（最新日期: {latest}，前 12 行）:")
        print(f"{'─' * 140}")

        # 表头: 收益 + 股息率 + 超额 + Alpha
        short_perf = [
            ("日", "daily_change"), ("周", "week_change"),
            ("1月", "month_1_change"), ("3月", "month_3_change"),
            ("6月", "month_6_change"), ("YTD", "ytd_change"),
            ("1年", "year_1_change"), ("3年", "year_3_change"),
            ("5年", "year_5_change"),
        ]
        short_alpha = [
            ("日α", "daily_alpha"), ("周α", "week_alpha"),
            ("1月α", "month_1_alpha"), ("3月α", "month_3_alpha"),
            ("6月α", "month_6_alpha"), ("YTDα", "ytd_alpha"),
            ("1年α", "year_1_alpha"), ("3年α", "year_3_alpha"),
            ("5年α", "year_5_alpha"),
        ]

        has_dy = "dividend_yield" in latest_df.columns
        hdr = f"{'代码':<8} {'名称':<20} "
        if has_dy:
            hdr += f"{'股息率':>6} "
        for label, _ in short_perf:
            hdr += f"{label:>7} "
        for label, _ in short_alpha:
            hdr += f"{label:>7} "
        print(hdr)
        print(f"{'─' * 140}")

        for _, r in latest_df.head(12).iterrows():
            line = (
                f"{r['fund_code']:<8} "
                f"{str(r.get('fund_name', ''))[:20]:<20} "
            )
            if has_dy:
                dy = r.get("dividend_yield")
                if dy is not None and not (isinstance(dy, float) and np.isnan(dy)):
                    line += f"{dy * 100:>5.2f}% "
                else:
                    line += f"{'N/A':>6} "
            for _, col in short_perf:
                line += f"{_pct(r.get(col))} "
            for _, col in short_alpha:
                line += f"{_pct(r.get(col))} "
            print(line)

        if len(latest_df) > 12:
            print(f"  ... (共 {len(latest_df)} 只)")
        print()
    else:
        print("⚠ 超额数据为空，跳过")


# 主入口

def main():
    print("\n" + "█" * 60)
    print("█  指数增强基金 涨跌幅 & Alpha 计算")
    print("█  口径: App 区间涨跌幅模型（天天基金 / 支付宝 / 雪球）")
    print("█  净值: 短期 unit_nav | 中长期 adj_nav")
    print("█  数据: 天天基金 + AKShare 指数行情")
    print("█" * 60)

    ensure_dirs()

    fund_master = load_fund_master()
    if fund_master.empty:
        print("基金池为空，请先运行 01_build_fund_pool.py")
        return

    fund_perf = calculate_fund_performance(fund_master)
    index_perf = calculate_index_performance()
    excess_perf = calculate_excess_performance(
        fund_perf, index_perf, fund_master
    )

    save_results(fund_perf, index_perf, excess_perf)

    print("█" * 60)
    print("█  涨跌幅计算完成 ✓")
    if not excess_perf.empty:
        latest = excess_perf["date"].max()
        funds = excess_perf["fund_code"].nunique()
        print(f"█  {funds} 只基金, 最新日期 {latest}")
    print(f"█  输出目录: {RETURN_DIR}")
    print("█" * 60)
    print("\n下一步: 运行 04_generate_html.py 生成展示页面\n")


if __name__ == "__main__":
    main()
