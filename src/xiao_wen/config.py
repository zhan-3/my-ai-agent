"""运行时配置单一入口：.env 优先、类型化读取、按能力懒校验。"""

import os
from dataclasses import dataclass

from dotenv import dotenv_values

from xiao_wen import ROOT

ENV_FILE = ROOT / ".env"

LLM_ENV_VARS = ("DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL", "DEEPSEEK_API_KEY")
EMBED_ENV_VAR = "DASHSCOPE_API_KEY"
_PUBLIC_JWT_SECRET = "dev-secret-change-me-in-prod-0123456789abcdef"


@dataclass(frozen=True)
class LLMConfig:
    model: str
    base_url: str
    api_key: str


@dataclass(frozen=True)
class Settings:
    deepseek_model: str
    deepseek_base_url: str
    deepseek_api_key: str
    dashscope_api_key: str
    dashscope_emb_model: str
    dashscope_emb_dim: str
    rag_min_sim: str
    postgres_url: str
    jwt_secret: str

    def require_llm(self) -> LLMConfig:
        values = (self.deepseek_model, self.deepseek_base_url, self.deepseek_api_key)
        missing = [name for name, value in zip(LLM_ENV_VARS, values, strict=True) if not value]
        if missing:
            raise RuntimeError(f"缺少 LLM 必需环境变量：{', '.join(missing)}（请在 .env 中配置）")
        return LLMConfig(*values)

    def require_embedding_key(self) -> str:
        if not self.dashscope_api_key:
            raise RuntimeError(f"缺少 embedding 必需环境变量：{EMBED_ENV_VAR}（请在 .env 中配置）")
        return self.dashscope_api_key

    def embedding_dimension(self, default: int = 1024) -> int:
        if not self.dashscope_emb_dim:
            return default
        try:
            return int(self.dashscope_emb_dim)
        except ValueError as error:
            raise RuntimeError("DASHSCOPE_EMB_DIM 必须是整数") from error

    def minimum_similarity(self, default: float = 0.35) -> float:
        if not self.rag_min_sim:
            return default
        try:
            return float(self.rag_min_sim)
        except ValueError as error:
            raise RuntimeError("RAG_MIN_SIM 必须是数字") from error

    def require_postgres_url(self) -> str:
        if not self.postgres_url:
            message = "存储需要 POSTGRES_URL（唯一后端 Postgres）："
            message += "docker compose up -d postgres && export POSTGRES_URL=..."
            raise RuntimeError(message)
        return self.postgres_url

    def require_jwt_secret(self) -> str:
        if not self.jwt_secret:
            raise RuntimeError("JWT_SECRET 未配置（请在 .env 中设置至少 32 字节的随机密钥）")
        if self.jwt_secret == _PUBLIC_JWT_SECRET:
            raise RuntimeError("JWT_SECRET 仍是公开开发默认值，请更换为至少 32 字节的随机密钥")
        if len(self.jwt_secret.encode()) < 32:
            raise RuntimeError("JWT_SECRET 长度不足 32 字节")
        return self.jwt_secret

    def validate_web(self) -> None:
        self.require_postgres_url()
        self.require_jwt_secret()


def load_settings() -> Settings:
    """读取运行时配置；项目 .env 覆盖同名继承变量，不修改进程环境。"""
    values = dict(os.environ)
    file_values = {name: value for name, value in dotenv_values(ENV_FILE).items() if value is not None}
    values.update(file_values)
    postgres_url = values.get("POSTGRES_TEST_URL") or values.get("POSTGRES_URL", "")
    return Settings(
        deepseek_model=values.get("DEEPSEEK_MODEL", ""),
        deepseek_base_url=values.get("DEEPSEEK_BASE_URL", ""),
        deepseek_api_key=values.get("DEEPSEEK_API_KEY", ""),
        dashscope_api_key=values.get(EMBED_ENV_VAR, ""),
        dashscope_emb_model=values.get("DASHSCOPE_EMB_MODEL", "text-embedding-v3"),
        dashscope_emb_dim=values.get("DASHSCOPE_EMB_DIM", ""),
        rag_min_sim=values.get("RAG_MIN_SIM", ""),
        postgres_url=postgres_url,
        jwt_secret=values.get("JWT_SECRET", ""),
    )
