# LLM Agent Workflow

# LLM Agent 工作流程

This package contains the only maintained agent workflow. It uses LangGraph to
control the route and Gemini to make selected reasoning decisions.

此資料夾放的是目前唯一維護的 agent 工作流程。它使用 LangGraph 控制流程路由，
並使用 Gemini 做部分推理決策。

## Runtime Shape

## 執行流程

```text
normalize question
-> plan search tasks
-> retrieve evidence from PostgreSQL
-> select and label evidence
-> judge evidence sufficiency
-> retry planning if evidence is weak
-> generate cited answer
-> verify citations
```

中文說明：

```text
整理問題
-> 規劃搜尋任務
-> 從 PostgreSQL 檢索證據
-> 挑選並標記 evidence，例如 [S1], [S2]
-> 判斷證據是否足夠
-> 如果證據不足，重新規劃搜尋
-> 產生有引用來源的答案
-> 驗證 citation 是否正確
```

## File Responsibility

## 檔案職責

`graph_workflow.py`

Defines the LangGraph topology and routing.

定義 LangGraph 的節點與路由。

Important graph nodes:

重要節點：

```text
normalize
plan
retrieve
select_evidence
judge_evidence
answer
verify
```

Tool implementations remain registered through `agent.tools`, so retrieval,
ranking, citation verification, and logging stay in one shared tool layer.

實際工具仍註冊在 `agent.tools`，因此檢索、排序、citation 驗證與 logging 都維持在同一個
工具層。

`prompts.py`

Defines the LLM prompt templates for the planner and evidence judge.

定義 LLM planner 與 evidence judge 的 prompt template。

Each prompt is written with this structure:

每個 prompt 都用這個結構撰寫：

```text
Role
Situation
Task
Rules
Output Format
Examples
Current Input
```

`decisions.py`

Calls Gemini for JSON decisions with explicit response schemas, parses the
response, validates the basic shape, and falls back to deterministic decisions
if the LLM output is not usable.

呼叫 Gemini 取得 JSON 決策，並用明確的 response schema 要求固定格式；接著解析回覆、
驗證基本格式。如果 LLM 輸出不可用，會 fallback 到 deterministic decision。

## LLM Decisions

## LLM 決策

For normal runs, Gemini can decide:

一般執行時，Gemini 可以決定：

```text
which search queries to run
whether selected evidence directly answers the question
how to write the final cited answer
```

中文：

```text
要搜尋哪些 query
挑出的 evidence 是否真的回答問題
如何產生有 citation 的最終答案
```

Python still enforces guardrails:

Python 仍負責強制保護機制：

```text
maximum retry count
allowed tools
source selection boundaries
citation verification
run logging
```
