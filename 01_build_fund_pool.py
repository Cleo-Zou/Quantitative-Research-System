import os
import time
import pandas as pd
import akshare as ak

from config import (
    DATA_DIR,
    NAV_DIR,
    INDEX_DIR,
    FUND_MASTER_PATH,
    INDEX_KEYWORDS,
    ENHANCE_KEYWORDS,
    ENHANCE_OBJECTIVE_KEYWORDS,
    EXCLUDE_PATTERNS,
    BENCHMARK_INDEX_MAP,
    INDEX_NAMES,
    REQUEST_DELAY,
    MAX_RETRIES,
    BATCH_SAVE_INTERVAL,
)

# 工具函数

def ensure_dirs():
    for d in [DATA_DIR, NAV_DIR, INDEX_DIR]:
        os.makedirs(d, exist_ok=True)

def _find_col(df: pd.DataFrame, *candidates: str) -> str | None:
    for col in df.columns:
        col_str = str(col)
        for c in candidates:
            if c in col_str:
                return col
    return None

def _format_seconds(sec: float) -> str:
    if sec < 60:
        return f"{sec:.0f}s"
    m, s = divmod(int(sec), 60)
    return f"{m}min{s}s"

# Step 1: 获取全市场基金列表

def get_all_funds() -> pd.DataFrame:
    print("=" * 60)
    print("Step 1 / 4  获取全市场基金列表")
    print("=" * 60)

    try:
        df = ak.fund_name_em()
    except Exception as e:
        print(f"✗ AKShare 调用失败: {e}")
        raise

    code_col = _find_col(df, "基金代码", "代码")
    name_col = _find_col(df, "基金简称", "简称", "名称")

    if code_col and code_col != "fund_code":
        df = df.rename(columns={code_col: "fund_code"})
    if name_col and name_col != "fund_name":
        df = df.rename(columns={name_col: "fund_name"})

    if "fund_code" in df.columns:
        df["fund_code"] = df["fund_code"].astype(str).str.zfill(6)

    print(f"✓ 全市场共 {len(df):,} 只基金")
    return df

# Step 2: 宽松粗筛 — 指数 OR 增强（不再要求同时满足）

def _match_index(name: str) -> str | None:
    for index_code, keywords in INDEX_KEYWORDS.items():
        for kw in keywords:
            if kw in name:
                return index_code
    return None

def _has_enhance_keyword(name: str) -> bool:
    for kw in ENHANCE_KEYWORDS:
        if kw in name:
            return True
    return False

def _has_exclude_pattern(name: str) -> bool:
    for pat in EXCLUDE_PATTERNS:
        if pat in name:
            return True
    return False

def build_candidate_pool(all_funds: pd.DataFrame) -> pd.DataFrame:
    print("\n" + "=" * 60)
    print("Step 2 / 4  宽松粗筛（指数 OR 增强）")
    print("=" * 60)

    name_col = _find_col(all_funds, "fund_name", "简称", "名称")
    if name_col is None:
        name_col = all_funds.columns[0]

    candidates: list[dict] = []
    seen_codes: set[str] = set()

    stats = {"index_hit": 0, "enhance_hit": 0, "both_hit": 0}

    for _, row in all_funds.iterrows():
        name = str(row[name_col])
        code = str(row.get("fund_code", row.iloc[0])).zfill(6)

        if code in seen_codes:
            continue

        index_code = _match_index(name)
        is_enhance = _has_enhance_keyword(name)

        # ---- OR 逻辑：满足任一即进入候选 ----
        if index_code is None and not is_enhance:
            continue

        seen_codes.add(code)

        if index_code and is_enhance:
            hit_reason = "both"
            stats["both_hit"] += 1
        elif index_code:
            hit_reason = "index"
            stats["index_hit"] += 1
        else:
            hit_reason = "enhance"
            stats["enhance_hit"] += 1

        candidates.append({
            "fund_code": code,
            "fund_name": name,
            "coarse_index": index_code or "unknown",
            "hit_reason": hit_reason,
        })

    df = pd.DataFrame(candidates)

    print(f"✓ 粗筛结果: {len(df)} 只候选")
    print(f"    指数命中:   {stats['index_hit']:>5} 只")
    print(f"    增强命中:   {stats['enhance_hit']:>5} 只")
    print(f"    双重命中:   {stats['both_hit']:>5} 只")

    print()
    for idx_code in ["HS300", "ZZ500", "ZZ1000", "CSI_ALL", "unknown"]:
        count = len(df[df["coarse_index"] == idx_code])
        if count > 0:
            label = INDEX_NAMES.get(idx_code, "待确认")
            print(f"    {label:<8} {count:>5} 只")

    return df

# Step 3: 获取天天基金详情 & 精确验证

