import os
import re
import time
import random
import pandas as pd
import akshare as ak

from config import (
    DATA_DIR,
    FUND_MASTER_PATH,
    API_FAILED_PATH,
    EXCLUDED_PATH,
    MANUAL_EXCLUDE_PATH,
    MANUAL_INCLUDE_PATH,
    INDEX_KEYWORDS,
    ENHANCE_KEYWORDS,
    ENHANCE_OBJECTIVE_KEYWORDS,
    EXCLUDE_PATTERNS,
    EXCLUDE_EXCEPTIONS,
    BENCHMARK_INDEX_MAP,
    INDEX_NAMES,
)


# 参数

CACHE_PATH = os.path.join(DATA_DIR, "fund_detail_cache.parquet")

REQUEST_DELAY_MIN = 0.8
REQUEST_DELAY_MAX = 1.8

MAX_RETRIES = 5

CACHE_SAVE_INTERVAL = 100


# 文件目录

def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)


# cache

def _load_detail_cache():
    if not os.path.exists(CACHE_PATH):
        return {}

    try:
        df = pd.read_parquet(CACHE_PATH)
        cache = {}
        for _, row in df.iterrows():
            cache[row["fund_code"]] = row.to_dict()
        print(f"✓ 加载API缓存: {len(cache)}条")
        return cache
    except Exception:
        return {}


def _save_detail_cache(cache):
    if not cache:
        return

    try:
        df = pd.DataFrame(list(cache.values()))
        df.to_parquet(CACHE_PATH, index=False)
    except Exception as e:
        print(f"\n缓存保存失败: {e}")


# 人工规则

def _load_manual_exclude():
    if not os.path.exists(MANUAL_EXCLUDE_PATH):
        return set()

    try:
        df = pd.read_csv(MANUAL_EXCLUDE_PATH, dtype=str)
        return set(df["fund_code"].astype(str).str.zfill(6))
    except Exception:
        return set()


def _load_manual_include():
    if not os.path.exists(MANUAL_INCLUDE_PATH):
        return []

    try:
        df = pd.read_csv(MANUAL_INCLUDE_PATH, dtype=str)
        df["fund_code"] = df["fund_code"].astype(str).str.zfill(6)
        return df.to_dict("records")
    except Exception:
        return []


# 基础工具

def _find_col(df, *names):
    for c in df.columns:
        for n in names:
            if n in str(c):
                return c
    return None


def _random_sleep():
    time.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))


def _extract_share_class(name):
    m = re.search(r"([ABCDE])$", name)
    return m.group(1) if m else ""


def _is_link_fund(name):
    return "联接" in name


# 增强关键词 / ETF过滤  →  统一使用 config 配置

def _has_enhance_keyword(name):
    """使用 config.ENHANCE_KEYWORDS 做名称增强关键词匹配"""
    for kw in ENHANCE_KEYWORDS:
        if kw in name:
            return True
    return False


def _is_etf_or_link(name):
    """使用 config.EXCLUDE_PATTERNS / EXCLUDE_EXCEPTIONS 做 ETF/联接过滤"""
    has_exclude = any(p in name for p in EXCLUDE_PATTERNS)
    if not has_exclude:
        return False
    # 例外：包含排除词和例外关键词，保留
    has_exception = any(e in name for e in EXCLUDE_EXCEPTIONS)
    if has_exception:
        return False
    return True


# API请求核心

