# ReadMatrix 读书辩论功能设计（用户作为一方）

日期：2026-03-04  
状态：已确认，待实现

## 1. 目标与范围

在现有聊天页中新增“辩论模式”，支持用户与 AI 围绕读书主题进行对辩。

首版范围：
- 入口为现有页面开关，不新建独立页面
- 用户先填写开场配置后才能发送第一条辩论消息
- AI 默认站在用户立场的对立面
- 用户输入“结束”后，AI 产出辩论总结
- 辩论过程落到现有会话历史（SQLite 持久化）
- AI 允许补充通用知识，但必须显式标注“非笔记依据”

非目标（首版不做）：
- 多人实时辩论
- 独立辩论会话模型
- 复杂投票/裁判系统

## 2. 已确认业务规则

1. 对辩角色  
- 用户为一方，AI 为另一方
- AI 默认对立立场

2. 证据规则  
- 优先使用笔记检索证据
- 允许补充通用知识
- 通用知识必须句内标注 `【非笔记依据】`
- 同时在回答末尾给“非笔记依据”小节

3. 结束规则  
- 用户输入“结束”触发总结
- 默认中立总结
- 可通过配置指定是否判胜负（`judge_mode=winner`）

4. 入口与交互  
- 在现有聊天页增加“辩论模式”开关
- 开启后必须先填写：
  - `辩题`（必填）
  - `你的立场`（必填）
  - `是否判胜负`（可选，默认否）

5. 持久化  
- 辩论内容写入现有会话历史

## 3. 技术方案

采用“扩展现有 `/api/ask` 协议”的方案，不新增独立辩论 API。

### 3.1 后端协议扩展

`AskRequest` 新增可选字段：
- `mode`: `"qa" | "debate"`（默认 `"qa"`）
- `debate`:
  - `topic: string`
  - `user_stance: string`
  - `judge_mode?: "none" | "winner"`（默认 `"none"`）

`AskResponse` / SSE `meta` 新增可选元信息：
- `mode`
- `debate_status`: `"active" | "ended"`
- `debate_event`: `"normal" | "end_summary"`

兼容性：
- 老客户端不传新字段时，行为完全保持现状

### 3.2 后端执行逻辑

1. `mode=qa`：沿用当前逻辑  
2. `mode=debate` 且非结束词：
- 根据辩题、用户立场构建辩论 Prompt
- AI 强制对立立场
- 优先引用笔记证据
- 外部知识强制标注 `【非笔记依据】` + 末尾证据小节
3. `mode=debate` 且命中结束词：
- 走“总结 Prompt”
- 输出结构化总结
- `judge_mode=winner` 时附加胜负判断
- 总结后返回 `debate_status=ended`

结束词（首版）：
- `结束`
- `结束辩论`
- `停止辩论`

### 3.3 持久化策略

沿用当前会话表：
- `conversations`
- `conversation_messages`

辩论普通消息按现有 user/assistant 消息落库。  
辩论状态（配置、状态）以隐藏 system 元信息消息存储（不对前端消息列表直接展示），用于刷新恢复。

### 3.4 前端交互设计

基于 `useChat` 扩展状态：
- `mode: "qa" | "debate"`
- `debateConfig: { topic, userStance, judgeMode } | null`
- `debateStatus: "idle" | "active" | "ended"`

页面行为：
1. 打开“辩论模式” -> 展示开场配置面板
2. 未完成配置前禁用输入
3. 配置确认后才能发送
4. 输入“结束”后展示总结
5. 总结完成自动退出辩论模式（回到普通问答）

## 4. 错误处理

1. `mode=debate` 且缺少必填配置 -> `400`  
2. 检索无命中：
- 允许继续辩论
- 明确说明未命中笔记，外部补充按规则标注
3. 流中断：
- 沿用现有错误兜底
4. 结束词误触发：
- 仅精确匹配结束词

## 5. 测试计划（首版）

后端：
1. 老请求兼容（无 mode/debate）
2. 辩论模式缺配置返回 400
3. 普通辩论回合返回对辩内容与 citations 结构
4. 结束词触发总结，并携带 `debate_status=ended`
5. `judge_mode=winner` 时包含胜负段落（通过 prompt 行为约束 + 结果断言）

前端（手工验证）：
1. 未填开场配置时输入禁用
2. 完成配置后可发送
3. 输入“结束”后产出总结并自动退出辩论模式
4. 刷新后会话历史可恢复

## 6. 实施清单

1. 后端：`api/routes.py`、`qa.py`、`conversation.py`、`indexer/database.py`  
2. 前端：`composables/useChat.ts`、`pages/index.vue`、`components/chat/ChatInput.vue`  
3. 测试：`backend/tests/test_api_ask.py`（新增辩论用例）