def _fetch_fund_detail_em(fund_code: str) -> dict | None:
    for attempt in range(1 + MAX_RETRIES):
        try:
            info_df = ak.fund_individual_basic_info_em(symbol=fund_code)

            if info_df is None or info_df.empty:
                return None

            info_dict: dict[str, str] = {}
            for _, row_data in info_df.iterrows():
                if len(row_data) >= 2:
                    k = str(row_data.iloc[0]).strip()
                    v = str(row_data.iloc[1]).strip()
                    info_dict[k] = v

            detail: dict = {
                "benchmark": "",
                "objective": "",
                "company": "",
                "manager": "",
                "launch_date": "",
                "scale": "",
            }

            for key, val in info_dict.items():
                if val in ("—", "-", "暂无", "None", "nan", ""):
                    continue
                if "业绩比较基准" in key or "业绩基准" in key:
                    detail["benchmark"] = val
                elif "投资目标" in key:
                    detail["objective"] = val
                elif "管理人" in key or "基金管理人" in key:
                    detail["company"] = val
                elif "基金经理" in key:
                    detail["manager"] = val
                elif "成立" in key and ("日期" in key or "时间" in key):
                    detail["launch_date"] = val
                elif "规模" in key or "资产净值" in key or "资产规模" in key:
                    detail["scale"] = val

            return detail

        except Exception:
            if attempt < MAX_RETRIES:
                time.sleep(REQUEST_DELAY * 2)

    return None

def _identify_index_from_detail(
    fund_name: str, benchmark: str, objective: str
) -> str | None:
    # 1) 名称中已有指数关键词
    name_index = _match_index(fund_name)
    if name_index:
        return name_index

    # 2) 业绩比较基准 + 投资目标中查找
    combined = (benchmark + " " + objective)

    for index_name, index_code in BENCHMARK_INDEX_MAP.items():
        if index_name in combined:
            return index_code

    # 3) 深层匹配
    if "300" in combined and "指数" in combined:
        return "HS300"
    if "中证500" in combined:
        return "ZZ500"
    if "中证1000" in combined:
        return "ZZ1000"
    if "中证全指" in combined or "全指" in combined:
        return "CSI_ALL"

    return None

def _is_index_enhancement(name: str, objective: str) -> bool:
    if _has_enhance_keyword(name):
        return True
    for kw in ENHANCE_OBJECTIVE_KEYWORDS:
        if kw in objective:
            return True
    return False

