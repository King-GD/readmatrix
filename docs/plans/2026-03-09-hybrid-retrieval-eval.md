# Hybrid Retrieval And Eval Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add SQLite FTS-based sparse retrieval, hybrid recall fusion, and repeatable offline evaluation reports to ReadMatrix without introducing new external infrastructure.

**Architecture:** Keep Chroma as the dense retrieval backend, add SQLite FTS as the sparse retrieval backend, fuse candidate lists with RRF, then reuse the existing reranker and QA pipeline. Extend the existing offline eval command so retrieval and generation quality can be compared across runs with JSON reports.

**Tech Stack:** Python 3.11, FastAPI, SQLite FTS5, ChromaDB, Rich, Typer, Pytest

---

### Task 1: Add failing tests for sparse retrieval and hybrid fusion

**Files:**
- Create: `backend/tests/test_hybrid_retriever.py`
- Modify: `backend/tests/test_api_ask.py`
- Reference: `backend/readmatrix/retriever.py`

**Step 1: Write the failing tests**

Add tests for:
- sparse retrieval returning a chunk by exact keyword/book title
- hybrid retrieval returning a result found only by sparse recall
- hybrid retrieval keeping dense behavior when sparse retrieval is disabled

Use a fake vector store and a temp SQLite database so retrieval logic is isolated and deterministic.

**Step 2: Run tests to verify they fail**

Run:
```bash
cd E:\code\readmatrix\backend
uv run pytest -q tests/test_hybrid_retriever.py
```

Expected:
- missing sparse retrieval methods
- missing hybrid retrieval mode/config

**Step 3: Add one API-level regression test**

Extend [`backend/tests/test_api_ask.py`](/E:/code/readmatrix/backend/tests/test_api_ask.py) so one ask-flow test can run with hybrid retrieval enabled and still return grounded citations.

**Step 4: Run the focused API test**

Run:
```bash
cd E:\code\readmatrix\backend
uv run pytest -q tests/test_api_ask.py
```

Expected:
- failure due to missing hybrid retrieval plumbing

**Step 5: Commit**

```bash
git add backend/tests/test_hybrid_retriever.py backend/tests/test_api_ask.py
git commit -m "test: add hybrid retrieval coverage"
```

### Task 2: Add SQLite FTS storage and query support

**Files:**
- Modify: `backend/readmatrix/indexer/database.py`
- Modify: `backend/readmatrix/models.py`
- Test: `backend/tests/test_hybrid_retriever.py`

**Step 1: Add the failing database-level test**

Add a focused test that:
- inserts chunk metadata/content into SQLite
- queries sparse retrieval
- expects exact title/keyword matches in ranked results

**Step 2: Run the single failing test**

Run:
```bash
cd E:\code\readmatrix\backend
uv run pytest -q tests/test_hybrid_retriever.py::test_sparse_search_returns_exact_match
```

Expected:
- failure because FTS tables/methods do not exist

**Step 3: Implement minimal database support**

In [`backend/readmatrix/indexer/database.py`](/E:/code/readmatrix/backend/readmatrix/indexer/database.py):
- add an FTS5 table for chunks
- add methods similar to:
  - `upsert_sparse_chunk(...)`
  - `delete_sparse_chunks_by_source_path(...)`
  - `search_sparse_chunks(query, limit, book_id, book_title)`
- make sure chunk rows can be rehydrated into `Chunk` objects or chunk-like records

In [`backend/readmatrix/models.py`](/E:/code/readmatrix/backend/readmatrix/models.py):
- add a lightweight structure only if needed to keep sparse retrieval results typed
- otherwise reuse `Chunk`

**Step 4: Run the sparse retrieval test**

Run:
```bash
cd E:\code\readmatrix\backend
uv run pytest -q tests/test_hybrid_retriever.py::test_sparse_search_returns_exact_match
```

Expected:
- PASS

**Step 5: Commit**

```bash
git add backend/readmatrix/indexer/database.py backend/readmatrix/models.py backend/tests/test_hybrid_retriever.py
git commit -m "feat: add sqlite fts retrieval support"
```

