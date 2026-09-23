# 复盘驾驶舱

一个本机优先的复盘工具，包含 **Next.js 前端** 与 **FastAPI 后端**。公开网页负责交互；复盘资料、RAG 数据库、API Key、生成任务和 Excel/Word 产物都留在运行者本机。

## 功能

- **每日复盘**：抓取公开复盘或导入文件；按需并行生成 Excel 与 Word，支持单分支重试。
- **知识库**：公开帖子增量同步、历史归档、人工体系导入，结合 BM25 与本地语义检索并保留来源引用。
- **首板布局**：先校验当日快照与规则，再筛选候选、检索证据、批量分析并导出审计结果。
- **历史与诊断**：查看任务状态、失败原因、耗时、来源和生成文件。

## Windows 快速开始

1. 安装 Python（可用 `py` 启动器）并复制配置模板：

   ```powershell
   Copy-Item backend/.env.example backend/.env
   ```

2. 编辑 `backend/.env`，填入 `DEEPSEEK_API_KEY`。不要把 `.env` 发给他人或提交到 Git。
3. 双击根目录的 **`启动复盘驾驶舱.cmd`**。首次启动会创建 `backend/.venv`、安装依赖并启动只监听 `127.0.0.1:8765` 的本机服务，然后打开驾驶舱页面。

当前网页入口：[fupan-review-cockpit.netlify.app](https://fupan-review-cockpit.netlify.app)。

站点页面不会读取 API Key；本机服务令牌由启动器生成并通过浏览器会话传递。若只使用规则、查看已有资料等不调用模型的功能，可先不配置模型 Key。

## 项目结构

```text
backend/             FastAPI、本地知识库、任务与文件处理
frontend/            Next.js/Vinext 页面和前端测试
docs/architecture/   Archify 架构图与流程图（HTML 可交互）
docs/rag/            经整理的 Markdown 参考资料
启动复盘驾驶舱.cmd    Windows 一键启动入口
start_review_cockpit.ps1
延边刺客短线打板体系.docx  当前人工体系 RAG 导入源
```

## 架构与流程图

从 [`docs/architecture/README.md`](docs/architecture/README.md) 打开系统架构、每日复盘和首板布局图。HTML 图可直接在浏览器查看。

## RAG 资料说明

`docs/rag/` 收录经整理的核心参考文本：

- [2025复盘｜六板及以上](<docs/rag/2025复盘_六板及以上.md>)
- [2026复盘｜五板及以上](<docs/rag/2026复盘_五板及以上个股_截至20260821.md>)
- [高标总结与交易心法](<docs/rag/高标总结与交易心法.md>)
- [个人短线交易系统 V1.0](<docs/rag/个人短线交易系统 V1.0.md>)
- [延边刺客短线打板体系](<docs/rag/延边刺客短线打板体系.md>)

这些 Markdown 便于阅读与版本管理；**当前后端自动导入器读取的是仓库根目录的 `延边刺客短线打板体系.docx`，不会自动把上述 Markdown 加入运行时数据库**。本机数据库和生成文件位于 `backend/data/` 等运行目录，不随仓库提交。

## 开发与验证

### 后端

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m pytest
```

### 前端

需要 Node.js `>=22.13.0`：

```powershell
cd frontend
npm ci
npm run dev
npm run build
npm test
```

`npm test` 会先构建，再运行页面 HTML 回归测试。正式日常使用建议从根目录启动器进入，以确保本机服务令牌与站点会话配套。

## 隐私边界

仓库只包含经审阅的程序代码、说明图与精选参考资料；不包含 API Key、本机数据库、生成产物、每日原始复盘、个人交易记录或本机路径。新增资料提交前请按 [`PRIVACY.md`](PRIVACY.md) 检查。
