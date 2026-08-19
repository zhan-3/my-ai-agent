"""领域参考数据单一来源：常用城市与地理坐标。

统一此前分散在多个模块的硬编码数据：
- web.CITY_COORDS（城市经纬度表）
- history_agent._CITIES（历史查询城市过滤词表，由经纬度表派生）

新增或修改城市时只改这里，各消费方自动跟随，避免多份词表漂移。

车次、车站、票价和余票属于动态票务事实，不在本地参考数据中维护。
"""

# ---- 中国常用差旅城市经纬度表（本地内置，零依赖、永远可用） ----
# 真实产品可换数据库/地理编码服务；此处用于免去 geocoding API 依赖与限流
CITY_COORDS: dict[str, tuple[float, float]] = {
    "北京": (39.9042, 116.4074),
    "上海": (31.2304, 121.4737),
    "广州": (23.1291, 113.2644),
    "深圳": (22.5431, 114.0579),
    "杭州": (30.2741, 120.1551),
    "成都": (30.5728, 104.0668),
    "武汉": (30.5928, 114.3055),
    "西安": (34.3416, 108.9398),
    "南京": (32.0603, 118.7969),
    "苏州": (31.2989, 120.5853),
    "重庆": (29.5630, 106.5516),
    "天津": (39.3434, 117.3616),
    "长沙": (28.2282, 112.9388),
    "青岛": (36.0671, 120.3826),
    "厦门": (24.4798, 118.0894),
    "郑州": (34.7466, 113.6254),
    "沈阳": (41.8057, 123.4315),
    "大连": (38.9140, 121.6147),
    "昆明": (25.0389, 102.7183),
    "哈尔滨": (45.8038, 126.5350),
}

# 已知差旅城市（由经纬度表派生）：历史查询过滤、意图识别等共用同一份城市集合
KNOWN_CITIES: tuple[str, ...] = tuple(CITY_COORDS)

# ---- 常用国际出差城市 → IANA 时区（本地内置，零依赖）----
# 用于联网查询「当地时间/时差」；未收录的城市走 open-meteo geocoding 兜底（仅英文名有效）。
# 中国城市不在表中：全国统一 Asia/Shanghai，由 web._timezone_of 直接返回。
CITY_TIMEZONES: dict[str, str] = {
    # 亚洲
    "东京": "Asia/Tokyo",
    "大阪": "Asia/Tokyo",
    "名古屋": "Asia/Tokyo",
    "首尔": "Asia/Seoul",
    "釜山": "Asia/Seoul",
    "新加坡": "Asia/Singapore",
    "香港": "Asia/Hong_Kong",
    "台北": "Asia/Taipei",
    "澳门": "Asia/Macau",
    "曼谷": "Asia/Bangkok",
    "吉隆坡": "Asia/Kuala_Lumpur",
    "雅加达": "Asia/Jakarta",
    "马尼拉": "Asia/Manila",
    "孟买": "Asia/Kolkata",
    "新德里": "Asia/Kolkata",
    "迪拜": "Asia/Dubai",
    "多哈": "Asia/Qatar",
    "伊斯坦布尔": "Europe/Istanbul",
    "特拉维夫": "Asia/Jerusalem",
    "河内": "Asia/Ho_Chi_Minh",
    "胡志明市": "Asia/Ho_Chi_Minh",
    # 欧洲
    "伦敦": "Europe/London",
    "巴黎": "Europe/Paris",
    "柏林": "Europe/Berlin",
    "法兰克福": "Europe/Berlin",
    "慕尼黑": "Europe/Berlin",
    "汉堡": "Europe/Berlin",
    "阿姆斯特丹": "Europe/Amsterdam",
    "苏黎世": "Europe/Zurich",
    "日内瓦": "Europe/Zurich",
    "马德里": "Europe/Madrid",
    "巴塞罗那": "Europe/Madrid",
    "米兰": "Europe/Rome",
    "罗马": "Europe/Rome",
    "莫斯科": "Europe/Moscow",
    "斯德哥尔摩": "Europe/Stockholm",
    "哥本哈根": "Europe/Copenhagen",
    "都柏林": "Europe/Dublin",
    "华沙": "Europe/Warsaw",
    "布拉格": "Europe/Prague",
    "维也纳": "Europe/Vienna",
    "布鲁塞尔": "Europe/Brussels",
    "里斯本": "Europe/Lisbon",
    # 美洲
    "纽约": "America/New_York",
    "波士顿": "America/New_York",
    "华盛顿": "America/New_York",
    "费城": "America/New_York",
    "迈阿密": "America/New_York",
    "洛杉矶": "America/Los_Angeles",
    "旧金山": "America/Los_Angeles",
    "西雅图": "America/Los_Angeles",
    "芝加哥": "America/Chicago",
    "丹佛": "America/Denver",
    "多伦多": "America/Toronto",
    "温哥华": "America/Vancouver",
    "墨西哥城": "America/Mexico_City",
    "圣保罗": "America/Sao_Paulo",
    "布宜诺斯艾利斯": "America/Argentina/Buenos_Aires",
    "圣地亚哥": "America/Santiago",
    "利马": "America/Lima",
    # 大洋洲
    "悉尼": "Australia/Sydney",
    "墨尔本": "Australia/Melbourne",
    "堪培拉": "Australia/Sydney",
    "布里斯班": "Australia/Brisbane",
    "珀斯": "Australia/Perth",
    "奥克兰": "Pacific/Auckland",
    "惠灵顿": "Pacific/Auckland",
    # 非洲
    "开罗": "Africa/Cairo",
    "约翰内斯堡": "Africa/Johannesburg",
    "内罗毕": "Africa/Nairobi",
    "拉各斯": "Africa/Lagos",
}
