# config.py
import os

# 模型路由映射：统一模型名 -> (适配器类型, 实际模型名)
MODEL_ROUTING = {
    "deepseek-v4-pro": ("deepseek", "deepseek-v4-pro"),
    "deepseek-v4-flash": ("deepseek", "deepseek-v4-flash"),
}

# API Keys（建议从环境变量读取）
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "sk-xxx")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "sk-ant-xxx")

# 限流配置：每模型每分钟请求上限
RATE_LIMITS = {
    "deepseek-v4-pro": 100,   # 每分钟100次
    "deepseek-v4-flash": 120,
}

# 重试配置
RETRY_CONFIG = {
    "max_attempts": 3,
    "base_delay": 1.0,
    "max_delay": 10.0,
    "exponential_base": 2,
}