def _fetch_fund_detail_xq(fund_code, cache):
    # 1. 读取缓存
    if fund_code in cache:
        return cache[fund_code]

    # 2. 多次重试（带随机 jitter 退避）
    for attempt in range(MAX_RETRIES):
        try:
            # 请求前随机延迟，降低限流概率
            if attempt > 0:
                wait = (2 ** attempt) + random.uniform(0, 1)
                time.sleep(wait)
            else:
                _random_sleep()

            df = ak.fund_individual_basic_info_xq(symbol=fund_code)

            if df is None or df.empty:
                raise ValueError("empty response")

            info = {}
            for _, row in df.iterrows():
                if len(row) >= 2:
                    key = str(row.iloc[0]).strip()
                    value = str(row.iloc[1]).strip()
                    info[key] = value

            detail = {
                "fund_code": fund_code,
                "benchmark_raw": "",
                "objective_raw": "",
                "benchmark": "",
                "objective": "",
                "fund_company": "",
                "fund_manager": "",
                "fund_type": "",
                "launch_date": "",
                "scale": "",
            }

            for k, v in info.items():
                if v in ["", "-", "—", "暂无"]:
                    continue

                if "业绩比较基准" in k or "业绩基准" in k:
                    detail["benchmark_raw"] = v
                    detail["benchmark"] = v
                elif "投资目标" in k:
                    detail["objective_raw"] = v
                    detail["objective"] = v
                elif "基金公司" in k or "管理人" in k:
                    detail["fund_company"] = v
                elif "基金经理" in k:
                    detail["fund_manager"] = v
                elif "基金类型" in k:
                    detail["fund_type"] = v
                elif "成立" in k:
                    detail["launch_date"] = v
                elif "规模" in k or "资产净值" in k:
                    detail["scale"] = v

            # 保存cache
            cache[fund_code] = detail
            return detail

        except Exception:
            # 失败后退避（带 jitter）
            wait = (2 ** attempt) + random.uniform(0, 1)
            time.sleep(wait)

    # 全部重试失败
    return None


# Step 1: 获取全市场基金列表

def get_all_funds():
    print("\n" + "=" * 60)
    print("Step 1 / 4 获取全市场基金列表")
    print("=" * 60)

    df = ak.fund_name_em()

    code_col = _find_col(df, "基金代码", "代码")
    name_col = _find_col(df, "基金简称", "简称", "名称")
    type_col = _find_col(df, "基金类型", "类型")

    if code_col:
        df = df.rename(columns={code_col: "fund_code"})
    if name_col:
        df = df.rename(columns={name_col: "fund_name"})
    if type_col:
        df = df.rename(columns={type_col: "fund_type_em"})

    df["fund_code"] = df["fund_code"].astype(str).str.zfill(6)

    print(f"✓ 全市场基金: {len(df)}只")
    return df


# 指数识别

def _match_index(name):
    for idx, keywords in INDEX_KEYWORDS.items():
        for kw in keywords:
            if kw in name:
                return idx
    return None


# 粗筛

def build_candidate_pool(all_funds):
    print("\n" + "=" * 60)
    print("Step 2 / 4 粗筛候选基金")
    print("=" * 60)

    candidates = []
    seen = set()

    stats = {
        "etf": 0,
        "bad_type": 0,
        "index": 0,
        "enhance": 0,
        "both": 0,
    }

    for _, row in all_funds.iterrows():
        code = row["fund_code"]
        name = str(row["fund_name"])

        if code in seen:
            continue

        # ETF/联接过滤（使用 config 规则）
        if _is_etf_or_link(name):
            stats["etf"] += 1
            continue

        # 类型过滤
        fund_type = str(row.get("fund_type_em", ""))
        bad = ["债券", "货币", "可转债"]

        if any(x in fund_type for x in bad):
            stats["bad_type"] += 1
            continue

        index_code = _match_index(name)
        enhance = _has_enhance_keyword(name)

        # 候选条件
        if index_code is None and not enhance:
            continue

        # 名称明显债券增强排除
        if "债券" in name or "可转债" in name:
            continue

        seen.add(code)

        if index_code and enhance:
            reason = "both"
            stats["both"] += 1
        elif index_code:
            reason = "index"
            stats["index"] += 1
        else:
            reason = "enhance"
            stats["enhance"] += 1

        candidates.append({
            "fund_code": code,
            "fund_name": name,
            "coarse_index": index_code or "unknown",
            "hit_reason": reason,
        })

    df = pd.DataFrame(candidates)

    print(f"✓ 候选: {len(df)}只")
    print(f"ETF过滤: {stats['etf']}")
    print(f"类型过滤: {stats['bad_type']}")
    print(f"指数+增强: {stats['both']}")
    print(f"仅指数: {stats['index']}")
    print(f"仅增强: {stats['enhance']}")

    return df


# Step 3: 基金验证

