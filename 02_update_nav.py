import os
import random
import time
from datetime import date

import pandas as pd
import akshare as ak

from config import (
    DATA_DIR,
    NAV_DIR,
    FUND_MASTER_PATH,
    REQUEST_DELAY,
    MAX_RETRIES,
)
from utils import (
    find_col,
    format_seconds,
    get_last_business_day,
    safe_read_parquet,
    safe_write_parquet,
)


def ensure_dirs():
    log_dir = os.path.join(DATA_DIR, "log")
    for d in [DATA_DIR, NAV_DIR, log_dir]:
        os.makedirs(d, exist_ok=True)


def load_fund_master() -> list[str]:
    df = pd.read_parquet(FUND_MASTER_PATH)
    codes = df["fund_code"].astype(str).str.zfill(6).tolist()
    print(f"读取基金池: {FUND_MASTER_PATH}")
    print(f"共 {len(codes)} 只基金待更新\n")
    return codes


def fetch_fund_nav(fund_code: str) -> pd.DataFrame | None:
   
    for attempt in range(1 + MAX_RETRIES):
        try:
            # ── 第一次: 单位净值 ──
            df_unit = ak.fund_open_fund_info_em(
                symbol=fund_code,
                indicator="单位净值走势",
            )
            if df_unit is None or df_unit.empty:
                return None

            unit_date_col = find_col(df_unit, "净值日期", "日期", "date")
            unit_val_col = find_col(df_unit, "单位净值", "unit")

            if unit_date_col is None or unit_val_col is None:
                return None

            result = pd.DataFrame()
            result["date"] = pd.to_datetime(df_unit[unit_date_col]).dt.date
            result["unit_nav"] = pd.to_numeric(
                df_unit[unit_val_col], errors="coerce"
            )

            # ── 第二次: 累计净值（作为 adj_nav） ──
            time.sleep(random.uniform(0.2, 0.5))  # 同基金两次调用间随机停顿，降低频率限制触发概率
            df_acc = ak.fund_open_fund_info_em(
                symbol=fund_code,
                indicator="累计净值走势",
            )

            if df_acc is not None and not df_acc.empty:
                acc_date_col = find_col(df_acc, "净值日期", "日期", "date")
                acc_val_col = find_col(df_acc, "累计净值", "acc")
                if acc_date_col and acc_val_col:
                    df_acc_mapped = pd.DataFrame()
                    df_acc_mapped["date"] = pd.to_datetime(
                        df_acc[acc_date_col]
                    ).dt.date
                    df_acc_mapped["adj_nav"] = pd.to_numeric(
                        df_acc[acc_val_col], errors="coerce"
                    )
                    result = result.merge(df_acc_mapped, on="date", how="outer")

            # 如果累计净值获取失败，用单位净值兜底
            if "adj_nav" not in result.columns:
                result["adj_nav"] = result["unit_nav"]

            result["update_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
            result = result.dropna(subset=["date"])
            result = result.sort_values("date").reset_index(drop=True)
            return result

        except Exception as e:
            if attempt < MAX_RETRIES:
                time.sleep(REQUEST_DELAY * 2)
            else:
                raise  # 最后一次重试失败，向上抛出以便记录详细原因


def load_existing_nav(fund_code: str) -> pd.DataFrame | None:
    path = os.path.join(NAV_DIR, f"{fund_code}.parquet")
    df = safe_read_parquet(path)
    if df is not None:
        df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def save_nav(fund_code: str, df: pd.DataFrame):
    df = df.drop_duplicates(subset=["date"], keep="last")
    df = df.sort_values("date").reset_index(drop=True)
    path = os.path.join(NAV_DIR, f"{fund_code}.parquet")
    safe_write_parquet(df, path)


def update_single_fund_nav(fund_code: str) -> dict:
    existing = load_existing_nav(fund_code)
    last_date = None if existing is None else existing["date"].max()

    # 已是最新：跳过 API 调用
    if existing is not None and last_date is not None:
        last_biz_day = get_last_business_day()
        if last_date >= last_biz_day:
            return {
                "fund_code": fund_code, "status": "ok", "new": 0,
                "reason": f"已最新 (last={last_date}, biz_day={last_biz_day})",
            }

    try:
        fresh = fetch_fund_nav(fund_code)
    except Exception as e:
        return {
            "fund_code": fund_code, "status": "fail", "new": 0,
            "reason": f"{type(e).__name__}: {e}",
        }
    if fresh is None:
        return {"fund_code": fund_code, "status": "fail", "new": 0, "reason": "API返回空数据"}

    now = time.strftime("%Y-%m-%d %H:%M:%S")

    if existing is None:
        merged = fresh
        new_count = len(fresh)
    else:
        if "update_time" not in existing.columns:
            existing["update_time"] = now
        if last_date is not None:
            new_data = fresh[fresh["date"] > last_date]
        else:
            new_data = fresh
        if new_data.empty:
            return {"fund_code": fund_code, "status": "ok", "new": 0, "reason": ""}
        merged = pd.concat([existing, new_data], ignore_index=True)
        new_count = len(new_data)

    save_nav(fund_code, merged)
    return {"fund_code": fund_code, "status": "ok", "new": new_count, "reason": ""}


def update_all_nav(fund_codes: list[str]) -> dict:
    total = len(fund_codes)
    ok_list: list[str] = []
    fail_list: list[dict] = []  # 现在存储 {code, reason, time}
    total_new = 0
    t_start = time.time()

    for i, code in enumerate(fund_codes):
        pct = (i + 1) / total * 100
        elapsed = time.time() - t_start
        avg = elapsed / (i + 1) if i > 0 else REQUEST_DELAY
        eta = format_seconds(avg * (total - i - 1))

        result = update_single_fund_nav(code)

        if result["status"] == "ok":
            ok_list.append(code)
            total_new += result["new"]
            tag = f"+{result['new']}" if result["new"] > 0 else " 不变"
        else:
            fail_list.append({
                "fund_code": code,
                "reason": result.get("reason", ""),
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            tag = "失败"

        print(
            f"\r  [{i + 1:>4}/{total} {pct:>4.0f}%]  "
            f"✓{len(ok_list):>4}  ✗{len(fail_list):>3}  "
            f"剩余≈{eta:<8s}  "
            f"{code} {tag}",
            end="", flush=True,
        )

        time.sleep(REQUEST_DELAY)

    print()
    elapsed = time.time() - t_start
    return {
        "total": total,
        "ok": len(ok_list),
        "fail": len(fail_list),
        "total_new": total_new,
        "elapsed": elapsed,
        "fail_list": fail_list,
    }


def write_log(stats: dict):
    today = time.strftime("%Y%m%d")
    log_path = os.path.join(DATA_DIR, "log", f"nav_update_{today}.log")
    lines = [
        f"净值更新日志  {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"{'─' * 40}",
        f"基金总数: {stats['total']}",
        f"成功:     {stats['ok']}",
        f"失败:     {stats['fail']}",
        f"新增记录: {stats['total_new']}",
        f"耗时:     {format_seconds(stats['elapsed'])}",
    ]
    if stats["fail_list"]:
        lines.append(f"{'─' * 40}")
        lines.append("失败详情:")
        for item in stats["fail_list"]:
            lines.append(
                f"  {item['time']}  {item['fund_code']}  {item['reason']}"
            )
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n日志已保存: {log_path}")


def main():
    print("\n" + "█" * 50)
    print("█  指数增强基金净值更新")
    print("█  数据来源: 天天基金 (via AKShare)")
    print("█" * 50)

    ensure_dirs()
    fund_codes = load_fund_master()

    if not fund_codes:
        print("基金池为空，请先运行 01_build_fund_pool.py")
        return

    total = len(fund_codes)
    eta = format_seconds(total * REQUEST_DELAY)
    print(f"预计耗时 ≈ {eta}（{total} 只 × {REQUEST_DELAY}s）\n")

    stats = update_all_nav(fund_codes)

    print(f"\n{'─' * 40}")
    print(f"更新完成")
    print(f"  成功: {stats['ok']}")
    print(f"  失败: {stats['fail']}")
    print(f"  新增: {stats['total_new']} 条记录")
    print(f"  耗时: {format_seconds(stats['elapsed'])}")
    print(f"{'─' * 40}")

    write_log(stats)

    print("\n" + "█" * 50)
    print("█  净值更新完成 ✓")
    print("█" * 50)


if __name__ == "__main__":
    main()
