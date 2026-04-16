"""
高德地图 POI 学校采集脚本（小学 / 初中 / 高中）

目标：
1. 尽量提高小初高学校 POI 的召回率；
2. 输出结果便于后续分类、清洗和空间分析；
3. 模块化、注释充分，便于论文答辩时解释；
4. 同时支持“类型编码抓取”和“关键词补充抓取”两种策略，减少漏采。

使用说明：
- 将 AMAP_KEY 替换为你自己的 Web 服务 API Key；
- 直接运行：python amap_school_poi_collector.py
- 默认会导出两个 Excel：
  1) 原始去重结果：南昌市学校POI_原始去重版.xlsx
  2) 分类整理结果：南昌市学校POI_分类整理版.xlsx

说明：
- 高德 place/text 单页最大返回 20 条；
- 同类 POI 可能因为平台数据质量存在重复、别名、缺失分类等情况；
- “抓全”无法做到绝对完整，但可通过“多轮查询 + 结果合并去重 + 名称规则分类”显著提升完整度。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests


# =========================
# 一、基础配置区
# =========================
AMAP_KEY = "3b8cce67eaff6f791b334689b610fd07"
CITY_NAME = "南昌市"
CITY_LIMIT = True
OUTPUT_PREFIX = CITY_NAME

# 请求参数
OFFSET = 20                 # 高德 text 检索单页最大 20 条
TIMEOUT = 10               # 接口超时秒数
REQUEST_INTERVAL = 0.5     # 请求间隔，建议免费 key 不低于 0.5 秒
MAX_EMPTY_ROUNDS = 1       # 连续空页轮次阈值，通常 1 即可

# 高德教育类常见 POI 编码（你原始代码里的编码保留使用）
# 小学 141201、初中 141202、高中 141203
TYPE_CODE_MAP = {
    "小学": "141201",
    "初中": "141202",
    "高中": "141203",
}

# 为了尽量抓全，除 types 外，再增加若干关键词查询
# 原因：部分学校 POI 分类可能标注不标准，单纯依赖 types 会漏掉。
KEYWORDS_BY_CATEGORY = {
    "小学": ["小学", "中心小学", "实验小学", "完全小学"],
    "初中": ["初中", "中学初中部", "九年一贯制学校"],
    "高中": ["高中", "高级中学", "完全中学", "中学高中部"],
}

# 若学校名称中出现以下关键词，可辅助判定分类
NAME_RULES = {
    "小学": [r"小学", r"完全小学", r"中心小学", r"实验小学"],
    "初中": [r"初级中学", r"初中", r"九年一贯制"],
    "高中": [r"高级中学", r"高中", r"完全中学"],
}

# 某些名称包含“中学”但不明确是初中还是高中，先标为“中学（待细分）”
AMBIGUOUS_MIDDLE_SCHOOL_PATTERNS = [r"中学"]


# =========================
# 二、数据模型
# =========================
@dataclass
class AmapSearchTask:
    """描述一次检索任务：按类型编码或按关键词检索。"""

    task_mode: str           # 'type' 或 'keyword'
    target_category: str     # 小学 / 初中 / 高中
    value: str               # type code 或 keyword


# =========================
# 三、底层工具函数
# =========================
def safe_request(url: str, params: Dict, timeout: int = TIMEOUT) -> Optional[Dict]:
    """
    发送 GET 请求，返回 JSON。

    返回 None 表示请求失败或 JSON 解析失败。
    """
    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        print(f"[请求异常] {exc}")
        return None


def split_location(location: str) -> Tuple[str, str]:
    """拆分高德 location 字段，返回 (lon, lat)。"""
    if not location or "," not in location:
        return "", ""
    lon, lat = location.split(",", 1)
    return lon, lat


def normalize_text(text: str) -> str:
    """
    对名称/地址做轻度标准化，便于后续去重。
    这里只做保守清洗，避免误删真实信息。
    """
    text = str(text or "").strip()
    text = re.sub(r"\s+", "", text)
    text = text.replace("（", "(").replace("）", ")")
    return text


# =========================
# 四、POI 解析与分类函数
# =========================
def classify_school(name: str, poi_type: str, source_category: str = "") -> str:
    """
    对学校进行分类。

    分类优先级：
    1. 高德 type 字段文本中若明确出现小学/初中/高中，直接使用；
    2. 名称规则匹配；
    3. 回退到检索来源分类（source_category）；
    4. 仍无法判断时标记为“中学（待细分）”或“未识别”。
    """
    name_std = normalize_text(name)
    poi_type_std = normalize_text(poi_type)

    # 1) 优先看 type 文本
    if "小学" in poi_type_std:
        return "小学"
    if "初中" in poi_type_std or "初级中学" in poi_type_std:
        return "初中"
    if "高中" in poi_type_std or "高级中学" in poi_type_std:
        return "高中"

    # 2) 再看名称规则
    for category, patterns in NAME_RULES.items():
        for pattern in patterns:
            if re.search(pattern, name_std):
                return category

    # 3) 含“中学”但未细分
    for pattern in AMBIGUOUS_MIDDLE_SCHOOL_PATTERNS:
        if re.search(pattern, name_std):
            if source_category in {"初中", "高中"}:
                return source_category
            return "中学（待细分）"

    # 4) 回退到来源分类
    if source_category in {"小学", "初中", "高中"}:
        return source_category

    return "未识别"


def build_record(poi: Dict, task: AmapSearchTask) -> Dict:
    """将单条高德 POI 转为结构化记录。"""
    lon, lat = split_location(poi.get("location", ""))
    school_name = poi.get("name", "")
    poi_type = poi.get("type", "")

    record = {
        "学校名称": school_name,
        "标准化名称": normalize_text(school_name),
        "省份": poi.get("pname", ""),
        "城市": poi.get("cityname", ""),
        "区县": poi.get("adname", ""),
        "详细地址": poi.get("address", ""),
        "标准化地址": normalize_text(poi.get("address", "")),
        "经度": lon,
        "纬度": lat,
        "POI类型": poi_type,
        "POI唯一编码": poi.get("id", ""),
        "检索模式": task.task_mode,
        "检索值": task.value,
        "来源目标分类": task.target_category,
    }
    record["最终学校分类"] = classify_school(
        name=record["学校名称"],
        poi_type=record["POI类型"],
        source_category=record["来源目标分类"],
    )
    return record


# =========================
# 五、检索任务构建
# =========================
def build_search_tasks() -> List[AmapSearchTask]:
    """
    构建所有检索任务。

    策略：
    1. 每个类别先跑一次 type 编码检索；
    2. 再补充多个关键词检索；
    3. 最后合并去重。
    """
    tasks: List[AmapSearchTask] = []

    for category, type_code in TYPE_CODE_MAP.items():
        tasks.append(AmapSearchTask(task_mode="type", target_category=category, value=type_code))

    for category, keywords in KEYWORDS_BY_CATEGORY.items():
        for kw in keywords:
            tasks.append(AmapSearchTask(task_mode="keyword", target_category=category, value=kw))

    return tasks


# =========================
# 六、单任务分页抓取
# =========================
def fetch_poi_by_task(task: AmapSearchTask) -> List[Dict]:
    """
    执行单个检索任务，并分页抓取结果。

    使用 text 搜索接口：
    - task_mode='type'：keywords 为空，types 指定类型编码；
    - task_mode='keyword'：使用关键词检索，同时仍限制城市范围。
    """
    url = "https://restapi.amap.com/v3/place/text"
    all_records: List[Dict] = []
    page_num = 1
    empty_rounds = 0

    print(f"\n[开始任务] 模式={task.task_mode} | 目标分类={task.target_category} | 检索值={task.value}")

    while True:
        params = {
            "key": AMAP_KEY,
            "city": CITY_NAME,
            "citylimit": str(CITY_LIMIT).lower(),
            "output": "json",
            "offset": OFFSET,
            "page": page_num,
            "extensions": "base",
        }

        if task.task_mode == "type":
            params["keywords"] = ""
            params["types"] = task.value
        else:
            params["keywords"] = task.value
            params["types"] = ""

        result = safe_request(url, params=params, timeout=TIMEOUT)
        if result is None:
            print("[任务中断] 请求失败，结束当前任务")
            break

        status = result.get("status")
        info = result.get("info", "")
        pois = result.get("pois", [])

        if status != "1":
            print(f"[接口报错] status={status}, info={info}")
            break

        if not pois:
            empty_rounds += 1
            print(f"[空页] page={page_num}，连续空页={empty_rounds}")
            if empty_rounds >= MAX_EMPTY_ROUNDS:
                break
        else:
            empty_rounds = 0
            for poi in pois:
                all_records.append(build_record(poi, task))
            print(f"[进度] page={page_num}，当前任务累计={len(all_records)} 条")

        page_num += 1
        time.sleep(REQUEST_INTERVAL)

    return all_records


# =========================
# 七、多任务合并与去重
# =========================
def deduplicate_records(records: List[Dict]) -> pd.DataFrame:
    """
    多轮检索后的去重。

    去重优先级：
    1. 先按 POI唯一编码 去重（最可靠）；
    2. 再对缺 id 的记录，按 标准化名称 + 区县 + 经度 + 纬度 去重。
    """
    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)

    # 先保留有唯一编码的数据
    has_id = df["POI唯一编码"].astype(str).str.strip() != ""
    df_with_id = df[has_id].copy()
    df_without_id = df[~has_id].copy()

    if not df_with_id.empty:
        df_with_id = df_with_id.drop_duplicates(subset=["POI唯一编码"], keep="first")

    if not df_without_id.empty:
        df_without_id = df_without_id.drop_duplicates(
            subset=["标准化名称", "区县", "经度", "纬度"],
            keep="first",
        )

    df_final = pd.concat([df_with_id, df_without_id], ignore_index=True)

    # 再做一次保守去重，防止同一学校被多轮任务重复写入
    df_final = df_final.drop_duplicates(
        subset=["标准化名称", "区县", "经度", "纬度", "最终学校分类"],
        keep="first",
    ).reset_index(drop=True)

    return df_final


# =========================
# 八、分类整理与导出
# =========================
def sort_and_reorder_columns(df: pd.DataFrame) -> pd.DataFrame:
    """整理字段顺序，便于论文数据核查与后续 GIS 使用。"""
    if df.empty:
        return df

    ordered_cols = [
        "学校名称",
        "最终学校分类",
        "来源目标分类",
        "POI类型",
        "省份",
        "城市",
        "区县",
        "详细地址",
        "经度",
        "纬度",
        "POI唯一编码",
        "检索模式",
        "检索值",
        "标准化名称",
        "标准化地址",
    ]

    existing_cols = [col for col in ordered_cols if col in df.columns]
    return df[existing_cols].sort_values(
        by=["最终学校分类", "区县", "学校名称"],
        ascending=[True, True, True],
    ).reset_index(drop=True)



def export_results(df: pd.DataFrame, output_prefix: str = OUTPUT_PREFIX) -> None:
    """导出 Excel 文件。"""
    if df.empty:
        print("[提示] 无可导出数据")
        return

    raw_output = f"{output_prefix}学校POI_原始去重版.xlsx"
    final_output = f"{output_prefix}学校POI_分类整理版.xlsx"

    df.to_excel(raw_output, index=False)
    sort_and_reorder_columns(df).to_excel(final_output, index=False)

    print(f"\n[导出完成] {raw_output}")
    print(f"[导出完成] {final_output}")
    print("[分类统计]")
    print(df["最终学校分类"].value_counts(dropna=False))


# =========================
# 九、主流程控制
# =========================
def collect_school_poi() -> pd.DataFrame:
    """
    主控函数：
    1. 构建任务；
    2. 逐任务抓取；
    3. 合并去重；
    4. 返回结果 DataFrame。
    """
    tasks = build_search_tasks()
    all_records: List[Dict] = []

    print("=" * 70)
    print(f"开始采集：{CITY_NAME} 小学 / 初中 / 高中学校 POI")
    print(f"任务总数：{len(tasks)}")
    print("=" * 70)

    for idx, task in enumerate(tasks, start=1):
        print(f"\n>>> 执行任务 {idx}/{len(tasks)}")
        task_records = fetch_poi_by_task(task)
        all_records.extend(task_records)
        print(f"[任务完成] 本任务获取 {len(task_records)} 条；总累计原始记录 {len(all_records)} 条")

    df = deduplicate_records(all_records)
    print("\n" + "=" * 70)
    print(f"全部任务结束，去重后共 {len(df)} 条")
    print("=" * 70)
    return df


# =========================
# 十、附加说明：如何进一步细分“中学”
# =========================
def classify_method_notes() -> str:
    """
    返回分类方法说明，便于你写到论文方法部分或答辩 PPT。
    """
    return (
        "学校分类采用‘三层判定法’：\n"
        "1. 优先依据高德返回的 POI类型 字段识别小学/初中/高中；\n"
        "2. 若 POI类型 不明确，则根据学校名称中的规则词判断，"
        "如‘小学’‘初级中学’‘高级中学’等；\n"
        "3. 若仍不明确，则回退到检索来源分类（如通过‘小学’关键词检索得到的结果优先归为小学）；\n"
        "4. 对仅出现‘中学’且无法明确初中/高中的记录，暂标记为‘中学（待细分）’，"
        "建议后续通过学校官网、教育局名录或人工核验继续细分。"
    )


# =========================
# 程序入口
# =========================
if __name__ == "__main__":
    if "替换为你自己申请的高德API_KEY" in AMAP_KEY:
        print("[警告] 请先将 AMAP_KEY 替换为你自己的高德 Web 服务 Key 再运行。")

    df_result = collect_school_poi()

    if df_result.empty:
        print("[结果] 未获取到有效数据，请检查 API Key、城市名、网络状态或查询参数。")
    else:
        export_results(df_result)
        print("\n[分类方法说明]")
        print(classify_method_notes())

