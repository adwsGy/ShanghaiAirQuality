# 数据与统计

仓库提供当前应用使用的全部35个数据文件，合计约17MB。`data/processed/data_manifest.json`记录数据版本和逐文件SHA-256，`build_status.json`标记完整构建。运行接口只读取本项目的数据文件。

城市日表有4018个日历日期，其中4016天有观测；站点日表有40792个站点日期，其中34493个有观测。小时记录在`hourly/`按城市、站点和年份分区；2018年历史站点观测已进入同一主表及小时分区。站点目录、地理边界和来源审计一并提供。

## 来源与口径

原始空气质量归档来自[中国空气质量历史数据](https://quotsoft.net/air/)，该站说明全国记录来自中国环境监测总站发布平台。2018年部分站点小时使用经核对的OpenAQ观测补齐。城市缺失小时仅在同小时九个评价站观测齐全时重算，保留原城市值优先。站点和城市始终分开计算，缺测不补零、不插值。

日均由已有有效小时求平均，月、年及所选时段对已有日均等权计算。真实零值保留，负数、非数值、非有限值与冲突重复观测不参与统计。P90采用线性插值计算；它表示日均的较高分位，不等于高值日期数量。站点坐标基准未核实，地图用于位置参照。

本数据集沿用迁出时的数据版本`sh-pm25-1318ae447557e3f0`，上游代码基线为`d493acf`。清单中的`inputs`、`code`及历史来源字段记录上游生成过程，其中相对路径是来源标签，不是当前运行依赖。它们不要求原项目、原始全国ZIP、旧数据快照或实验记录存在。新项目的重建过程另记录在输出清单的`rebuild`中。

## 校验与重建

```powershell
.\.venv\Scripts\python.exe -m pipeline.verify
.\.venv\Scripts\python.exe -m pipeline.rebuild --output data/rebuilt
```

Linux/macOS使用以下命令，Git Bash也可沿用Windows虚拟环境的Python路径：

```bash
./.venv/bin/python -m pipeline.verify
./.venv/bin/python -m pipeline.rebuild --output data/rebuilt
```

校验逐一核对清单所列文件的长度与SHA-256。重建从已提供的标准小时分区重算日均、月度、年度和站点对比，沿用日表的观测日历及来源字段，生成新的版本与清单，不下载数据、不请求模型。目标必须为不同的空目录；再次重建请指定新的输出目录。若要运行重建结果，可设置环境变量`SHANGHAI_DATA_DIR`为该目录。

## 清洗其他原始文件

```powershell
.\.venv\Scripts\python.exe -m pipeline.clean data/raw/china_cities_20230101.csv --source city --objects 上海=shanghai --output data/imported/city.csv.gz
```

Linux/macOS将解释器替换为`./.venv/bin/python`，其余参数相同。

输入可为单日CSV或包含多个单日CSV的ZIP，文件名须以八位日期加`.csv`结尾。站点使用`--source site --objects 1141A=1141A 1142A=1142A`。只提取`PM2.5`一小时记录，忽略`PM2.5_24h`；相同重复值合并，冲突重复值隔离，非法日期、小时、数值及HTML响应记录在审计文件中。输出为标准小时表和对应的`.audit.json`，不会覆盖原文件。

新增数据应先核查单位、时区、对象身份与重叠值，再更新标准小时分区及日历。清洗命令不自动将新来源覆盖到当前数据集中。
