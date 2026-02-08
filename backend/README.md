# ReadMatrix Backend

Local-first personal knowledge platform with grounded Q&A.

## Installation

```bash
cd backend
pip install -e .
```

## Usage

```bash
# 从仓库根目录拷贝配置模板到 backend/.env
cp ../.env.example .env

# 启动前自检（可选）
readmatrix doctor

# 启动 API
readmatrix serve --reload
```