def _identify_index_from_detail(name, benchmark, objective):
    """返回 (index_code, reason) 或 (None, None)"""
    # 1. 名称优先
    index = _match_index(name)
    if index:
        return index, f"名称匹配指数: {INDEX_NAMES.get(index, index)}"

    text = benchmark + " " + objective

    for k, v in BENCHMARK_INDEX_MAP.items():
        if k in text:
            return v, f"业绩基准/投资目标匹配: {k}"

    if "300" in text and "指数" in text:
        return "HS300", "业绩基准含300指数"

    if "中证500" in text:
        return "ZZ500", "业绩基准含中证500"

    if "中证1000" in text:
        return "ZZ1000", "业绩基准含中证1000"

    if "中证全指" in text or "全指" in text:
        return "CSI_ALL", "业绩基准含中证全指"

    return None, None


def _is_index_enhancement(name, objective, fund_type):
    """返回 (is_enhancement, reason)"""

    # 基金类型
    if "增强指数" in fund_type:
        return True, "基金类型为增强指数型"

    # 名称（使用 config.ENHANCE_KEYWORDS）
    for kw in ENHANCE_KEYWORDS:
        if kw in name:
            return True, f"名称含增强关键词: {kw}"

    # 投资目标（使用 config.ENHANCE_OBJECTIVE_KEYWORDS）
    for kw in ENHANCE_OBJECTIVE_KEYWORDS:
        if kw in objective:
            return True, f"投资目标含增强信号: {kw}"

    return False, ""


