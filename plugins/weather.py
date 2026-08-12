"""插件：联网查询（复用 xiao_wen.web 的天气工具）"""
# 懒加载哨兵
print("  ⚠️ [weather] 模块已执行（懒加载触发）")

import os
import re
import sys

# 插件被注册中心以文件路径 exec_module 加载，需自行把 src/ 加入搜索路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from xiao_wen import web as _web  # noqa: E402

# ---- 插件元数据 ----
INTENT = "联网查询"
DESCRIPTION = "查询实时信息：指定城市的天气、汇率、空气质量"

_CITIES = "北京|上海|广州|深圳|杭州|成都|武汉|西安|南京|苏州|重庆|天津|长沙|青岛"


def run(query: str) -> str:
    """统一插件接口：从 query 抽城市 → 调真实天气 API"""
    m = re.search(rf"({_CITIES})", query)
    city = m.group(1) if m else "北京"
    # @tool 装饰后是 StructuredTool 对象，.func 取回原始函数直接调用
    return _web.get_weather.func(city)
