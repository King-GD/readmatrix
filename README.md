# ReadMatrix

<div align="center">

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](backend/pyproject.toml)
[![Nuxt](https://img.shields.io/badge/Nuxt-4-00DC82?logo=nuxt&logoColor=white)](frontend/package.json)
[![FastAPI](https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white)](backend/readmatrix/main.py)
[![License](https://img.shields.io/badge/License-MIT-black)](LICENSE)

本地优先的个人知识问答系统，面向读书笔记场景，支持 RAG 检索增强与引用追溯。

</div>

---

## 项目简介

ReadMatrix 是一个围绕“读书笔记 -> 可追溯问答”设计的本地优先系统：

- 后端使用 `FastAPI + ChromaDB` 进行索引、检索和问答。
- 前端使用 `Nuxt 4` 提供聊天式交互与引用查看。
- 支持 `OpenAI / SiliconFlow / Ollama` 等模型接入（按环境变量切换）。
- 所有回答都可附带引用来源，便于核查与复用。

## 核心特性

- `RAG 问答`：基于你的笔记进行检索增强生成。
- `引用追溯`：回答支持引用标记与出处回看。
- `本地优先`：索引和数据可保存在本地目录。
- `可切换模型`：支持多提供商配置。
- `CLI 工具链`：`doctor/index/serve/stats/eval` 一套命令完成常见操作。
- `Docker 部署`：支持一键启动前后端服务。

## 界面截图

> 以下为截图区模板。你可以把实际截图上传到仓库（例如 `assets/screenshots/`）后替换链接。

| 首页对话 | 引用面板 |
|---|---|
| ![Chat Page Placeholder](https://placehold.co/1200x720?text=ReadMatrix+Chat) | ![Citation Panel Placeholder](https://placehold.co/1200x720?text=Citation+Panel) |

| 健康检查 | 索引任务 |
|---|---|
| ![Doctor Placeholder](https://placehold.co/1200x720?text=Doctor) | ![Indexer Placeholder](https://placehold.co/1200x720?text=Indexer) |

## 技术栈

### Backend

- `FastAPI`
- `ChromaDB`
- `Pydantic Settings`
- `Typer`

### Frontend

- `Nuxt 4` + `Vue 3`
- `TypeScript`
- `Tailwind CSS`
- `Vercel AI SDK` (`@ai-sdk/vue`, `ai`)

## 系统架构

```text
Obsidian/WeRead 笔记
        |
        v
 [Parser + Chunker]
        |
        v
[Embedding + ChromaDB]
        |
        v
   [Retriever/Reranker]
        |
        v
   [LLM Answer + Citations]
        |
        v
     Nuxt 前端展示
```

## 快速开始

### 1. 环境要求

- Python `3.11+`
- Node.js `22+`
- pnpm
- 可选：`uv`（推荐）

### 2. 克隆项目

```bash
git clone <your-repo-url>
cd readmatrix
```

### 3. 配置环境变量

- 本地开发后端读取：`backend/.env`
- Docker Compose 读取：仓库根目录 `.env`
- 模板文件：根目录 `.env.example`

#### 本地开发（后端）

```bash
cd backend
cp ../.env.example .env
# 编辑 .env，填写 API Key 和 VAULT_PATH
```

#### Docker Compose

```bash
cd ..
cp .env.example .env
# 编辑 .env，填写 LLM_PROVIDER / EMBEDDING_PROVIDER / API KEY / VAULT_PATH
```

### 4. 本地启动（开发模式）

#### 启动后端

```bash
cd backend
uv sync
uv run readmatrix doctor
uv run readmatrix serve --reload
```

#### 启动前端

```bash
cd frontend
pnpm install
pnpm dev
```

访问：

- Frontend: `http://localhost:3000`
- Backend API: `http://localhost:8000`
- API Docs: `http://localhost:8000/docs`

### 5. Docker 一键启动

```bash
docker compose up -d
docker compose logs -f
docker compose down
```

## 常用命令

### 后端 CLI

```bash
cd backend

# 环境自检
readmatrix doctor

# 增量索引
readmatrix index

# 全量重建索引
readmatrix index --full

# 查看统计
readmatrix stats

# 运行离线评测
readmatrix eval --cases eval_cases.jsonl --mode retrieval
```

## 配置说明

### 关键环境变量

| 变量 | 说明 | 示例 |
|---|---|---|
| `LLM_PROVIDER` | LLM 提供商（`openai` / `siliconflow` / `ollama`） | `siliconflow` |
| `EMBEDDING_PROVIDER` | Embedding 提供商 | `siliconflow` |
| `OPENAI_API_KEY` | OpenAI API Key | `sk-***` |
| `SILICONFLOW_API_KEY` | SiliconFlow API Key | `sk-***` |
| `LLM_MODEL` | LLM 模型名 | `gpt-4o-mini` |
| `EMBEDDING_MODEL` | Embedding 模型名 | `text-embedding-3-small` |
| `VAULT_PATH` | 笔记目录（宿主机） | `/path/to/vault` |
| `WEREAD_FOLDER` | 微信读书目录名 | `微信读书` |
| `DATA_DIR` | 索引与数据库目录 | `./data` |

### 安全建议

- 不要提交任何 `.env` 文件（尤其 `backend/.env`）。
- 使用 `.env.example` 管理配置模板。
- 一旦密钥疑似泄露，立即在提供商后台轮换。

## 项目结构

```text
readmatrix/
├── backend/                 # Python 后端
│   ├── readmatrix/
│   │   ├── api/             # API 路由
│   │   ├── indexer/         # 索引与向量存储
│   │   ├── vault/           # 笔记扫描/解析/切分
│   │   ├── qa.py            # 问答流程
│   │   ├── retriever.py     # 检索逻辑
│   │   └── reranker.py      # 重排序逻辑
│   └── Dockerfile
├── frontend/                # Nuxt 前端
│   ├── components/
│   ├── composables/
│   ├── pages/
│   └── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## Roadmap

- [x] 基础 RAG 问答链路（检索 + 生成）
- [x] 引用追溯与前端展示
- [x] CLI 自检与索引命令
- [x] Docker Compose 部署支持
- [ ] 多库/多知识源管理
- [ ] 更细粒度检索过滤（标签、时间、来源）
- [ ] 管理后台（索引状态、质量分析）
- [ ] 完整 E2E 测试与性能基准

## 贡献指南

欢迎提交 Issue / PR。

### 提交流程

1. Fork 本仓库并创建分支：`feature/xxx` 或 `fix/xxx`
2. 保持提交粒度清晰，描述变更动机
3. 本地自测通过后发起 PR
4. 在 PR 描述里说明：改动范围、影响面、测试方式

### 开发约定

- 代码编码统一使用 `UTF-8`。
- 不提交本地构建产物、依赖目录和密钥文件。
- 新增功能优先保持简单可维护（KISS / YAGNI / DRY）。

## 常见问题

### Q1: 后端启动后找不到笔记？

检查 `VAULT_PATH` 和 `WEREAD_FOLDER` 是否正确，先执行 `readmatrix doctor`。

### Q2: Docker 已启动但前端无响应？

执行 `docker compose logs -f frontend backend` 查看容器日志；确认 `8000/3000` 端口未被占用。

### Q3: 为什么回答内容不稳定？

模型和检索参数会影响结果，可优先调整：`RETRIEVAL_TOP_K`、`RETRIEVAL_MAX_DISTANCE`、`QA_NOTE_RATIO`。

## License

MIT
