"""
一次性回填脚本：根据已有 NAV 数据，重新计算所有历史日期的收益/超额
运行后 data/return/excess_return.parquet 将包含全部历史交易日数据
"""
import os, sys, time
import numpy as np
import pandas as pd
from datetime import date

# 复用 03 的核心计算函数
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (
    NAV_DIR, INDEX_DIR, RETURN_DIR, FUND_MASTER_PATH,
    FUND_RETURN_PATH, INDEX_RETURN_PATH, EXCESS_RETURN_PATH,
    INDEX_NAMES,
)
from utils import safe_read_parquet, safe_write_parquet, format_seconds


def load_all_nav_dates() -> set[date]:
    """扫描所有 NAV 文件，收集所有出现过的日期"""
    all_dates = set()
    nav_files = sorted([f for f in os.listdir(NAV_DIR) if f.endswith('.parquet')])
    print(f"扫描 {len(nav_files)} 个 NAV 文件...")
    for f in nav_files:
        path = os.path.join(NAV_DIR, f)
        df = safe_read_parquet(path)
        if df is not None and not df.empty and 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date']).dt.date
            all_dates.update(df['date'].unique())
    return all_dates


def load_fund_master() -> pd.DataFrame:
    df = safe_read_parquet(FUND_MASTER_PATH)
    if df is None:
        print(f"✗ 基金主表不存在: {FUND_MASTER_PATH}")
        return pd.DataFrame()
    df["fund_code"] = df["fund_code"].astype(str).str.zfill(6)
    return df


def _subtract_months(d: date, n: int) -> date:
    year = d.year
    month = d.month - n
    while month <= 0:
        month += 12
        year -= 1
    import calendar
    max_day = calendar.monthrange(year, month)[1]
    day = min(d.day, max_day)
    return date(year, month, day)


def _find_nearest_trading_day(dates: pd.Series, target: date) -> date | None:
    pos = np.searchsorted(dates.values, target, side="right") - 1
    if pos < 0:
        return None
    return dates.iloc[pos]


def _calculate_max_drawdown(df: pd.DataFrame) -> float | None:
    adj = df["adj_nav"].dropna()
    if len(adj) < 2:
        return None
    peak = adj.expanding().max()
    drawdown = (adj / peak - 1).min()
    return float(drawdown)


def _calculate_risk_metrics(df, max_drawdown):
    from config import RISK_FREE_RATE
    result = {"annual_return": None, "annual_volatility": None,
              "sharpe_ratio": None, "calmar_ratio": None}
    adj = df["adj_nav"].dropna()
    if len(adj) < 20:
        return result
    daily_returns = adj.pct_change().dropna()
    N = len(daily_returns)
    if N < 10:
        return result
    cumulative = adj.iloc[-1] / adj.iloc[0] - 1
    annual_return = (1 + cumulative) ** (252 / N) - 1
    result["annual_return"] = float(annual_return)
    annual_vol = float(daily_returns.std()) * np.sqrt(252)
    result["annual_volatility"] = float(annual_vol)
    if annual_vol > 0:
        result["sharpe_ratio"] = float((annual_return - RISK_FREE_RATE) / annual_vol)
    if max_drawdown is not None and max_drawdown < 0:
        result["calmar_ratio"] = float(annual_return / abs(max_drawdown))
    return result


def calc_performance_for_date(nav_df: pd.DataFrame, target_date: date) -> dict | None:
    """计算单只基金在指定日期的绩效指标（复用 03 逻辑）"""
    df = nav_df[nav_df["date"] <= target_date].copy()
    if df.empty or len(df) < 2:
        return None

    df = df.sort_values("date").reset_index(drop=True)
    df = df.drop_duplicates(subset=["date"], keep="last")
    df["date"] = pd.to_datetime(df["date"]).dt.date

    latest_date: date = df["date"].max()
    dates: pd.Series = df["date"]

    unit_values = dict(zip(df["date"], df["unit_nav"])) if "unit_nav" in df.columns else {}
    adj_values = dict(zip(df["date"], df["adj_nav"])) if "adj_nav" in df.columns else {}

    latest_unit = unit_values.get(latest_date) if unit_values else None
    latest_adj = adj_values.get(latest_date) if adj_values else None

    def _change(target, values, latest_val):
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

    # 短期
    if unit_values and latest_unit is not None:
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
        result["week_change"] = _change(
            latest_date - pd.Timedelta(days=7), unit_values, latest_unit
        )
    else:
        result["daily_change"] = None
        result["week_change"] = None

    # 中长期
    if adj_values and latest_adj is not None:
        result["day_20_change"] = _change(
            latest_date - pd.Timedelta(days=28), adj_values, latest_adj
        )
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

        first_valid_date = df.dropna(subset=["adj_nav"])["date"].min()
        if first_valid_date and first_valid_date in adj_values and first_valid_date != latest_date:
            result["since_launch_change"] = latest_adj / adj_values[first_valid_date] - 1
        else:
            result["since_launch_change"] = None
    else:
        for key in ["day_20_change", "month_1_change", "month_3_change", "month_6_change",
                     "ytd_change", "year_1_change", "year_3_change", "year_5_change",
                     "since_launch_change"]:
            result[key] = None

    result["max_drawdown"] = _calculate_max_drawdown(df)
    risk = _calculate_risk_metrics(df, result["max_drawdown"])
    result.update(risk)
    return result


