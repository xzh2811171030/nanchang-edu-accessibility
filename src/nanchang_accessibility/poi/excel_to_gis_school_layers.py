
"""
将学校 POI Excel 转为可直接导入 GIS 的空间数据。

功能：
1. 读取 Excel；
2. 筛选“最终学校分类”为“小学”“初中”的记录；
3. 将高德 GCJ-02 经纬度近似转换为 WGS84；
4. 再投影到 CGCS2000_3_Degree_GK_Zone_39（EPSG:4527）；
5. 分别导出小学、初中两个 GIS 数据文件。

默认输出：
- GPKG（推荐，字段名不易丢失，ArcGIS/QGIS 都能直接打开）
- Shapefile（兼容性强，但字段名长度和编码更受限制）

安装：
    pip install pandas openpyxl geopandas pyogrio shapely pyproj

说明：
- 你的 Excel 经纬度如果来自高德 POI，一般属于 GCJ-02。
- GIS 分析时若要使用 CGCS2000 投影坐标，不能把 GCJ-02 直接当作 WGS84/CGCS2000 投影，
  否则会出现系统偏差。因此本脚本先做 GCJ-02 -> WGS84 近似反算，再投影到 EPSG:4527。
- EPSG:4527 对应 CGCS2000 / 3-degree Gauss-Kruger zone 39，适用于 115.5°E 到 118.5°E。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Tuple

import pandas as pd
import geopandas as gpd
from shapely.geometry import Point


# =========================
# 1. 参数配置
# =========================
INPUT_EXCEL = r"南昌市学校POI_分类整理版.xlsx"  # 改成你的 Excel 路径
SHEET_NAME = 0  # 第一个 sheet；如果有固定名字也可改成字符串
OUTPUT_DIR = r"gis_output"

# 目标分类
TARGET_CATEGORIES = ["小学", "初中"]

# 列名配置（根据你当前文件实际字段名编写）
COL_CLASS = "最终学校分类"
COL_NAME = "学校名称"
COL_LON = "经度"
COL_LAT = "纬度"

# GIS 坐标系
CRS_WGS84 = "EPSG:4326"
CRS_TARGET = "EPSG:4527"  # CGCS2000_3_Degree_GK_Zone_39


# =========================
# 2. GCJ-02 -> WGS84 转换函数
# =========================
PI = math.pi
A = 6378245.0
EE = 0.00669342162296594323


def out_of_china(lon: float, lat: float) -> bool:
    """判断点是否在中国范围外。"""
    return not (73.66 < lon < 135.05 and 3.86 < lat < 53.55)



def _transform_lat(x: float, y: float) -> float:
    ret = (
        -100.0
        + 2.0 * x
        + 3.0 * y
        + 0.2 * y * y
        + 0.1 * x * y
        + 0.2 * math.sqrt(abs(x))
    )
    ret += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * PI) + 40.0 * math.sin(y / 3.0 * PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * PI) + 320 * math.sin(y * PI / 30.0)) * 2.0 / 3.0
    return ret



def _transform_lon(x: float, y: float) -> float:
    ret = (
        300.0
        + x
        + 2.0 * y
        + 0.1 * x * x
        + 0.1 * x * y
        + 0.1 * math.sqrt(abs(x))
    )
    ret += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * PI) + 40.0 * math.sin(x / 3.0 * PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * PI) + 300.0 * math.sin(x / 30.0 * PI)) * 2.0 / 3.0
    return ret



def gcj02_to_wgs84(lon: float, lat: float) -> Tuple[float, float]:
    """
    将 GCJ-02 经纬度近似转换为 WGS84 经纬度。
    对学校 POI 制图、可达性分析通常够用。
    """
    if out_of_china(lon, lat):
        return lon, lat

    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)
    radlat = lat / 180.0 * PI
    magic = math.sin(radlat)
    magic = 1 - EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((A * (1 - EE)) / (magic * sqrtmagic) * PI)
    dlon = (dlon * 180.0) / (A / sqrtmagic * math.cos(radlat) * PI)
    mglat = lat + dlat
    mglon = lon + dlon
    return lon * 2 - mglon, lat * 2 - mglat


# =========================
# 3. 数据读取与清洗
# =========================
def read_excel_data(excel_path: str, sheet_name=0) -> pd.DataFrame:
    """读取 Excel 并检查必要字段。"""
    df = pd.read_excel(excel_path, sheet_name=sheet_name)

    required_cols = [COL_CLASS, COL_NAME, COL_LON, COL_LAT]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Excel 缺少必要字段: {missing}")

    # 经纬度转数值，无法转换的置空
    df[COL_LON] = pd.to_numeric(df[COL_LON], errors="coerce")
    df[COL_LAT] = pd.to_numeric(df[COL_LAT], errors="coerce")

    # 仅保留目标分类 + 有效坐标
    df = df[df[COL_CLASS].isin(TARGET_CATEGORIES)].copy()
    df = df.dropna(subset=[COL_LON, COL_LAT]).copy()

    # 去掉明显异常坐标
    df = df[(df[COL_LON].between(70, 140)) & (df[COL_LAT].between(0, 60))].copy()

    if df.empty:
        raise ValueError("筛选后无有效记录，请检查分类字段或经纬度字段。")

    return df


# =========================
# 4. 坐标转换与建空间数据
# =========================
def build_geodataframe(df: pd.DataFrame) -> gpd.GeoDataFrame:
    """
    先将高德 GCJ-02 经纬度转近似 WGS84，
    再构建 GeoDataFrame。
    """
    converted = df.apply(lambda row: gcj02_to_wgs84(row[COL_LON], row[COL_LAT]), axis=1)
    df[["wgs84_lon", "wgs84_lat"]] = pd.DataFrame(converted.tolist(), index=df.index)

    geometry = [Point(xy) for xy in zip(df["wgs84_lon"], df["wgs84_lat"])]
    gdf = gpd.GeoDataFrame(df.copy(), geometry=geometry, crs=CRS_WGS84)
    return gdf


# =========================
# 5. 导出 GIS 数据
# =========================
def export_category_layers(gdf_wgs84: gpd.GeoDataFrame, output_dir: str) -> None:
    """
    分别导出小学、初中两类图层。
    每类输出：
    - 一个 GPKG（推荐）
    - 一个 WGS84 GeoJSON（方便快速检查）
    - 一个投影后的 GPKG（EPSG:4527）
    - 一个投影后的 Shapefile（兼容老 GIS 软件）
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for cat in TARGET_CATEGORIES:
        sub = gdf_wgs84[gdf_wgs84[COL_CLASS] == cat].copy()
        if sub.empty:
            print(f"[提示] 分类 {cat} 无数据，跳过。")
            continue

        # 投影到 CGCS2000_3_Degree_GK_Zone_39
        sub_proj = sub.to_crs(CRS_TARGET)

        # 文件名
        safe_name = "primary_school" if cat == "小学" else "junior_school"

        # 1) WGS84 GeoJSON
        geojson_file = out_dir / f"{safe_name}_wgs84.geojson"
        sub.to_file(geojson_file, driver="GeoJSON")

        # 2) WGS84 GPKG
        gpkg_wgs84 = out_dir / f"{safe_name}_wgs84.gpkg"
        sub.to_file(gpkg_wgs84, layer=safe_name, driver="GPKG")

        # 3) 投影后 GPKG（推荐给 GIS 分析）
        gpkg_proj = out_dir / f"{safe_name}_cgcs2000_gk39.gpkg"
        sub_proj.to_file(gpkg_proj, layer=safe_name, driver="GPKG")

        # 4) 投影后 Shapefile（兼容）
        # shapefile 字段名限制较多，因此另做一份英文简化字段版本
        shp_df = sub_proj.copy()
        rename_map = {
            "学校名称": "name",
            "最终学校分类": "class",
            "来源目标分类": "src_class",
            "POI类型": "poi_type",
            "省份": "prov",
            "城市": "city",
            "区县": "district",
            "详细地址": "address",
            "经度": "amap_lon",
            "纬度": "amap_lat",
            "POI唯一编码": "poi_id",
            "检索模式": "search_md",
            "检索值": "search_val",
            "标准化名称": "name_std",
            "标准化地址": "addr_std",
            "wgs84_lon": "wgs_lon",
            "wgs84_lat": "wgs_lat",
        }
        existing_rename = {k: v for k, v in rename_map.items() if k in shp_df.columns}
        shp_df = shp_df.rename(columns=existing_rename)

        shp_folder = out_dir / f"{safe_name}_cgcs2000_gk39_shp"
        shp_folder.mkdir(exist_ok=True)
        shp_file = shp_folder / f"{safe_name}.shp"
        shp_df.to_file(shp_file, driver="ESRI Shapefile", encoding="utf-8")

        print(f"[完成] {cat}")
        print(f"  GeoJSON: {geojson_file}")
        print(f"  WGS84 GPKG: {gpkg_wgs84}")
        print(f"  投影 GPKG: {gpkg_proj}")
        print(f"  投影 SHP: {shp_file}")
        print(f"  数量: {len(sub)} 条")


# =========================
# 6. 主程序
# =========================
def main() -> None:
    print("开始读取 Excel...")
    df = read_excel_data(INPUT_EXCEL, SHEET_NAME)
    print(f"读取成功，共 {len(df)} 条目标记录。")
    print(df[COL_CLASS].value_counts())

    print("开始构建空间数据并做坐标转换...")
    gdf = build_geodataframe(df)

    print("开始导出 GIS 文件...")
    export_category_layers(gdf, OUTPUT_DIR)
    print("全部完成。")


if __name__ == "__main__":
    main()
