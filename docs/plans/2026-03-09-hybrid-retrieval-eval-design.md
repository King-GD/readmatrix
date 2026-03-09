# Hybrid Retrieval And Eval Pipeline Design

**Date:** 2026-03-09

## Goal

Upgrade ReadMatrix from single-path dense retrieval into a more reliable RAG stack with:

- hybrid retrieval: dense vector recall + sparse keyword recall
- reranking after multi-source recall fusion
- automated offline evaluation for retrieval and generation quality

This first version explicitly does **not** implement GraphRAG. The goal is to improve retrieval quality and make optimization measurable before adding a more complex graph layer.

## Current State

The backend already has useful foundations:

- dense retrieval via Chroma vector search in [retriever.py](/E:/code/readmatrix/backend/readmatrix/retriever.py)
- optional reranking via [reranker.py](/E:/code/readmatrix/backend/readmatrix/reranker.py)
- an offline evaluation entry point in [eval.py](/E:/code/readmatrix/backend/readmatrix/eval.py)

What is missing:

- sparse retrieval for exact keywords, titles, names, and quoted phrases
- a fusion strategy to combine dense and sparse recall
- durable evaluation cases, JSON reports, and regression comparison

## Scope

### In Scope

- SQLite-based sparse retrieval using FTS
- hybrid recall in the backend retriever
- reciprocal rank fusion (RRF) for candidate merging
- reranking after fusion
- offline retrieval and generation evaluation improvements
- machine-readable evaluation reports

### Out Of Scope

- GraphRAG and graph construction
- external search systems such as Elasticsearch or OpenSearch
- query rewriting agents
- judge-model answer scoring
- frontend UI for retrieval diagnostics

## Architecture

### Retrieval Flow

1. User query enters the retriever.
2. Dense recall fetches semantic candidates from Chroma.
3. Sparse recall fetches exact-match candidates from SQLite FTS.
4. Candidate lists are deduplicated by `chunk_id`.
5. RRF combines both ranked lists into one merged candidate set.
6. The merged candidate set is reranked with the existing cross-encoder path.
7. Context window expansion runs after reranking.
8. Final chunks are returned to the QA layer.

This keeps the current QA path stable while improving recall quality.

### Indexing Flow

The index pipeline must write two synchronized views of the same chunk data:

- vector embeddings into Chroma
- searchable text metadata into SQLite FTS

Chunk create, update, delete, and rebuild operations must keep both stores aligned.

## Data Model

## SQLite FTS Table

Add an FTS-backed chunk index storing:

- `chunk_id`
- `source_path`
- `book_id`
- `book_title`
- `title_path`
- `content`

The main table layout should remain simple and local-first. SQLite is enough for this project size and avoids introducing a new operational dependency.

## Fusion Strategy

Use **Reciprocal Rank Fusion (RRF)** in v1.

Reasoning:

- dense distance and BM25/FTS scores are not directly comparable
- RRF is simple, robust, and widely used for hybrid retrieval
- it avoids score normalization work in the first version

Suggested defaults:

- dense recall: 20
- sparse recall: 20
- fused candidate pool: 20 to 30
- reranked final candidate pool: 5 to 10 before context expansion

## Configuration

Add retrieval config flags in [config.py](/E:/code/readmatrix/backend/readmatrix/config.py):

- `retrieval_mode = dense | hybrid`
- `enable_sparse_retrieval`
- `dense_top_k`
- `sparse_top_k`
- `fusion_top_k`

Defaults should preserve current behavior where possible, with `hybrid` becoming opt-in until validated.

## Evaluation Pipeline

The evaluation layer should become a repeatable workflow instead of a one-off CLI.

### Retrieval Eval

Target metrics:

- Hit@k
- MRR
- optional Recall@k

### Generation Eval

Target metrics:

- citation recall
- citation count
- whether expected sources appear in citations

### Outputs

Store reports as JSON so results are comparable over time and can later feed CI.

Suggested directories:

- `backend/evals/cases/`
- `backend/evals/reports/`

Suggested modes:

- `retrieval`
- `generation`
- `all`

## Error Handling And Degradation

This system should fail soft:

- if sparse retrieval fails, fall back to dense retrieval
- if reranking fails, return fused ordering
- if FTS becomes stale or broken, make rebuild possible and surface a clear warning
- if evaluation inputs are invalid, fail loudly with a clear error message

The user-facing QA flow should stay available even if one retrieval component is degraded.

## Implementation Order

1. Add SQLite FTS support for chunks.
2. Update indexing so chunk writes update both Chroma and FTS.
3. Add sparse retrieval queries in the database layer.
4. Add fusion logic with RRF.
5. Upgrade the retriever to support dense or hybrid mode.
6. Extend the evaluation tool with stable case sets and JSON reports.
7. Compare dense vs hybrid on real project data.

## Acceptance Criteria

### Engineering

- hybrid mode can be enabled through config
- index rebuild keeps vector and FTS stores aligned
- existing QA flow keeps working

### Quality

- retrieval evaluation runs and reports stable metrics
- generation evaluation runs and reports stable metrics
- hybrid retrieval is measurably better than dense-only on at least part of the case set
- no major retrieval regression is introduced

### Operations

- the workflow is runnable through fixed commands
- reports are written to disk
- the setup is ready to connect to CI later

## Why GraphRAG Is Deferred

GraphRAG is useful for multi-hop, cross-document relationship questions, but it adds substantial cost:

- graph extraction
- graph storage
- entity and relationship maintenance
- graph-aware retrieval logic

ReadMatrix will get more immediate value from:

- improving recall quality now
- measuring regressions automatically

Once hybrid retrieval and evaluation are stable, GraphRAG can be added as a second-phase retrieval path rather than the first major upgrade.
