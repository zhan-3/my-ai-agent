"""插件：知识问答（复用 homework/0008 向量 RAG 后端）"""
# 懒加载哨兵：只有本模块被 exec_module 时才输出（证明懒加载生效）
print("  ⚠️ [policy] 模块已执行（懒加载触发）")

import importlib.util
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "homework"))
_rag_path = os.path.join(os.path.dirname(__file__), "..", "homework", "0008_rag_vector.py")
_spec = importlib.util.spec_from_file_location("rag_backend", _rag_path)
if _spec is None or _spec.loader is None:
    raise ImportError(f"无法加载后端：{_rag_path}")
_rag = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rag)

# ---- 插件元数据（注册中心 AST 只读这两行，不执行代码） ----
INTENT = "知识问答"
DESCRIPTION = "回答企业差旅政策、报销规则、预订流程、住宿标准等知识问题（向量检索知识库）"


def run(query: str) -> str:
    """统一插件接口：query 进，文本答出"""
    return _rag.knowledge_qa(query)
