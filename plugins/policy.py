"""插件：知识问答（复用 xiao_wen.rag 向量 RAG 后端）"""
# 懒加载哨兵：只有本模块被 exec_module 时才输出（证明懒加载生效）
print("  ⚠️ [policy] 模块已执行（懒加载触发）")

import os
import sys

# 插件被注册中心以文件路径 exec_module 加载，需自行把 src/ 加入搜索路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from xiao_wen import rag as _rag  # noqa: E402

# ---- 插件元数据（注册中心 AST 只读这两行，不执行代码） ----
INTENT = "知识问答"
DESCRIPTION = "回答企业差旅政策、报销规则、预订流程、住宿标准等知识问题（向量检索知识库）"


def run(query: str) -> str:
    """统一插件接口：query 进，文本答出"""
    return _rag.knowledge_qa(query)
