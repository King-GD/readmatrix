# Eval Cases (Core v1)

本目录用于维护 `readmatrix eval` 的标准评测集。

## 文件说明

- `core-v1.jsonl`：核心评测集模板（30 条）

## 每条 case 结构

```json
{
  "id": "fact_01",
  "query": "用户真实会问的问题",
  "expected": {
    "book_title": ["书名A", "书名B"],
    "source_path": ["路径关键词A", "路径关键词B"],
    "must_include": ["关键词1", "关键词2"]
  },
  "meta": {
    "bucket": "fact|compare|reason|no_answer",
    "priority": "high|medium|low"
  }
}
```

`expected` 字段与当前评测逻辑对应：

- `book_title`：命中块的 `book_title` 需要包含其中任一项
- `source_path`：命中块的 `source_path` 需要包含其中任一项
- `must_include`：命中块 `content` 需要包含全部关键词

当 `expected = {}` 时，表示该问题应为“无答案/无相关笔记”场景。

## 构建方法（建议）

1. 先收集你最近真实提问 30 条，不要让 AI 虚构。
2. 每条问题手工标注 1-3 个证据锚点（书名/路径/关键词）。
3. 先跑 `retrieval`，修正歧义问题和标注不准的 case。
4. 再跑 `generation`，观察引用召回是否符合预期。

## 运行命令

```powershell
cd E:\code\readmatrix\backend
uv run readmatrix eval --cases eval_cases/core-v1.jsonl --mode retrieval
uv run readmatrix eval --cases eval_cases/core-v1.jsonl --mode generation
```

## 标注建议

- 优先填 `book_title`，其次 `must_include`，最后 `source_path`
- `must_include` 不宜过长，建议 1-3 个短关键词
- 对于对比问题，`book_title` 至少填 2 本书
- 对于无答案问题，`expected` 保持空对象 `{}` 即可