def backfill_fund_returns(fund_codes: list[str], all_dates: list[date]):
    """逐基金、逐日期计算历史收益"""
    print(f"\n{'=' * 60}")
    print("回填基金涨跌幅（所有历史日期）")
    print(f"{'=' * 60}")
    print(f"  {len(fund_codes)} 只基金 × {len(all_dates)} 个交易日")
    print(f"  预计耗时: {len(fund_codes) * len(all_dates) * 0.001:.0f}s（每基金每日期约 1ms）\n")

    results = []
    t_start = time.time()

    for fi, code in enumerate(fund_codes):
        nav_path = os.path.join(NAV_DIR, f"{code}.parquet")
        nav = safe_read_parquet(nav_path)
        if nav is None or nav.empty:
            continue
        nav["date"] = pd.to_datetime(nav["date"]).dt.date
        nav = nav.sort_values("date").reset_index(drop=True)

        has_unit = "unit_nav" in nav.columns
        has_adj = "adj_nav" in nav.columns
        if not has_unit and not has_adj:
            continue

        fund_dates = set(nav["date"].unique())
        for target in all_dates:
            if target not in fund_dates:
                continue
            try:
                perf = calc_performance_for_date(nav, target)
                if perf:
                    perf["fund_code"] = code
                    results.append(perf)
            except Exception:
                pass

        elapsed = time.time() - t_start
        avg = elapsed / (fi + 1)
        eta = format_seconds(avg * (len(fund_codes) - fi - 1))
        if (fi + 1) % 50 == 0 or fi == 0:
            print(f"\r  [{fi + 1}/{len(fund_codes)}] 已产出 {len(results)} 行  剩余≈{eta}", end="", flush=True)

    print()
    if not results:
        print("✗ 无数据")
        return pd.DataFrame()
    df = pd.DataFrame(results)
    print(f"  完成: {len(df)} 行, {df['date'].nunique()} 个交易日\n")
    return df


def backfill_index_returns(all_dates: list[date]):
    """回填指数涨跌幅 — 从已有指数缓存中计算每个交易日"""
    print(f"\n{'=' * 60}")
    print("回填指数涨跌幅")
    print(f"{'=' * 60}")

    results = []
    for idx_code in ["HS300", "ZZ500", "ZZ1000", "CSI_ALL"]:
        path = os.path.join(INDEX_DIR, f"{idx_code}.parquet")
        idx_df = safe_read_parquet(path)
        if idx_df is None or idx_df.empty:
            print(f"  ✗ {idx_code} 无数据，跳过")
            continue
        idx_df["date"] = pd.to_datetime(idx_df["date"]).dt.date
        idx_df = idx_df.sort_values("date").reset_index(drop=True)
        idx_dates = set(idx_df["date"].unique())

        for target in all_dates:
            if target not in idx_dates:
                continue
            nav = idx_df.copy()
            nav = nav.rename(columns={"index_value": "adj_nav"})
            nav["unit_nav"] = nav["adj_nav"]
            try:
                perf = calc_performance_for_date(nav, target)
                if perf:
                    perf["index_code"] = idx_code
                    perf["index_name"] = INDEX_NAMES.get(idx_code, idx_code)
                    results.append(perf)
            except Exception:
                pass
        print(f"  ✓ {INDEX_NAMES.get(idx_code, idx_code)}")

    if not results:
        return pd.DataFrame()
    df = pd.DataFrame(results)
    print(f"  完成: {len(df)} 行, {df['date'].nunique()} 个交易日\n")
    return df