### Task 3: Synchronize indexing with FTS writes and deletes

**Files:**
- Modify: `backend/readmatrix/indexer/manager.py`
- Modify: `backend/readmatrix/indexer/database.py`
- Test: `backend/tests/test_hybrid_retriever.py`

**Step 1: Add an indexing synchronization test**

Add a test covering:
- file index writes both vector and FTS entries
- incremental delete removes both vector and sparse entries

Use fake vector store hooks and temp files where practical.

**Step 2: Run the failing sync test**

Run:
```bash
cd E:\code\readmatrix\backend
uv run pytest -q tests/test_hybrid_retriever.py::test_index_manager_syncs_sparse_index
```

Expected:
- failure because index manager only writes Chroma

**Step 3: Implement minimal sync logic**

In [`backend/readmatrix/indexer/manager.py`](/E:/code/readmatrix/backend/readmatrix/indexer/manager.py):
- on `_index_file`, write chunks to FTS after embedding/vector write
- on file removal or reindex, remove stale sparse rows by `source_path`

In [`backend/readmatrix/indexer/database.py`](/E:/code/readmatrix/backend/readmatrix/indexer/database.py):
- keep delete helpers symmetric with vector deletes

**Step 4: Run the sync test**

Run:
```bash
cd E:\code\readmatrix\backend
uv run pytest -q tests/test_hybrid_retriever.py::test_index_manager_syncs_sparse_index
```

Expected:
- PASS

**Step 5: Commit**

```bash
git add backend/readmatrix/indexer/manager.py backend/readmatrix/indexer/database.py backend/tests/test_hybrid_retriever.py
git commit -m "feat: sync sparse index with chunk indexing"
```

### Task 4: Implement hybrid retriever with RRF fusion

**Files:**
- Modify: `backend/readmatrix/retriever.py`
- Create: `backend/readmatrix/retrieval_fusion.py`
- Modify: `backend/readmatrix/config.py`
- Test: `backend/tests/test_hybrid_retriever.py`

**Step 1: Add failing fusion tests**

Add tests for:
- RRF merges dense and sparse result lists by rank
- hybrid mode retrieves sparse-only hits
- dense mode still behaves like current production behavior
- reranker is called after fusion, not before

**Step 2: Run the fusion test file**

Run:
```bash
cd E:\code\readmatrix\backend
uv run pytest -q tests/test_hybrid_retriever.py
```

Expected:
- failure because fusion/config do not exist

**Step 3: Implement minimal fusion**

Create [`backend/readmatrix/retrieval_fusion.py`](/E:/code/readmatrix/backend/readmatrix/retrieval_fusion.py) with:
- `reciprocal_rank_fusion(...)`
- helper for dedupe by `chunk_id`

Update [`backend/readmatrix/config.py`](/E:/code/readmatrix/backend/readmatrix/config.py) with:
- `retrieval_mode`
- `enable_sparse_retrieval`
- `dense_top_k`
- `sparse_top_k`
- `fusion_top_k`

Update [`backend/readmatrix/retriever.py`](/E:/code/readmatrix/backend/readmatrix/retriever.py) so:
- dense-only mode remains supported
- hybrid mode runs dense + sparse + RRF + rerank + context expansion
- sparse retrieval failures degrade to dense-only with a warning

**Step 4: Run the full hybrid retriever tests**

Run:
```bash
cd E:\code\readmatrix\backend
uv run pytest -q tests/test_hybrid_retriever.py tests/test_api_ask.py
```

Expected:
- PASS

**Step 5: Commit**

```bash
git add backend/readmatrix/retriever.py backend/readmatrix/retrieval_fusion.py backend/readmatrix/config.py backend/tests/test_hybrid_retriever.py backend/tests/test_api_ask.py
git commit -m "feat: add hybrid retrieval with rrf fusion"
```

### Task 5: Extend offline eval into a repeatable report pipeline

**Files:**
- Modify: `backend/readmatrix/eval.py`
- Create: `backend/evals/cases/retrieval.jsonl`
- Create: `backend/evals/cases/generation.jsonl`
- Create: `backend/tests/test_eval_pipeline.py`

