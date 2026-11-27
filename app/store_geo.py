"""按行政区划词典和本机映射推断门店与仓库的位置。"""
import re

PROVINCES = (
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "上海", "江苏", "浙江", "安徽",
    "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州",
    "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆", "台湾", "香港", "澳门",
)
MUNICIPALITIES = {"北京", "天津", "上海", "重庆"}
ALIASES = {"内蒙": "内蒙古"}

_CITIES = {
    "河北": "石家庄 唐山 秦皇岛 邯郸 邢台 保定 张家口 承德 沧州 廊坊 衡水 定州 辛集",
    "山西": "太原 大同 阳泉 长治 晋城 朔州 晋中 运城 忻州 临汾 吕梁",
    "内蒙古": "呼和浩特 包头 乌海 赤峰 通辽 鄂尔多斯 呼伦贝尔 巴彦淖尔 乌兰察布 兴安盟 锡林郭勒 阿拉善",
    "辽宁": "沈阳 大连 鞍山 抚顺 本溪 丹东 锦州 营口 阜新 辽阳 盘锦 铁岭 葫芦岛",
    "吉林": "长春 四平 辽源 通化 白山 松原 白城 延边",
    "黑龙江": "哈尔滨 齐齐哈尔 鸡西 鹤岗 双鸭山 大庆 伊春 佳木斯 七台河 牡丹江 黑河 绥化 大兴安岭",
    "江苏": "南京 无锡 徐州 常州 苏州 南通 连云港 淮安 盐城 扬州 镇江 泰州 宿迁",
    "浙江": "杭州 宁波 温州 嘉兴 湖州 绍兴 金华 衢州 舟山 台州 丽水",
    "安徽": "合肥 芜湖 蚌埠 淮南 马鞍山 淮北 铜陵 安庆 黄山 滁州 阜阳 宿州 六安 亳州 池州 宣城",
    "福建": "福州 厦门 莆田 三明 泉州 漳州 南平 龙岩 宁德",
    "江西": "南昌 景德镇 萍乡 九江 新余 鹰潭 赣州 吉安 宜春 抚州 上饶",
    "山东": "济南 青岛 淄博 枣庄 东营 烟台 潍坊 济宁 泰安 威海 日照 临沂 德州 聊城 滨州 菏泽",
    "河南": "郑州 开封 洛阳 平顶山 安阳 鹤壁 新乡 焦作 濮阳 许昌 漯河 三门峡 南阳 商丘 信阳 周口 驻马店 济源",
    "湖北": "武汉 黄石 十堰 宜昌 襄阳 鄂州 荆门 孝感 荆州 黄冈 咸宁 随州 恩施 仙桃 潜江 天门 神农架",
    "湖南": "长沙 株洲 湘潭 衡阳 邵阳 岳阳 常德 张家界 益阳 郴州 永州 怀化 娄底 湘西",
    "广东": "广州 韶关 深圳 珠海 汕头 佛山 江门 湛江 茂名 肇庆 惠州 梅州 汕尾 河源 阳江 清远 东莞 中山 潮州 揭阳 云浮",
    "广西": "南宁 柳州 桂林 梧州 北海 防城港 钦州 贵港 玉林 百色 贺州 河池 来宾 崇左",
    "海南": "海口 三亚 儋州 琼海 文昌 万宁 澄迈 临高 陵水",
    "四川": "成都 自贡 攀枝花 泸州 德阳 绵阳 广元 遂宁 内江 乐山 南充 眉山 宜宾 广安 达州 雅安 巴中 资阳 阿坝 甘孜 凉山 西昌",
    "贵州": "贵阳 六盘水 遵义 安顺 毕节 铜仁 黔西南 黔东南 黔南",
    "云南": "昆明 曲靖 玉溪 保山 昭通 丽江 普洱 临沧 楚雄 红河 文山 西双版纳 大理 德宏",
    "西藏": "拉萨 日喀则 昌都 林芝 山南 那曲",
    "陕西": "西安 铜川 宝鸡 咸阳 渭南 延安 汉中 榆林 安康 商洛",
    "甘肃": "兰州 嘉峪关 金昌 白银 天水 武威 张掖 平凉 酒泉 庆阳 定西 陇南 临夏",
    "青海": "西宁 海东",
    "宁夏": "银川 石嘴山 吴忠 固原 中卫",
    "新疆": "乌鲁木齐 克拉玛依 吐鲁番 哈密 昌吉 阿克苏 喀什 和田 伊犁 石河子",
}
# 只收录不会和别省重名、并且门店名常直接以它开头的县区
_COUNTIES = {
    "湖南": "浏阳 宁乡 长沙县 望城 醴陵 攸县 茶陵 炎陵 湘乡 韶山 湘潭县 衡东 衡南 衡山 祁东 耒阳 常宁 衡阳县 邵东 新邵 "
            "隆回 洞口 武冈 新宁 城步 绥宁 邵阳县 汨罗 平江 湘阴 华容 临湘 岳阳县 安乡 汉寿 澧县 临澧 桃源 石门 津市 "
            "慈利 桑植 南县 桃江 安化 沅江 桂阳 宜章 永兴 嘉禾 临武 汝城 桂东 安仁 资兴 祁阳 东安 双牌 道县 江永 宁远 "
            "蓝山 新田 江华 沅陵 辰溪 溆浦 中方 会同 麻阳 新晃 芷江 靖州 通道 洪江 双峰 新化 冷水江 涟源 吉首 泸溪 "
            "凤凰 花垣 保靖 永顺 龙山 冷水滩 零陵 鼎城 武陵 赫山 资阳区 雨花 岳麓 开福 天心 芙蓉 星沙 河西",
    "江西": "南昌县 进贤 安义 新建 浮梁 乐平 莲花 上栗 芦溪 瑞昌 共青城 武宁 修水 永修 德安 都昌 湖口 彭泽 分宜 "
            "贵溪 余江 南康 赣县 信丰 大余 上犹 崇义 安远 定南 全南 宁都 于都 兴国 会昌 寻乌 石城 瑞金 龙南 井冈山 "
            "吉水 峡江 新干 永丰 泰和 遂川 万安 安福 永新 丰城 樟树 高安 奉新 万载 上高 宜丰 靖安 铜鼓 南城 黎川 "
            "南丰 崇仁 乐安 宜黄 金溪 资溪 广昌 广丰 广信 玉山 铅山 横峰 弋阳 余干 鄱阳 万年 婺源 德兴 红谷滩 青山湖",
}

