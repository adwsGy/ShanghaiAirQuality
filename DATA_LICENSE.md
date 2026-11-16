# 数据与地图来源

项目代码采用[MIT许可证](LICENSE)，第三方数据与地图遵循各自来源的使用条款。

## 适用文件

- `data/processed/`中的观测值、站点资料、来源记录及其清洗、聚合结果。
- `data/processed/geometry/shanghai.geojson`与`frontend/public/geometry/shanghai.geojson`中的行政边界。
- 界面截图中包含的地图、外部资料及其他第三方内容。

文件清单、校验值与处理方法见`data/processed/data_manifest.json`、`data/processed/source_file_audit.csv`及[数据说明](docs/data.md)。

## 来源与使用说明

| 材料 | 来源 | 使用说明 |
| --- | --- | --- |
| 全国城市和站点PM2.5小时归档、历史站点资料 | [中国空气质量历史数据（QuotSoft）](https://quotsoft.net/air/)，原始监测来源为中国环境监测总站发布平台 | 来源页面欢迎分析研究，未列明单独的再分发许可证。 |
| 2018年8月、12月的部分补充站点小时观测 | [OpenAQ](https://openaq.org/)公开历史归档，多数站点的提供者记录为ChinaAQIData | 按[OpenAQ使用条款](https://docs.openaq.org/about/terms#intellectual-property-and-attribution)署名OpenAQ及原提供者，并遵守提供者条款。部分历史记录的具体许可信息仍待确认。 |
| 上海行政边界 | 阿里云DataV GeoAtlas，[获取地址](https://geo.datav.aliyun.com/areas_v3/bound/310000_full.json)，上游为高德开放平台 | [阿里云官方说明](https://help.aliyun.com/zh/datav/datav-7-0/user-guide/datav-geoatlas-widgets/)列明用途为学习交流；其他使用方式请查阅原平台条款。 |

## 使用与署名

使用观测结果时，请注明中国空气质量历史数据归档及原监测来源；使用补充观测时注明OpenAQ及可识别的原提供者。展示地图时保留DataV GeoAtlas及其上游来源说明。

再分发数据或地图时，请确认来源允许相应使用方式，并保留其要求的署名和许可信息。