def verify_index_enhancement(candidates: pd.DataFrame) -> pd.DataFrame:
    print("\n" + "=" * 60)
    print("Step 3 / 4  获取天天基金详情 & 精确验证")
    print("=" * 60)

    total = len(candidates)
    verified: list[dict] = []
    skipped: list[str] = []

    skip_reasons: dict[str, int] = {
        "ETF/联接排除": 0,
        "非目标指数": 0,
        "非增强型": 0,
        "API获取失败": 0,
    }

    t_start = time.time()

    for i, (_, row) in enumerate(candidates.iterrows()):
        code = row["fund_code"]
        name = row["fund_name"]
        coarse_index = row["coarse_index"]

        # ---- 时间估算 ----
        elapsed = time.time() - t_start
        avg_per_item = elapsed / (i + 1) if i > 0 else REQUEST_DELAY
        eta_sec = avg_per_item * (total - i - 1)
        eta_str = _format_seconds(eta_sec)

        # ---- 进度 ----
        pct = (i + 1) / total * 100
        print(
            f"\r  [{i + 1:>4}/{total} {pct:>4.0f}%]  "
            f"✓{len(verified):>3}  "
            f"✗{sum(skip_reasons.values()):>3}  "
            f"剩余≈{eta_str:<8s}  "
            f"{code} {name[:24]}",
            end="", flush=True,
        )

        # ---- 条件 C: 排除 ETF / 联接 ----
        if _has_exclude_pattern(name):
            skip_reasons["ETF/联接排除"] += 1
            skipped.append(f"{code} {name} | ETF/联接")
            time.sleep(REQUEST_DELAY)
            continue

        # ---- 获取天天基金详情 ----
        detail = _fetch_fund_detail_em(code)

        if detail is None:
            skip_reasons["API获取失败"] += 1
            skipped.append(f"{code} {name} | API无详情")
            time.sleep(REQUEST_DELAY)
            continue

        # ---- 条件 A: 识别指数 ----
        identified_index = _identify_index_from_detail(
            name,
            detail.get("benchmark", ""),
            detail.get("objective", ""),
        )

        if identified_index is None:
            skip_reasons["非目标指数"] += 1
            skipped.append(f"{code} {name} | 非四指数")
            time.sleep(REQUEST_DELAY)
            continue

        # ---- 条件 B: 判断是否增强 ----
        if not _is_index_enhancement(name, detail.get("objective", "")):
            skip_reasons["非增强型"] += 1
            skipped.append(f"{code} {name} | 非增强")
            time.sleep(REQUEST_DELAY)
            continue

        # ---- 通过全部验证 ----
        verified.append({
            "fund_code": code,
            "fund_name": name,
            "benchmark_index": identified_index,
            "strategy_type": "指数增强",
            "company": detail.get("company", ""),
            "manager": detail.get("manager", ""),
            "launch_date": detail.get("launch_date", ""),
            "scale": detail.get("scale", ""),
            "source": (
                "name_match"
                if coarse_index == identified_index
                else "detail_discover"
            ),
        })

        # 定期保存中间结果（防中断）
        if len(verified) % BATCH_SAVE_INTERVAL == 0 and len(verified) > 0:
            pd.DataFrame(verified).to_parquet(
                FUND_MASTER_PATH + ".tmp", index=False
            )

        time.sleep(REQUEST_DELAY)

    print()  # 换行（进度条用 \r）

    # ---- 统计 ----
    total_elapsed = time.time() - t_start
    print(f"\n  总耗时: {_format_seconds(total_elapsed)}")
    print(f"  {'─' * 30}")
    print(f"  ✓ 通过验证:     {len(verified):>4} 只")
    print(f"  ✗ 被排除:       {sum(skip_reasons.values()):>4} 只")
    for reason, count in skip_reasons.items():
        if count > 0:
            print(f"       ├─ {reason}: {count}")
    print(f"  {'─' * 30}")
    print(f"  候选合计:       {total:>4} 只")

    if skipped:
        print(f"\n  被排除示例（前 10 只）:")
        for s in skipped[:10]:
            print(f"    ✗ {s}")

    df_verified = pd.DataFrame(verified)

    # 按指数统计
    print(f"\n  最终基金池分布:")
    for idx_code in ["HS300", "ZZ500", "ZZ1000", "CSI_ALL"]:
        count = len(df_verified[df_verified["benchmark_index"] == idx_code])
        label = INDEX_NAMES.get(idx_code, idx_code)
        bar = "█" * min(count // 2, 30) if count > 0 else ""
        print(f"    {label:<8} {count:>4} 只  {bar}")

    return df_verified

# Step 4: 保存基金主表

def save_fund_master(fund_pool: pd.DataFrame) -> None:
    print("\n" + "=" * 60)
    print("Step 4 / 4  保存基金主表")
    print("=" * 60)

    columns = [
        "fund_code",
        "fund_name",
        "benchmark_index",
        "strategy_type",
        "company",
        "manager",
        "launch_date",
        "scale",
        "source",
    ]

    for col in columns:
        if col not in fund_pool.columns:
            fund_pool[col] = ""

    fund_pool = fund_pool[columns]

    # 去重
    fund_pool = fund_pool.drop_duplicates(subset="fund_code", keep="first")

    # 排序：指数 → 代码
    idx_order = {"HS300": 0, "ZZ500": 1, "ZZ1000": 2, "CSI_ALL": 3}
    fund_pool["_sort_idx"] = (
        fund_pool["benchmark_index"].map(idx_order).fillna(9)
    )
    fund_pool = fund_pool.sort_values(["_sort_idx", "fund_code"]).drop(
        columns=["_sort_idx"]
    )

    fund_pool.to_parquet(FUND_MASTER_PATH, index=False)

    tmp_path = FUND_MASTER_PATH + ".tmp"
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    print(f"✓ 基金主表已保存: {FUND_MASTER_PATH}")
    print(f"  共 {len(fund_pool)} 只基金\n")

    # 预览
    print(f"{'─' * 72}")
    print("预览（前 20 行）:")
    print(f"{'─' * 72}")
    print(f"{'代码':<8} {'名称':<30} {'指数':<10} {'来源'}")
    print(f"{'─' * 72}")
    for _, r in fund_pool.head(20).iterrows():
        idx_label = INDEX_NAMES.get(r["benchmark_index"], r["benchmark_index"])
        print(
            f"{r['fund_code']:<8} {r['fund_name']:<30} "
            f"{idx_label:<10} {r['source']}"
        )
    if len(fund_pool) > 20:
        print(f"  ... (共 {len(fund_pool)} 只)")

# 主入口

def main():
    print("\n" + "█" * 60)
    print("█  公募指数增强基金池 构建程序")
    print("█  数据来源: 天天基金 (via AKShare)")
    print("█  逻辑: 粗筛(OR) → 详情验证(AND) → 排除ETF/联接")
    print("█" * 60)

    ensure_dirs()

    all_funds = get_all_funds()
    candidates = build_candidate_pool(all_funds)

    if candidates.empty:
        print("\n⚠ 粗筛结果为空，请检查配置")
        return

    print(
        f"\n  预计 Step 3 耗时 ≈ "
        f"{_format_seconds(len(candidates) * REQUEST_DELAY)} "
        f"（{len(candidates)} 只 × {REQUEST_DELAY}s）"
    )

    fund_pool = verify_index_enhancement(candidates)

    if fund_pool.empty:
        print("\n⚠ 没有基金通过验证，请检查筛选逻辑")
        return

    save_fund_master(fund_pool)

    print("\n" + "█" * 60)
    print("█  基金池构建完成 ✓")
    print(f"█  共 {len(fund_pool)} 只指数增强基金入库")
    print(f"█  文件: {FUND_MASTER_PATH}")
    print("█" * 60)

if __name__ == "__main__":
    main()