_CITY_TO_PROVINCE = {city: prov for prov, names in _CITIES.items() for city in names.split()}
_COUNTY_TO_PROVINCE = {county: prov for prov, names in _COUNTIES.items() for county in names.split()}
_PROVINCE_KEYS = sorted(PROVINCES, key=len, reverse=True)
_CITY_KEYS = sorted(_CITY_TO_PROVINCE, key=len, reverse=True)
_COUNTY_KEYS = sorted(_COUNTY_TO_PROVINCE, key=len, reverse=True)
_WAREHOUSE_LOCATIONS = {
    **_COUNTY_TO_PROVINCE,
    **_CITY_TO_PROVINCE,
    **{city: city for city in MUNICIPALITIES},
}
_WAREHOUSE_KEYS = sorted(_WAREHOUSE_LOCATIONS, key=lambda location: (-len(location), location))
_BRACKETS = re.compile(r"（.*?）|\(.*?\)")
_PROVINCE_SUFFIX = re.compile(r"^(省|市|壮族自治区|回族自治区|维吾尔自治区|自治区)")
_WAREHOUSE_SUFFIX = re.compile(r"(?:智慧仓|分仓|[一二三四五六七八九十]仓|仓)$")


def clean_store(name, brand_prefixes=None) -> str:
    """去掉门店名中的附注和本机配置的品牌前缀。"""
    text = _BRACKETS.sub("", str(name or "")).strip()
    prefix = max((prefix for prefix in (brand_prefixes or {}) if prefix and text.startswith(prefix)),
                 key=len, default="")
    return text[len(prefix):].lstrip()


def locate(name, brand_prefixes=None) -> tuple[str, str]:
    """返回 (省份, 城市)，认不出时省份为空字符串。"""
    text = clean_store(name, brand_prefixes)
    for alias, full in ALIASES.items():
        if text.startswith(alias) and not text.startswith(full):
            text = full + text[len(alias):]
    for province in _PROVINCE_KEYS:
        if text.startswith(province):
            if province in MUNICIPALITIES:
                return province, province
            rest = _PROVINCE_SUFFIX.sub("", text[len(province):])
            for city in _CITY_KEYS:
                if rest.startswith(city) and _CITY_TO_PROVINCE[city] == province:
                    return province, city
            return province, ""
    for city in _CITY_KEYS:
        if text.startswith(city):
            return _CITY_TO_PROVINCE[city], city
    for county in _COUNTY_KEYS:
        if text.startswith(county):
            return _COUNTY_TO_PROVINCE[county], ""
    return "", ""


def locate_warehouse(org, warehouse_org_locations=None) -> tuple[str, str]:
    """采购组织对应的仓库显示名和省份。优先使用本机组织映射。"""
    code, separator, label = str(org or "").strip().partition("_")
    override = (warehouse_org_locations or {}).get(code)
    if override is not None:
        return override
    name = (label if separator else code).strip()
    place = _WAREHOUSE_SUFFIX.sub("", _BRACKETS.sub("", name).strip())
    province, city = locate(place)
    candidates = [key for key in _WAREHOUSE_KEYS
                  if key in place and (not province or _WAREHOUSE_LOCATIONS[key] == province)]
    for key in candidates:
        if place.endswith(key):
            return key, _WAREHOUSE_LOCATIONS[key]
    if city:
        return city, province
    if candidates:
        location = candidates[0]
        return location, _WAREHOUSE_LOCATIONS[location]
    return name or "未识别", province


warehouse = locate_warehouse
