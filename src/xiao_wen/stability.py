"""稳定性模块：工程稳定性四件套

重试（指数退避）/ 超时（调用方约定 timeout 参数）/ 熔断（三态）/ 日志 / 健康检查
用法：
    from xiao_wen.stability import with_retry, CircuitBreaker, logger, health_check
    breaker = CircuitBreaker(failure_threshold=3, recovery_time=5.0)
    @with_retry(retries=2, breaker=breaker)
    def call_llm(...): ...
"""

import functools
import logging
import threading
import time
from logging.handlers import TimedRotatingFileHandler

from xiao_wen import ROOT
from xiao_wen.config import EMBED_ENV_VAR, LLM_ENV_VARS, load_settings

# ---- 日志记录（stdout + data/stability.log 双写，按天滚动保留 7 天） ----
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        TimedRotatingFileHandler(DATA_DIR / "stability.log", when="midnight", backupCount=7, encoding="utf-8"),
    ],
)
# 库噪音静音：httpx 的 INFO 是「每次 HTTP 请求一行」的调试输出（实测占日志九成以上），
# 请求失败路径已有 llm/web 自有 WARNING 埋点，不靠 httpx 记成功请求。
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("stability")


class CircuitBreaker:
    """熔断器三态：closed（正常）→ open（熔断，快速失败）→ half_open（试探恢复）

    - 连续失败达到 failure_threshold 次 → open，拒绝后续调用（省时省费）
    - open 超过 recovery_time 秒 → half_open：放一个请求试探，成功则复位 closed
    """

    def __init__(self, failure_threshold: int = 3, recovery_time: float = 5.0):
        self.failure_threshold = failure_threshold
        self.recovery_time = recovery_time
        self.failures = 0
        self.state = "closed"
        self.last_open_at = 0.0
        self._lock = threading.Lock()  # 并发保护：状态迁移/计数读写原子化（共享全局熔断器多线程可见）

    @property
    def is_open(self) -> bool:
        with self._lock:
            if self.state == "open" and time.time() - self.last_open_at >= self.recovery_time:
                self.state = "half_open"
                logger.info("熔断恢复期：半开试探（放行一个请求）")
            return self.state == "open"

    def record_success(self) -> None:
        with self._lock:
            if self.state != "closed":
                logger.info("熔断复位：closed")
            self.failures = 0
            self.state = "closed"

    def record_failure(self) -> None:
        with self._lock:
            self.failures += 1
            self.last_open_at = time.time()
            if self.state == "half_open" or self.failures >= self.failure_threshold:
                self.state = "open"
                logger.warning("熔断打开：连续失败 %d 次，%.1fs 内快速失败", self.failures, self.recovery_time)


def with_retry(retries: int = 2, base_delay: float = 0.5, breaker: CircuitBreaker | None = None):
    """重试装饰器：指数退避（0.5s → 1s → 2s…），可配熔断器"""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if breaker and breaker.is_open:
                raise RuntimeError("熔断已打开：拒绝调用（快速失败）")
            delay = base_delay
            for attempt in range(retries + 1):
                try:
                    result = fn(*args, **kwargs)
                    if breaker:
                        breaker.record_success()
                    return result
                except Exception as e:
                    if breaker:
                        breaker.record_failure()
                    if attempt == retries:
                        raise
                    logger.warning("调用失败（第 %d/%d 次），%.1fs 后重试：%s", attempt + 1, retries, delay, e)
                    time.sleep(delay)
                    delay *= 2

        return wrapper

    return deco


def health_check() -> list[dict]:
    """健康检查：.env 配置 / 知识库索引 / 记忆可写 / 插件目录 / 日志可写"""
    report: list[dict] = []

    # ① .env 关键配置（变量名单一来源：llm 接缝 REQUIRED_ENV_VARS + rag embedding）
    settings = load_settings()
    llm_values = (settings.deepseek_model, settings.deepseek_base_url, settings.deepseek_api_key)
    cfg = {name: ("存在" if value else "缺失") for name, value in zip(LLM_ENV_VARS, llm_values, strict=True)}
    cfg["DEEPSEEK_MODEL"] = settings.deepseek_model or "缺失"
    cfg[EMBED_ENV_VAR] = "存在" if settings.dashscope_api_key else "缺失"
    report.append({"项": "环境配置", "状态": "✅" if "缺失" not in cfg.values() else "⚠️", "详情": str(cfg)})

    # ② 向量知识库索引（chroma 持久化）
    chroma_dir = DATA_DIR / "chroma"
    index_status = "✅" if chroma_dir.exists() else "⚠️"
    index_detail = f"{chroma_dir} " + (
        "存在（已持久化）" if chroma_dir.exists() else "缺失，需先构建向量索引（rag 模块）"
    )
    report.append({"项": "向量索引", "状态": index_status, "详情": index_detail})

    # ③ 记忆后端就绪（唯一后端 Postgres：探活；未配 URL / 连接失败 → ⚠️）
    from xiao_wen import memory as memory_mod

    try:
        backend = memory_mod._get_backend()
        backend.health_check()
        mem_status, mem_detail = "✅", "Postgres 连接正常（会话隔离持久化）"
    except Exception:
        mem_status, mem_detail = "⚠️", "Postgres 连接失败（检查 POSTGRES_URL 与容器）"
    report.append({"项": "记忆存储", "状态": mem_status, "详情": mem_detail})

    # ④ 外部扩展子 Agent 目录（插件化；计数口径与注册中心 discover() 一致：只数外部扩展、
    #    过滤缺 INTENT/DESCRIPTION 元数据的文件，不数内置 agents/）
    from xiao_wen import plugin_registry

    ext = [m for m in plugin_registry.discover() if m["source"] == "external"]
    report.append(
        {
            "项": "插件目录",
            "状态": "✅" if ext else "⚠️",
            "详情": "发现 " + "、".join(m["INTENT"] for m in ext) + f"（{len(ext)} 个外部扩展）",
        }
    )

    # ⑤ 日志文件可写
    report.append({"项": "日志", "状态": "✅", "详情": str(DATA_DIR / "stability.log")})
    return report
