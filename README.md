# 南昌市基础教育资源空间可达性与供需匹配分析

## 1. 项目简介

本项目基于GIS与空间分析方法，对南昌市基础教育资源（小学、初中、高中）的空间配置进行研究。

研究技术路线为：

人口需求面（100 m人口格网）
→ 最近学校时间可达性分析
→ 高斯两步移动搜索法（Gaussian 2SFCA）供需匹配评价

项目用于支撑论文相关的数据处理、空间分析与结果生成。

---

## 2. 数据来源

* 人口数据：2024年100 m全国人口格网（裁剪至南昌市）
* 学校数据：基于高德地图API获取的教育设施POI
* 路网数据：OpenStreetMap / 本地道路数据

---

## 3. 项目结构

```
nanchang-edu-accessibility/
│
├── data_raw/                 # 原始数据
│   ├── schools_amap_raw.csv
│
├── data_processed/           # 处理后数据
│   ├── schools_clean.csv
│   ├── schools_classified.csv
│
├── poi_collection/           # POI获取与清洗
│   ├── get_poi.py
│   ├── classify_school.py
│
├── module_b_accessibility/   # 可达性分析
│
├── module_c_2sfca/           # 高斯2SFCA分析
│
├── results/                  # 输出结果
│   ├── maps/
│   ├── tables/
│
└── README.md
```

---

## 4. 功能说明

### 4.1 POI获取（高德API）

使用高德地图 Web 服务 API 获取南昌市学校POI数据：

* 支持关键词搜索（小学 / 初中 / 高中）
* 自动分页获取（避免数据遗漏）
* 输出CSV文件

运行方式：

```bash
python poi_collection/get_poi.py
```

---

### 4.2 学校分类

根据学校名称进行规则分类：

* 小学
* 初中
* 高中
* 九年一贯制 / 完全中学（标记）

运行方式：

```bash
python poi_collection/classify_school.py
```

---

### 4.3 可达性分析

基于路网构建时间成本面，计算：

* 到最近小学时间
* 到最近初中时间
* 到最近高中时间

---

### 4.4 高斯2SFCA供需匹配

* 供给端：学校点
* 需求端：人口格网
* 引入高斯距离衰减函数

输出教育资源供需匹配度空间分布。

---

## 5. 使用说明

1. 获取高德API Key
2. 在 `get_poi.py` 中填写 key
3. 运行脚本获取学校数据
4. 执行分类脚本
5. 进入后续分析模块

---

## 6. 注意事项

* 高德POI数据主要用于空间位置获取
* 学校分类基于名称规则，存在一定误差
* 未区分学位规模，仅用于空间分析

---

## 7. 作者说明

本项目为课程/毕业论文研究使用，仅用于学术分析。
