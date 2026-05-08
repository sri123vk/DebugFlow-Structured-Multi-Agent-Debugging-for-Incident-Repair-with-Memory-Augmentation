# DebugFlow: Structured Multi-Agent Debugging for Incident Repair with Memory Augmentation

DebugFlow is a research-oriented prototype for autonomous software incident triage, root-cause localization, patch generation, and verification. The system combines multi-agent reasoning, MemGPT-inspired memory management, Retrieval-Augmented Generation (RAG), lightweight code graph expansion, and constraint-aware verification to simulate modern AI-assisted incident-response workflows.

The project explores how autonomous agents can move beyond passive code assistants and instead perform iterative debugging workflows similar to real software engineers.

---

# Motivation

Modern software systems require engineers to rapidly diagnose incidents, localize failures across large repositories, validate fixes, and ensure patches do not violate business or infrastructure constraints.

Current LLM-based coding assistants primarily:
- operate statelessly
- lack persistent memory
- struggle with repository-scale reasoning
- overfocus on local error regions
- fail to validate fixes against system constraints

DebugFlow investigates whether a memory-augmented multi-agent system can autonomously perform:

```text
incident triage
→ root-cause localization
→ patch generation
→ verification
→ PR-style repair reasoning
```

while incorporating:
- historical debugging memory
- repository structure
- domain constraints
- iterative reasoning loops

---

# System Overview

The DebugFlow pipeline consists of:

```text
Incident Report
    ↓
Context Builder
    ↓
Memory Retrieval
    ↓
RAG Retrieval
    ↓
Code Graph Expansion
    ↓
Constraint Injection
    ↓
Structured Debugging Context
    ↓
Multi-Agent Repair Loop
    ↓
Verification
    ↓
Memory Update
```

---

# Core Components

## 1. Benchmark Environment

The repository contains seeded debugging incidents designed to simulate realistic software engineering failures.

Implemented incidents include:

### Duplicate Event Retry Incident
- Retry pipeline reprocesses events without idempotency protection
- Misleading symptom appears in analytics report layer
- Correct repair requires fixing upstream retry logic

### BigQuery Cost Spike Incident
- Query generation removes partition filter
- Query output remains correct but infrastructure cost explodes
- Correct repair must preserve both correctness and cost constraints

The benchmark intentionally includes:
- misleading symptoms
- multi-hop reasoning
- upstream root causes
- constraint-sensitive debugging

---

# 2. MemGPT-Inspired Memory Architecture

DebugFlow adapts concepts from MemGPT-style memory systems to software debugging workflows.

The system separates memory into:

## Working Context
Stores:
- current incident
- retrieved files
- hypotheses
- verification outcomes
- repair attempts

## Recall Memory
Stores:
- previous incidents
- successful repair patterns
- historical debugging outcomes

## Archival Memory
Stores:
- long-term repository knowledge
- risky modules
- recurring bug patterns
- infrastructure-sensitive regions

Memory updates occur only after successful verification to avoid propagating incorrect debugging patterns.

---

# 3. Retrieval-Augmented Generation (RAG)

The system performs lightweight semantic retrieval over:
- repository files
- incident descriptions
- tests
- historical repairs

RAG narrows the debugging search space and provides candidate files for localization.

---

# 4. Lightweight Code Graph Expansion

Pure semantic retrieval often causes localization bias.

To address this, DebugFlow expands retrieved context using lightweight repository graph reasoning:
- callers
- callees
- covering tests

This allows the system to reason across structural repository relationships rather than only local error regions.

Example:

```text
report layer
   ↑
retry pipeline
   ↑
ingestion logic
```

This helps reduce tunnel vision during debugging.

---

# 5. Constraint-Aware Verification

Many incorrect patches superficially fix symptoms while violating system constraints.

DebugFlow therefore includes:
- pytest-based validation
- simulated infrastructure constraints
- domain-specific repair checks

Examples:
- preserve partition filters
- maintain query-cost thresholds
- avoid deleting valid repeated events

---

# 6. Localization-Support Evaluation

The project evaluates whether the context-building pipeline successfully retrieves the true root-cause region before patch generation occurs.

Metrics include:
- root-cause retrieval success
- RAG retrieval coverage
- graph expansion coverage
- memory retrieval hits
- constraint injection statistics

This allows evaluation of localization quality independently from downstream LLM patch generation.

---

# Benchmark Modes

The system supports multiple benchmark configurations.

## Single-Agent Baseline

```text
incident only
```

No retrieval or memory augmentation.

---

## RAG-Only Baseline

```text
incident + semantic retrieval
```

No graph reasoning or memory.

---

## Full DebugFlow Pipeline

```text
incident
+ memory
+ RAG
+ graph expansion
+ constraints
```

This enables comparison between:
- stateless debugging
- retrieval-only debugging
- memory-augmented structured debugging

---

# Repository Structure

```text
aiagents/
│
├── bugs/
├── tests/
├── incidents/
├── memory/
├── context/
├── evaluation/
├── outputs/
│
├── verifier.py
├── run_person_a.py
└── README.md
```

---

# Running the Project

## Build Context

### Duplicate Retry Incident

```bash
python -m context.builder \
  --incident incidents/duplicate_retry.json \
  --repo . \
  --out outputs/context_duplicate_retry.json
```

### BigQuery Cost Spike Incident

```bash
python -m context.builder \
  --incident incidents/bq_cost_spike.json \
  --repo . \
  --out outputs/context_bq_cost_spike.json
```

---

# Run Full Pipeline

```bash
python run_person_a.py \
  --incident incidents/duplicate_retry.json \
  --repo .
```

---

# Run Verifier

```bash
python -m verifier \
  --incident incidents/duplicate_retry.json \
  --repo .
```

---

# Run Evaluation Metrics

```bash
python evaluation/person_a_metrics.py \
  --context outputs/INC-DUP-001_context.json
```

---

# Example Metrics

```json
{
  "incident_id": "INC-DUP-001",
  "root_cause_file_retrieved": true,
  "num_rag_chunks": 5,
  "num_graph_callers": 2,
  "num_graph_callees": 5,
  "num_tests": 1,
  "num_constraints": 1,
  "num_recall_hits": 1,
  "num_archival_hits": 1
}
```

---

# Research Questions

The project investigates:

1. Does memory improve root-cause localization?
2. Does graph expansion reduce localization bias?
3. Can structured debugging context improve repair quality?
4. Does memory augmentation outperform RAG-only systems?
5. Can verification-aware memory reduce memory pollution?

---

# Future Work

Future extensions may include:
- larger repositories
- dynamic execution traces
- real deployment logs
- prompt-injection robustness
- memory poisoning defenses
- multi-service debugging
- richer graph traversal
- production-scale agent orchestration

---

# Technologies

- Python
- Pytest
- JSON-based benchmark infrastructure
- Lightweight RAG retrieval
- Repository graph traversal
- Memory-augmented reasoning

---

# Authors

- Srimathi Ravisankar
- Clara Zhang

---

# Disclaimer

This project is a research-oriented educational prototype designed for experimentation with autonomous debugging workflows. The benchmark and repository are intentionally simplified to enable controlled evaluation and rapid iteration.
