import os
import pandas as pd

from config import (
    EXCESS_RETURN_PATH,
    FUND_MASTER_PATH,
    ANALYSIS_OUTPUT,
    INDEX_NAMES,
)

from analysis.ranking import compute_rankings
from analysis.research_profile import determine_profile
from analysis.research_tags import determine_tags
from analysis.research_summary import generate_summaries
from analysis.excel import export_excel


def load_data() -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """加载超额收益数据和基金主表"""
    if not os.path.exists(EXCESS_RETURN_PATH):
        raise FileNotFoundError(
            f"超额收益文件不存在: {EXCESS_RETURN_PATH}\n"
            "请先运行 03_calculate_return.py"
        )

    excess = pd.read_parquet(EXCESS_RETURN_PATH)
    print(f"读取超额收益数据: {len(excess)} 条")

    # 只取最新日期
    latest_date = excess["date"].max()
    excess = excess[excess["date"] == latest_date].copy()
    print(f"最新日期: {latest_date}, 基金数: {len(excess)}")

    # 加载基金主表（获取 launch_date）
    master = None
    if os.path.exists(FUND_MASTER_PATH):
        master = pd.read_parquet(FUND_MASTER_PATH)
        master["fund_code"] = master["fund_code"].astype(str).str.zfill(6)
        print(f"读取基金主表: {len(master)} 条")
    else:
        print("[WARN] 基金主表不存在，成立日期信息将缺失")

    return excess, master


def prepare_df(excess: pd.DataFrame, master: pd.DataFrame | None) -> pd.DataFrame:
    """合并数据，选取分析所需字段"""
    # 分析所需的核心字段
    core_cols = [
        "fund_code", "fund_name", "share_class",
        "benchmark_index", "benchmark_name",
        # 五核心
        "annual_return", "annual_volatility", "sharpe_ratio",
        "max_drawdown", "calmar_ratio",
        # Alpha
        "year_1_alpha", "month_6_alpha", "month_1_alpha",
        # 保留 year_1_change 用于兼容
        "year_1_change",
    ]

    df = excess[[c for c in core_cols if c in excess.columns]].copy()

    # 合并 launch_date（优先 fund_master，其次 fund_detail_cache）
    launch_map: dict[str, str] = {}
    if master is not None and "launch_date" in master.columns:
        launch_map.update(
            master.set_index("fund_code")["launch_date"].dropna().to_dict()
        )
    # 从缓存补充
    cache_path = os.path.join(os.path.dirname(EXCESS_RETURN_PATH), "..", "fund_detail_cache.parquet")
    cache_path = os.path.normpath(cache_path)
    if os.path.exists(cache_path):
        cache = pd.read_parquet(cache_path)
        if "launch_date" in cache.columns:
            for _, row in cache.iterrows():
                code = str(row["fund_code"]).zfill(6)
                ld = row["launch_date"]
                if code not in launch_map and pd.notna(ld) and str(ld) not in ("", "nan", "None"):
                    launch_map[code] = str(ld)

    df["launch_date"] = df["fund_code"].map(launch_map)
    launched = df["launch_date"].notna().sum()
    print(f"  成立日期覆盖: {launched}/{len(df)}")

    # 过滤：至少有一个周期的 Alpha 数据（不完全为空）
    alpha_cols = [c for c in ["year_1_alpha", "month_6_alpha", "month_1_alpha"] if c in df.columns]
    if alpha_cols:
        df = df[df[alpha_cols].notna().any(axis=1)].copy()

    print(f"有效分析样本: {len(df)} 只")

    # 分组统计
    for idx_code in ["HS300", "ZZ500", "ZZ1000", "CSI_ALL"]:
        count = len(df[df["benchmark_index"] == idx_code])
        if count > 0:
            label = INDEX_NAMES.get(idx_code, idx_code)
            print(f"  {label:<8} {count:>3} 只")

    return df


def main():
    print("\n" + "█" * 60)
    print("█  基金研究解读引擎（Rule-based Research Interpretation）")
    print("█  输出: Profile + Tags + Research Summary")
    print("█" * 60)

    # ── Step 1: 加载数据 ──
    excess, master = load_data()
    df = prepare_df(excess, master)

    if df.empty:
        print("\n[ERROR] 无有效分析数据")
        return

    # ── Step 2: 排名与百分位 ──
    print("\n[1/5] 计算同类排名与百分位...")
    df = compute_rankings(df)
    print(f"  完成: {len(df)} 只")

    # ── Step 3: Profile 判定 ──
    print("\n[2/5] 判定基金画像（Profile）...")
    df = determine_profile(df)
    profile_counts = df["profile"].value_counts()
    for p, c in profile_counts.items():
        print(f"  {p}: {c}")

    # ── Step 4: Tag 生成 ──
    print("\n[3/5] 生成研究标签（Tags）...")
    df = determine_tags(df)

    # ── Step 5: 研究摘要 ──
    print("\n[4/5] 生成研究摘要（Research Summary）...")
    df = generate_summaries(df)

    # ── Step 6: 导出 Excel ──
    print("\n[5/5] 导出 Excel...")
    export_excel(df, ANALYSIS_OUTPUT)

    # ── 预览 ──
    print("\n" + "=" * 60)
    print("Preview: top 5 Stable Enhanced funds")
    print("=" * 60)
    preview = df[df["profile"] == "稳定增强型"].head(5)
    for _, row in preview.iterrows():
        code = row["fund_code"]
        name = row["fund_name"]
        profile = row["profile"]
        tags = str(row.get("tags", ""))
        ret = str(row.get("return_summary", ""))[:80]
        comment = str(row.get("summary_comment", ""))
        try:
            print(f"\n  {code} {name}")
            print(f"  Profile: {profile}  Tags: {tags}")
            print(f"  [Return] {ret}")
            print(f"  [Summary] {comment}")
        except UnicodeEncodeError:
            print(f"\n  {code} {name}")
            print(f"  Profile: {profile}")
            print(f"  [Return] {ret}")
            print(f"  [Summary] {comment}")

    print("\n" + "█" * 60)
    print(f"[OK] Research analysis exported: {ANALYSIS_OUTPUT}")
    print("█" * 60)


if __name__ == "__main__":
    main()