def backfill_excess(fund_perf, index_perf, fund_master):
    """回填超额收益 — 对所有历史日期计算"""
    print(f"\n{'=' * 60}")
    print("回填超额收益 (Alpha)")
    print(f"{'=' * 60}")

    if fund_perf.empty or index_perf.empty:
        return pd.DataFrame()

    info = fund_master[["fund_code", "fund_name", "share_class",
                         "benchmark_index", "benchmark_name"]].copy()
    info["fund_code"] = info["fund_code"].astype(str).str.zfill(6)

    all_dates = sorted(fund_perf["date"].unique())
    print(f"  处理 {len(all_dates)} 个交易日...")

    results = []
    for d in all_dates:
        fp = fund_perf[fund_perf["date"] == d].copy()
        ip = index_perf[index_perf["date"] == d].copy()
        if fp.empty or ip.empty:
            continue

        merged = fp.merge(info, on="fund_code", how="left")

        for perf_field in ["daily_change", "week_change", "day_20_change",
                            "month_1_change", "month_3_change", "month_6_change",
                            "ytd_change",
                            "year_1_change", "year_3_change", "year_5_change"]:
            excess_field = perf_field.replace("change", "excess")
            alpha_field = perf_field.replace("change", "alpha")
            idx_map = ip.set_index("index_code")[perf_field].to_dict()
            merged[excess_field] = merged[perf_field] - 0.95 * merged["benchmark_index"].map(idx_map)
            # 回填暂不扣股息（无历史股息率数据），alpha ≈ excess
            merged[alpha_field] = merged[excess_field]

        results.append(merged)

    if not results:
        return pd.DataFrame()
    df = pd.concat(results, ignore_index=True)
    # 保留 output 列
    out_cols = ["fund_code", "fund_name", "share_class",
                "benchmark_index", "benchmark_name", "date",
                "daily_change", "week_change", "day_20_change",
                "month_1_change", "month_3_change", "month_6_change",
                "ytd_change", "year_1_change", "year_3_change", "year_5_change",
                "since_launch_change", "max_drawdown",
                "annual_return", "annual_volatility", "sharpe_ratio", "calmar_ratio",
                "daily_excess", "week_excess", "day_20_excess",
                "month_1_excess", "month_3_excess", "month_6_excess",
                "ytd_excess",
                "year_1_excess", "year_3_excess", "year_5_excess",
                "daily_alpha", "week_alpha", "day_20_alpha",
                "month_1_alpha", "month_3_alpha", "month_6_alpha",
                "ytd_alpha",
                "year_1_alpha", "year_3_alpha", "year_5_alpha"]
    out_cols = [c for c in out_cols if c in df.columns]
    df = df[out_cols]
    print(f"  完成: {len(df)} 行, {df['date'].nunique()} 个交易日\n")
    return df


def main():
    print("\n" + "█" * 60)
    print("█  历史数据回填 — 从 NAV 重建所有日期的收益/超额")
    print("█" * 60)

    os.makedirs(RETURN_DIR, exist_ok=True)

    # 1. 收集所有历史日期
    all_dates_set = load_all_nav_dates()
    if not all_dates_set:
        print("✗ 无 NAV 数据")
        return
    all_dates = sorted(all_dates_set)
    print(f"\n共发现 {len(all_dates)} 个交易日")
    print(f"日期范围: {all_dates[0]} ~ {all_dates[-1]}")

    # 2. 加载基金池
    fund_master = load_fund_master()
    if fund_master.empty:
        print("✗ 基金池为空")
        return
    fund_codes = fund_master["fund_code"].tolist()

    # 3. 回填基金涨跌幅
    fund_perf = backfill_fund_returns(fund_codes, all_dates)
    if not fund_perf.empty:
        safe_write_parquet(fund_perf, FUND_RETURN_PATH)
        print(f"✓ 基金涨跌幅已保存: {FUND_RETURN_PATH}")

    # 4. 回填指数涨跌幅
    index_perf = backfill_index_returns(all_dates)
    if not index_perf.empty:
        safe_write_parquet(index_perf, INDEX_RETURN_PATH)
        print(f"✓ 指数涨跌幅已保存: {INDEX_RETURN_PATH}")

    # 5. 回填超额收益
    excess_perf = backfill_excess(fund_perf, index_perf, fund_master)
    if not excess_perf.empty:
        safe_write_parquet(excess_perf, EXCESS_RETURN_PATH)
        print(f"✓ 超额收益已保存: {EXCESS_RETURN_PATH}")
        print(f"  共 {len(excess_perf)} 行, {excess_perf['date'].nunique()} 个交易日")
        print(f"  最新日期: {excess_perf['date'].max()}")

    print("\n" + "█" * 60)
    print("█  回填完成！现在可以运行 04_generate_html.py 生成带全量历史日期的看板")
    print("█" * 60)


if __name__ == "__main__":
    main()
