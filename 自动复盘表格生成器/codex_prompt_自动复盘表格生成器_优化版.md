# Codex 开发任务：自动复盘表格生成器

## 目标

在“复盘”项目下实现一个可本地运行的 Streamlit 工具。用户粘贴复盘文章，程序调用 Kimi Code API 提取结构化数据，预览后下载单工作表的 `.xlsx`。

## 技术与边界

- Python 3.10+；Streamlit、OpenAI Python SDK、openpyxl、python-dotenv、pandas。
- 不使用数据库，不自动抓取网页，不把 API Key 写入源码、日志或 Excel。
- 网络请求必须设置 60 秒默认超时；Base URL、模型、超时均可通过环境变量覆盖。密钥仅从 `KIMI_API_KEY` 或页面密码框读取。
- 不使用 500–800 行单文件。入口 `app.py` 只负责启动；预处理、Kimi Code 客户端、校验、Excel、UI 分模块实现，单文件职责明确。
- 注释使用中文，错误处理实用，不做无必要的类层级或抽象。

## 目录结构

```text
自动复盘表格生成器/
├─ app.py
├─ review_app/
│  ├─ config.py
│  ├─ preprocessing.py
│  ├─ llm.py
│  ├─ validation.py
│  ├─ excel.py
│  └─ ui.py
├─ tests/test_core.py
├─ output/
├─ requirements.txt
├─ .env.example
├─ .gitignore
└─ README.md
```

## 功能要求

1. 页面采用 40%/60% 左右分栏。左侧为 400px 原文输入、密码型 API Key 输入和主按钮；右侧用 7 个 tab 预览结果并提供下载。
2. 预处理去除零宽字符、常见“下载 APP”广告行、行首多余空格，将连续 3 个以上换行压缩为 2 个。空文本和超长文本直接提示。
3. Kimi Code 使用 OpenAI 兼容协议：`OpenAI(api_key=..., base_url=..., timeout=60)` 和 `chat.completions.create`；默认模型 `kimi-for-coding`，按接口限制使用温度 1，使用 JSON Object 输出，并兼容 Markdown JSON 围栏及正文夹带 JSON 的情况。
4. JSON 数据包含 `meta`、`first_boards`、`ladders`、`sentiment`、`observation_plan`、`bidding_analysis`、`temperament_stocks`、`thinking_questions`。提示模型只提取原文，不编造、不合并板块、不遗漏股票名；不确定日期留空。
5. 校验层补齐缺失字段；数组或对象类型不正确时降级为空值；情绪分数限制在 0–10；日期缺失时使用本机当天日期。
6. Excel 只生成一个“复盘汇总”工作表，将首板复盘、连板梯队、高标情绪、观察计划、竞价分析、气质股、思考题七个区块纵向排列。日期只显示在顶部一行，不作为重复列；首板个股每四只一行且每只独占一个单元格；连板梯队每只个股独占一行，并分列显示个股名称和晋级分析。使用清晰区块标题、微软雅黑 10pt、适当边框、自动换行、合理列宽和行高。
7. 首板按科技/医药/有色/其他设置板块色；连板按板数倒序，4 板及以上红色强调，2 板灰色；情绪分数 ≥7 绿色、≤3 红色、中间黄色。
8. 文件名为 `复盘_{作者}_{日期}.xlsx`，清理 Windows 非法文件名字符。浏览器下载为主；不得因本地目录权限导致页面崩溃。

## 错误处理

- Key 为空：提示填写 Key 或设置 `KIMI_API_KEY`。
- API 超时、连接失败、HTTP 状态错误分别给出可执行提示；不得展示 Key。
- 非 JSON、空响应、顶层非对象给出明确解析错误。
- Excel 生成异常由 UI 捕获并显示；未知异常可展示堆栈便于本地排查。

## 验收标准

- `python -m streamlit run app.py` 能启动，健康检查返回正常。
- 无 Key、空文本场景不会发起请求且提示明确。
- 单元测试覆盖预处理、默认字段、单工作表、首板每行四只、连板每股一行、关键单元格和安全文件名。
- 使用模拟数据可以生成并重新打开 Excel，无损坏警告。
- `.env.example`、依赖清单和 README 运行步骤完整；仓库中没有真实 Key。

## Codex 执行步骤

1. 先检查项目已有文件和约束，保留无关内容。
2. 按目录结构实现模块和测试，不一次性输出巨型 `app.py`。
3. 创建隔离虚拟环境，安装依赖并运行测试。
4. 启动 Streamlit，访问健康检查确认服务可用后停止测试进程。
5. 汇报文件、命令、测试结果，以及仍需用户填写的 `KIMI_API_KEY`；没有真实 Key 时不得伪称完成线上 API 测试。