**Step 1: Add failing eval pipeline tests**

Cover:
- loading retrieval and generation case files from the new default directories
- writing JSON reports to disk
- comparing a new run to an existing baseline report

**Step 2: Run the eval pipeline tests**

Run:
```bash
cd E:\code\readmatrix\backend
uv run pytest -q tests/test_eval_pipeline.py
```

Expected:
- failure because report output/baseline comparison is missing

**Step 3: Implement minimal report output**

In [`backend/readmatrix/eval.py`](/E:/code/readmatrix/backend/readmatrix/eval.py):
- add default case paths under `backend/evals/cases`
- add JSON output path support
- add a simple baseline diff summary
- add an `all` mode that runs retrieval and generation sequentially

Create small but representative seed cases in:
- [`backend/evals/cases/retrieval.jsonl`](/E:/code/readmatrix/backend/evals/cases/retrieval.jsonl)
- [`backend/evals/cases/generation.jsonl`](/E:/code/readmatrix/backend/evals/cases/generation.jsonl)

**Step 4: Run eval pipeline tests**

Run:
```bash
cd E:\code\readmatrix\backend
uv run pytest -q tests/test_eval_pipeline.py
```

Expected:
- PASS

**Step 5: Commit**

```bash
git add backend/readmatrix/eval.py backend/evals/cases/retrieval.jsonl backend/evals/cases/generation.jsonl backend/tests/test_eval_pipeline.py
git commit -m "feat: add repeatable rag eval reporting"
```

### Task 6: Run end-to-end backend validation

**Files:**
- Modify if needed: `backend/readmatrix/retriever.py`
- Modify if needed: `backend/readmatrix/eval.py`
- Test: all backend tests

**Step 1: Run the backend test suite**

Run:
```bash
cd E:\code\readmatrix\backend
uv run pytest -q
```

Expected:
- all retrieval, API, review, conversation, and eval tests pass

**Step 2: Run retrieval eval in dense mode**

Run:
```bash
cd E:\code\readmatrix\backend
uv run python -m readmatrix.eval run --mode retrieval --cases backend/evals/cases/retrieval.jsonl
```

Expected:
- terminal summary with hit rate and MRR
- JSON report written if configured

**Step 3: Run retrieval eval in hybrid mode**

Run:
```bash
cd E:\code\readmatrix\backend
uv run python -m readmatrix.eval run --mode retrieval --cases backend/evals/cases/retrieval.jsonl
```

Expected:
- summary is at least non-regressive
- inspect case-level improvements manually before tuning

**Step 4: Run generation eval**

Run:
```bash
cd E:\code\readmatrix\backend
uv run python -m readmatrix.eval run --mode generation --cases backend/evals/cases/generation.jsonl
```

Expected:
- citation recall and average citation counts are reported

**Step 5: Commit**

```bash
git add backend/readmatrix/retriever.py backend/readmatrix/eval.py backend/tests backend/evals
git commit -m "chore: validate hybrid retrieval and eval pipeline"
```

### Task 7: Optional follow-up tuning pass

**Files:**
- Modify if needed: `backend/readmatrix/config.py`
- Modify if needed: `backend/evals/cases/*.jsonl`

**Step 1: Review dense vs hybrid report deltas**

Look for:
- sparse-only rescue cases
- keyword-heavy failure cases
- reranker regressions

**Step 2: Tune only minimal parameters**

Allowed first-pass tuning:
- `dense_top_k`
- `sparse_top_k`
- `fusion_top_k`
- retrieval mode default

Do not add GraphRAG or query rewriting in this pass.

**Step 3: Re-run eval**

Run:
```bash
cd E:\code\readmatrix\backend
uv run pytest -q
uv run python -m readmatrix.eval run --mode all
```

Expected:
- stable or improved metrics

**Step 4: Commit**

```bash
git add backend/readmatrix/config.py backend/evals/cases
git commit -m "perf: tune hybrid retrieval defaults"
```
