import os

# 项目路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
NAV_DIR = os.path.join(DATA_DIR, "nav")
INDEX_DIR = os.path.join(DATA_DIR, "index")

RETURN_DIR = os.path.join(DATA_DIR, "return")

FUND_MASTER_PATH = os.path.join(DATA_DIR, "fund_master.parquet")
FUND_RETURN_PATH = os.path.join(RETURN_DIR, "fund_return.parquet")
INDEX_RETURN_PATH = os.path.join(RETURN_DIR, "index_return.parquet")
EXCESS_RETURN_PATH = os.path.join(RETURN_DIR, "excess_return.parquet")
METRICS_PATH = os.path.join(DATA_DIR, "metrics.parquet")
MANUAL_EXCLUDE_PATH = os.path.join(DATA_DIR, "manual_exclude.csv")
MANUAL_INCLUDE_PATH = os.path.join(DATA_DIR, "manual_include.csv")
DASHBOARD_PATH = os.path.join(BASE_DIR, "dashboard.html")

# 目标指数 & 名称关键词（用于粗筛）

INDEX_KEYWORDS = {
    "HS300": [
        "沪深300",
        "HS300",
        "300增强",
        "300指数增强",
    ],
    "ZZ500": [
        "中证500",
        "ZZ500",
        "500增强",
        "500指数增强",
    ],
    "ZZ1000": [
        "中证1000",
        "ZZ1000",
        "1000增强",
        "1000指数增强",
    ],
    "CSI_ALL": [
        "中证全指",
        "CSI_ALL",
        "全指增强",
    ],
}

# 增强关键词（基金名称中出现 → 候选）

ENHANCE_KEYWORDS = [
    "指数增强",
    "增强策略",
    "增强指数",
    "指数量化增强",
    "量化增强",
    "基本面增强",
    "指数增强发起式",
]

# 排除关键词（ETF / 联接 —— 只是跟踪指数，不是增强）

EXCLUDE_PATTERNS = [
    "ETF",
    "联接",
    # 注意: "LOF" 已移除，因为存在"沪深300指数增强(LOF)"等合法产品
]

# 即使名称含"联接"，若同时含"增强"则保留（增强策略ETF联接）
EXCLUDE_EXCEPTIONS = [
    "增强",  # 增强策略ETF发起式联接 → 不排除
]

# 投资目标中的增强信号词（名称不含增强，但目标含这些词也视为增强）

ENHANCE_OBJECTIVE_KEYWORDS = [
    "超越指数",
    "增强收益",
    "超额收益",
    "跑赢指数",
    "战胜指数",
]

# 业绩比较基准 → 指数代码映射

BENCHMARK_INDEX_MAP = {
    "沪深300": "HS300",
    "中证500": "ZZ500",
    "中证1000": "ZZ1000",
    "中证全指": "CSI_ALL",
}

# 指数中文名（用于展示）

INDEX_NAMES = {
    "HS300": "沪深300",
    "ZZ500": "中证500",
    "ZZ1000": "中证1000",
    "CSI_ALL": "中证全指",
}

# 指数 → AKShare 代码（用于获取指数行情）

INDEX_AKSHARE_SYMBOLS = {
    "HS300": "sh000300",    # 沪深300 价格指数
    "ZZ500": "sh000905",    # 中证500 价格指数
    "ZZ1000": "sh000852",   # 中证1000 价格指数
    "CSI_ALL": "sh000985",  # 中证全指 价格指数（注意: Sina 源数据仅到 2016 年）
}

# 指数 → 中证指数公司 CSI 代码（用于获取估值 & 股息率）

INDEX_CSI_CODES = {
    "HS300": "000300",
    "ZZ500": "000905",
    "ZZ1000": "000852",
    "CSI_ALL": "000985",
}

# 缓存控制

INDEX_CACHE_MAX_AGE_HOURS = 24  # 指数行情缓存最大有效期（小时），超期自动刷新

# API 请求控制

REQUEST_DELAY = 0.6          # 每次 API 调用间隔（秒），避免被封
MAX_RETRIES = 2               # 单只基金详情最多重试次数
BATCH_SAVE_INTERVAL = 20      # 每验证 N 只基金，保存一次中间结果
