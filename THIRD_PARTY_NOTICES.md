# 第三方软件与资料说明

项目代码采用[MIT许可证](LICENSE)，第三方依赖保留各自的版权和许可证。下表列出直接依赖与主要开发工具。

## 前端

| 软件 | 许可证 | 上游 |
| --- | --- | --- |
| React、React DOM | MIT | [React](https://react.dev/) |
| Apache ECharts | Apache-2.0 | [Apache ECharts](https://echarts.apache.org/) |
| Motion | MIT | [Motion](https://motion.dev/) |
| TypeScript | Apache-2.0 | [TypeScript](https://www.typescriptlang.org/) |
| Vite、@vitejs/plugin-react | MIT | [Vite](https://vite.dev/) |
| @types/node、@types/react、@types/react-dom | MIT | [DefinitelyTyped](https://definitelytyped.org/) |

Apache ECharts的已安装版本附带以下NOTICE：

```text
Apache ECharts
Copyright 2017-2026 The Apache Software Foundation

This product includes software developed at
The Apache Software Foundation (https://www.apache.org/).
```

## 后端与数据处理

| 软件 | 许可证 | 上游 |
| --- | --- | --- |
| pandas | BSD-3-Clause | [pandas](https://pandas.pydata.org/) |
| NumPy | BSD-3-Clause | [NumPy](https://numpy.org/) |
| jsonschema | MIT | [jsonschema](https://python-jsonschema.readthedocs.io/) |
| FastAPI | MIT | [FastAPI](https://fastapi.tiangolo.com/) |
| Uvicorn | BSD-3-Clause | [Uvicorn](https://uvicorn.dev/) |
| HTTPX | BSD-3-Clause | [HTTPX](https://www.python-httpx.org/) |
| LangGraph、langgraph-checkpoint-sqlite | MIT | [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview) |

完整依赖版本见`frontend/package-lock.json`与`requirements-lock.txt`。传递依赖及二进制包附带的组件使用各自的许可证，具体条款见安装包内的LICENSE、COPYING、NOTICE及许可证目录。

本仓库不跟踪`node_modules`、Python虚拟环境或构建产物。需要再分发这些依赖时，应保留相应组件要求的完整许可证与NOTICE；本表只作索引。

## 数据、地图与截图

第三方观测数据、地理边界和截图中的外部内容，其来源与使用说明见[DATA_LICENSE.md](DATA_LICENSE.md)。
