"""认证模块：JWT 无状态认证（pyjwt）+ 用户存储（唯一后端 Postgres users 表）

- 决策集（grilling 定案）：JWT（不选 Session Cookie/OAuth）+ bcrypt 密码哈希
  + 用户存储唯一后端 Postgres（memory_pg.PostgresUserStore，POSTGRES_URL 必配）
- 会话隔离升级（ADR-0007）：认证后 webapp 层把 JWT 解出的用户名作为会话维度
  （session_id = user_id），客户端不再自填 session_id——「会话隔离」升级为「用户隔离」
- JWT_SECRET：环境变量注入；未设时用开发默认值（生产必须显式设置，见 README）
- 依赖懒导入：psycopg 仅在 PostgresUserStore 构造路径触发
"""

import os
import time
from typing import Protocol

import bcrypt
import jwt

# 开发默认密钥（仅演示/本地；生产必须通过 JWT_SECRET 覆盖，见 README）
# 长度 ≥ 32 字节，满足 RFC 7518 HMAC-SHA256 最小密钥建议，避免测试刷警告
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me-in-prod-0123456789abcdef")
TOKEN_TTL_SECONDS = 7 * 24 * 3600  # 7 天


class UserStore(Protocol):
    """用户存储：用户名唯一，只存 bcrypt 哈希（认证域专属，不混进记忆三域）"""

    def register(self, username: str, password_hash: str) -> dict | None: ...

    def get_user(self, username: str) -> dict | None: ...


# ---- 模块级当前用户存储（测试注入 set_user_store；生产懒构造 Postgres） ----
_user_store: UserStore | None = None


def set_user_store(store: UserStore) -> None:
    """注入用户存储（测试注入 PostgresUserStore(test_url) 隔离）"""
    global _user_store  # noqa: PLW0603 —— 注入是模块级状态的刻意设计
    _user_store = store


def _get_user_store() -> UserStore:
    """懒构造产品后端：Postgres users 表（唯一后端）。未配 POSTGRES_URL 直接报错。"""
    global _user_store  # noqa: PLW0603
    if _user_store is None:
        url = os.environ.get("POSTGRES_URL")
        if not url:
            raise RuntimeError(
                "用户存储需要 POSTGRES_URL（唯一后端 Postgres）："
                "docker compose up -d postgres && export POSTGRES_URL=..."
            )
        from xiao_wen.memory_pg import PostgresUserStore  # 懒导入：pg 依赖可选

        _user_store = PostgresUserStore(url)
    return _user_store


# ---------- 密码哈希（bcrypt，用户拍板；两次哈希不同 = 盐生效） ----------
def hash_password(password: str) -> str:
    """bcrypt 哈希（自动带盐）"""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """校验密码；格式非法（非 bcrypt）返回 False 而不是抛异常"""
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


# ---------- JWT 签发与校验（HS256，payload 只含 sub + exp） ----------
def create_token(username: str, secret: str | None = None) -> str:
    """签发 token：sub = 用户名（即会话维度），exp = 7 天"""
    now = int(time.time())
    return jwt.encode(
        {"sub": username, "iat": now, "exp": now + TOKEN_TTL_SECONDS},
        secret or JWT_SECRET,
        algorithm="HS256",
    )


def decode_token(token: str, secret: str | None = None) -> str | None:
    """解出用户名；无效/过期/伪造一律 None"""
    try:
        payload = jwt.decode(token, secret or JWT_SECRET, algorithms=["HS256"])
        sub = payload.get("sub")
        return sub if isinstance(sub, str) else None
    except jwt.InvalidTokenError:
        return None


# ---------- 认证服务（纯逻辑：注册 / 登录 / 校验） ----------
def register(username: str, password: str) -> str | None:
    """注册并直接登录（返回 token）；用户名冲突返回 None。用户名即会话维度。"""
    username = username.strip()
    if not username or not password:
        return None
    hashed = hash_password(password)
    if _get_user_store().register(username, hashed) is None:
        return None
    return create_token(username)


def login(username: str, password: str) -> str | None:
    """登录：校验密码 → 返回 token；失败（用户不存在 / 密码错）返回 None"""
    rec = _get_user_store().get_user(username.strip())
    if rec is None or not verify_password(password, rec.get("password_hash", "")):
        return None
    return create_token(rec["username"])


def authenticate(token: str) -> str | None:
    """校验请求携带的 token → 返回用户名（None = 未登录/失效）"""
    return decode_token(token)
