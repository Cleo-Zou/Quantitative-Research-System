import os

# 项目路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
NAV_DIR = os.path.join(DATA_DIR, "nav")
INDEX_DIR = os.path.join(DATA_DIR, "index")

FUND_MASTER_PATH = os.path.join(DATA_DIR, "fund_master.parquet")
METRICS_PATH = os.path.join(DATA_DIR, "metrics.parquet")
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
    "增强",
]

# 排除关键词（ETF / 联接 —— 只是跟踪指数，不是增强）

EXCLUDE_PATTERNS = [
    "ETF",
    "联接",
    "LOF",
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

# API 请求控制

REQUEST_DELAY = 0.6          # 每次 API 调用间隔（秒），避免被封
MAX_RETRIES = 2               # 单只基金详情最多重试次数
BATCH_SAVE_INTERVAL = 20      # 每验证 N 只基金，保存一次中间结果