def _make_verified_entry(code, name, index, detail, source, reason):
    """构建统一格式的 verified 条目，确保所有字段齐全"""
    entry = {
        "fund_code": code,
        "fund_name": name,
        "share_class": _extract_share_class(name),
        "fund_company": detail.get("fund_company", "") if detail else "",
        "fund_manager": detail.get("fund_manager", "") if detail else "",
        "fund_type": detail.get("fund_type", "") if detail else "",
        "benchmark_index": index,
        "benchmark_name": INDEX_NAMES.get(index, index),
        "benchmark_raw": detail.get("benchmark_raw", "") if detail else "",
        "objective_raw": detail.get("objective_raw", "") if detail else "",
        "strategy_type": "指数增强",
        "enhancement_flag": True,
        "source": source,
        "reason": reason,
        "update_time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    return entry


def verify_index_enhancement(candidates):
    print("\n" + "=" * 60)
    print("Step 3 / 4 基金验证")
    print("=" * 60)

    verified = []
    verified_codes = set()
    api_failed = []  # 记录API调取失败的基金
    excluded = []    # 记录所有被筛去的基金及原因

    manual_exclude = _load_manual_exclude()
    manual_include = _load_manual_include()

    cache = _load_detail_cache()

    stats = {
        "白名单": 0,
        "黑名单": 0,
        "名称确认": 0,
        "API失败": 0,
        "非指数": 0,
        "非增强": 0,
        "非权益": 0,
    }

    # 第一部分：白名单优先加入

    print(f"\n加载白名单: {len(manual_include)}")

    for idx, item in enumerate(manual_include):
        code = str(item["fund_code"]).zfill(6)

        if code in manual_exclude:
            stats["黑名单"] += 1
            excluded.append({
                "fund_code": code,
                "fund_name": item["fund_name"],
                "exclude_reason": "人工维护黑名单",
                "update_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            continue

        if code in verified_codes:
            continue

        print(
            f"\r  白名单 [{idx + 1}/{len(manual_include)}]"
            f" {code} {item['fund_name'][:20]}",
            end="",
            flush=True,
        )

        # 白名单人工确认过，不需要调 API，直接加入
        verified.append(_make_verified_entry(
            code=code,
            name=item["fund_name"],
            index=item["benchmark_index"],
            detail=None,
            source="manual_include",
            reason="白名单手动加入",
        ))

        verified_codes.add(code)
        stats["白名单"] += 1

    # ==================================================
    # 第二部分：自动验证
    # ==================================================

    print("\n开始自动验证...")

    for i, (_, row) in enumerate(candidates.iterrows()):
        code = row["fund_code"]
        name = row["fund_name"]

        print(
            f"\r[{i + 1}/{len(candidates)}]"
            f" 已通过:{len(verified)} "
            f"{code} {name[:20]}",
            end="",
            flush=True,
        )

        # 已经人工加入
        if code in verified_codes:
            continue

        # 黑名单
        if code in manual_exclude:
            stats["黑名单"] += 1
            excluded.append({
                "fund_code": code,
                "fund_name": name,
                "exclude_reason": "人工维护黑名单",
                "update_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            continue

        # 名称同时命中指数关键词 + 增强关键词 → 直接通过，无需调 API
        if row.get("hit_reason") == "both" and row.get("coarse_index") != "unknown":
            index = row["coarse_index"]
            verified.append(_make_verified_entry(
                code=code,
                name=name,
                index=index,
                detail=None,
                source="name_both_confirm",
                reason=f"名称同时命中{INDEX_NAMES.get(index, index)}与增强关键词",
            ))
            verified_codes.add(code)
            stats["名称确认"] += 1
            continue

        detail = _fetch_fund_detail_xq(code, cache)

        # ==================================================
        # API失败降级：名称同时命中指数+增强 → 纳为候选
        # ==================================================

        if detail is None:
            index = _match_index(name)

            if index and _has_enhance_keyword(name):
                verified.append(_make_verified_entry(
                    code=code,
                    name=name,
                    index=index,
                    detail=None,
                    source="api_failed_name_confirm",
                    reason=f"API失败降级——名称同时命中{INDEX_NAMES.get(index, index)}与增强关键词",
                ))
                verified_codes.add(code)
            else:
                stats["API失败"] += 1
                fail_entry = {
                    "fund_code": code,
                    "fund_name": name,
                    "coarse_index": row.get("coarse_index", ""),
                    "hit_reason": row.get("hit_reason", ""),
                    "share_class": _extract_share_class(name),
                    "fail_reason": "API请求失败（已重试{}次）".format(MAX_RETRIES),
                    "update_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                api_failed.append(fail_entry)
                excluded.append({
                    "fund_code": code,
                    "fund_name": name,
                    "exclude_reason": "API请求失败，无法验证",
                    "update_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                })

            continue

        fund_type = detail.get("fund_type", "")

        if any(x in fund_type for x in ["债券", "货币", "可转债"]):
            stats["非权益"] += 1
            excluded.append({
                "fund_code": code,
                "fund_name": name,
                "exclude_reason": f"非权益类基金（{fund_type}）",
                "update_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            continue

        index, index_reason = _identify_index_from_detail(
            name,
            detail.get("benchmark", ""),
            detail.get("objective", ""),
        )

        if index is None:
            stats["非指数"] += 1
            excluded.append({
                "fund_code": code,
                "fund_name": name,
                "exclude_reason": "未匹配到目标指数（沪深300/中证500/中证1000/中证全指）",
                "update_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            continue

        is_enh, enhance_reason = _is_index_enhancement(
            name,
            detail.get("objective", ""),
            detail.get("fund_type", ""),
        )

        if not is_enh:
            stats["非增强"] += 1
            excluded.append({
                "fund_code": code,
                "fund_name": name,
                "exclude_reason": "非指数增强策略（被动指数基金或主动管理）",
                "update_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            continue

        # 组合入选理由
        reason = f"{index_reason}; {enhance_reason}"

        verified.append(_make_verified_entry(
            code=code,
            name=name,
            index=index,
            detail=detail,
            source="api_verify",
            reason=reason,
        ))

        verified_codes.add(code)

        # 定期保存缓存（跳过 0 避免首次空保存）
        if len(verified) > 0 and len(verified) % CACHE_SAVE_INTERVAL == 0:
            _save_detail_cache(cache)

    print()

    _save_detail_cache(cache)

    df = pd.DataFrame(verified)

    print("\n验证完成")
    print(f"最终基金: {len(df)}")
    print(f"被筛去: {len(excluded)}")
    print(f"API失败: {len(api_failed)}")

    print("\n统计:")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    return df, api_failed, excluded


# Step 4: 保存基金主表

def save_fund_master(fund_pool, api_failed=None, excluded=None):
    print("\n" + "=" * 60)
    print("Step 4 / 4 保存基金主表")
    print("=" * 60)

    if fund_pool.empty:
        print("⚠ 基金池为空")
    else:
        # 去重
        fund_pool = fund_pool.drop_duplicates(subset="fund_code", keep="first")

        # 排序
        idx_order = {
            "HS300": 0,
            "ZZ500": 1,
            "ZZ1000": 2,
            "CSI_ALL": 3,
        }

        if "benchmark_index" in fund_pool.columns:
            fund_pool["_sort"] = (
                fund_pool["benchmark_index"].map(idx_order).fillna(9)
            )
            fund_pool = (
                fund_pool
                .sort_values(["_sort", "fund_code"])
                .drop(columns="_sort")
            )

        fund_pool.to_parquet(FUND_MASTER_PATH, index=False)

        # 同时输出 CSV，方便 Excel 直接打开检查
        csv_path = os.path.join(DATA_DIR, "fund_master.csv")
        fund_pool.to_csv(csv_path, index=False, encoding="utf-8-sig")

        print(f"✓ 基金池保存: {FUND_MASTER_PATH}")
        print(f"✓ CSV 已导出: {csv_path}")
        print(f"基金数量: {len(fund_pool)}")

        print("\n前20只:")

        show_cols = ["fund_code", "fund_name", "share_class", "benchmark_index", "source", "reason"]
        show_cols = [c for c in show_cols if c in fund_pool.columns]

        print(fund_pool[show_cols].head(20).to_string(index=False))

    # ── 保存 API 调取失败的基金 ──
    if api_failed is not None and len(api_failed) > 0:
        df_failed = pd.DataFrame(api_failed)
        df_failed = df_failed.drop_duplicates(subset="fund_code", keep="first")
        df_failed = df_failed.sort_values("fund_code")

        df_failed.to_parquet(API_FAILED_PATH, index=False)

        csv_failed_path = os.path.join(DATA_DIR, "api_failed.csv")
        df_failed.to_csv(csv_failed_path, index=False, encoding="utf-8-sig")

        print(f"\n✓ API失败基金保存: {API_FAILED_PATH}")
        print(f"✓ CSV 已导出: {csv_failed_path}")
        print(f"API失败基金数量: {len(df_failed)}")
    elif api_failed is not None:
        print(f"\n✓ 无API失败基金")

    # ── 保存被筛去的基金 ──
    if excluded is not None and len(excluded) > 0:
        df_excluded = pd.DataFrame(excluded)
        df_excluded = df_excluded.drop_duplicates(subset="fund_code", keep="first")
        df_excluded = df_excluded.sort_values("fund_code")

        df_excluded.to_parquet(EXCLUDED_PATH, index=False)

        csv_excluded_path = os.path.join(DATA_DIR, "excluded_funds.csv")
        df_excluded.to_csv(csv_excluded_path, index=False, encoding="utf-8-sig")

        print(f"\n✓ 被筛去基金保存: {EXCLUDED_PATH}")
        print(f"✓ CSV 已导出: {csv_excluded_path}")
        print(f"被筛去基金数量: {len(df_excluded)}")

        # 按原因分组统计
        print("\n  筛去原因分布:")
        for reason, count in df_excluded["exclude_reason"].value_counts().items():
            print(f"    {reason}: {count}")
    elif excluded is not None:
        print(f"\n✓ 无被筛去基金")


# 主程序

def main():
    print("\n" + "=" * 60)
    print("指数增强基金池构建程序")
    print("优化版: cache + retry + manual rules")
    print("=" * 60)

    ensure_dirs()

    # 1. 全市场基金
    all_funds = get_all_funds()

    # 2. 粗筛
    candidates = build_candidate_pool(all_funds)

    if candidates.empty:
        print("⚠ 无候选基金")
        return

    # 3. 验证
    fund_pool, api_failed, excluded = verify_index_enhancement(candidates)

    if fund_pool.empty and len(api_failed) == 0:
        print("⚠ 最终基金池为空且无API失败记录")
        return

    # 4. 保存
    save_fund_master(fund_pool, api_failed, excluded)

    print("\n" + "=" * 60)
    print("基金池构建完成 ✓")
    print(f"共 {len(fund_pool)} 只")
    print("=" * 60)


if __name__ == "__main__":
    main()
