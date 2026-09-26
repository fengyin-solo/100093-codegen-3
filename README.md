# 实验室样品检测管理平台

面向第三方检测实验室样品接收、任务分配、检测分析、结果复核、报告签发与标物管理的检测业务管理后台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 样品登记 | `sample` | 检测样品 | 样品编号、样品名称、委托单位 |
| 委托合同 | `contract` | 委托合同 | 合同编号、委托单位、检测项目 |
| 检测任务 | `task` | 检测任务 | 任务编号、关联样品、检测项目 |
| 检测方法 | `method` | 检测方法 | 方法编号、方法名称、标准编号 |
| 仪器设备 | `instrument` | 仪器 | 仪器编号、仪器名称、规格型号 |
| 标准物质 | `standard` | 标准物质 | 标物编号、标物名称、证书编号 |
| 检测结果 | `result` | 检测结果 | 结果编号、关联任务、检测项目 |
| 检测报告 | `report` | 检测报告 | 报告编号、关联任务、编制人 |
| 分包检测 | `boundary` | 分包记录 | 分包编号、分包原因、分包方名称 |
| 不符合项 | `abnormal` | 不符合项 | 不符合编号、发现环节、不符合描述 |
| 环境监控 | `envmonitor` | 环境记录 | 记录编号、监测区域、温度值 |
| 盲样考核 | `blind` | 盲样 | 盲样编号、考核人员、检测项目 |
| 能力验证 | `ability` | 能力验证 | 验证编号、组织方、检测项目 |
| 中间液配制 | `intermediate` | 中间液 | 配制编号、母液编号、目标浓度 |
| 内审检查 | `audit` | 内审记录 | 内审编号、内审日期、内审部门 |
| 认证认可 | `certification` | 资质认定 | 认定编号、认定类型、发证机构 |
| 质控样 | `quality` | 质控样 | 质控样编号、参数名称、标准值 |
| 试剂管理 | `reagent2` | 试剂 | 试剂编号、试剂名称、规格等级 |
| 实验废液 | `waste` | 废液记录 | 废液编号、废液类别、产生环节 |
| 客户反馈 | `opinion` | 反馈记录 | 反馈编号、委托单位、反馈类型 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 仪器设备检定判定口径

- 下次检定日距今天不足临期阈值的仪器自动标为「待检定」；阈值按保管人所在实验室
  区分（理化 30 天、色谱 45 天、微生物 15 天，未配置的实验室默认 30 天）。
- 检定日期晚于下次检定日的数据不允许保存，接口会说明原因；超过检定有效期仍要
  保持「正常」使用状态的仪器一律拦下。
- 「维修中」「已停用」的仪器不参与到期判定。
- 检定记录按仪器编号归集（`instrument_calibration` 台账），同一编号出现多条时以
  检定日期最近的一条为准；办理检定会追加一条检定记录。
- 服务启动时会把既有仪器按新口径重标一遍，之后每次读取也按当天口径刷新，并可
  通过 `POST /api/instrument/refresh` 或页面「按新口径重标」按钮手动重标；
  列表与详情共用同一套判定函数，检定结论始终一致。
