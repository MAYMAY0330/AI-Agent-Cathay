# Agent Layer

# Agent 層說明

The `agent/` package is the orchestration layer. It does not store documents and
does not directly own SQL search logic. It coordinates tools that retrieve
evidence from `rag/`, call Gemini, verify citations, and write logs.

`agent/` 是 orchestration layer。它不負責存文件，也不直接管理 SQL 搜尋邏輯。
它負責協調工具：從 `rag/` 檢索 evidence、呼叫 Gemini、驗證 citations、寫入 logs。

## File Map

## 檔案地圖

```text
agent/
  run.py
  workflow.py
  state.py
  tools.py
  tool_registry.py
  llm_agent/
    graph_workflow.py
    prompts.py
    decisions.py
  tests/
```

`run.py`

Command-line entrypoint.

命令列入口。當你執行 `python -m agent.run "問題"` 時，會先進到這個檔案。

`workflow.py`

Top-level coordinator.

總控管者。建立 run id、連接 DB、建立 tool registry、執行 LLM graph、寫入 run log。

`state.py`

Shared run state models.

共同狀態資料模型。定義一次 agent run 會記住什麼，例如 question、search tasks、
retrieved sources、answer、verification、LLM decisions。

`tools.py`

Agent tool implementations.

Agent 工具實作。包含 normalize、LLM search planner、retrieval、evidence selection、
LLM evidence judge、answer generation、citation verification、logging。

`tool_registry.py`

Tool registration and controlled tool calling.

工具註冊與受控呼叫。workflow 透過 `registry.call_tool(...)` 呼叫工具，而不是直接散亂呼叫函式。

`llm_agent/`

Primary LangGraph LLM workflow.

主要的 LangGraph LLM agent 工作流程。

`llm_agent/prompts.py`

Prompt templates for the LLM planner and evidence judge.

LLM planner 與 evidence judge 的 prompt template。

`llm_agent/decisions.py`

Gemini structured JSON decision calls and parsing/fallback logic.

Gemini 結構化 JSON 決策呼叫、解析與 fallback 邏輯。

`tests/`

Unit tests.

單元測試。

## Current Agent Path

## 目前 Agent 路徑

Normal command:

一般執行：

```bash
python -m agent.run "資料共享是否需要告知客戶？" --vector
```

Enable the small RAG search agent for extra validated query expansion:

啟用 RAG 內部的小型 search agent，讓檢索時多產生幾組經過驗證的搜尋 query：

```bash
python -m agent.run "資料共享是否需要告知客戶？" --vector --agentic-search
```

Execution path:

執行路徑：

```text
run.py
-> workflow.py
-> llm_agent/graph_workflow.py
-> tools.py
-> rag/
-> Gemini
-> citation verifier
-> JSONL log
```
