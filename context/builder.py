"""
context/builder.py
───────────────────
Person A's primary deliverable.

Interface:
    build_context(incident: dict, repo_path: str = ".") -> dict

Combines all four systems into one context.json payload
that Person B's agent loop consumes directly.

Four systems wired together:
  1. Working context  — seeds the active incident state (Tier 1)
  2. Recall storage   — searches session log for this incident (Tier 2)
  3. Archival storage — searches past RCAs and fix patterns (Tier 3)
  4. Code graph       — expands call chain from error site

Output shape:
  {
    "incident_id":       str,
    "working_context":   { ... },   # Tier 1 state
    "recall_hits":       [ ... ],   # Tier 2 — session entries
    "archival_hits":     [ ... ],   # Tier 3 — past RCAs
    "patch_patterns":    [ ... ],   # Tier 3 — fix templates
    "code_graph":        { ... },   # call chain expansion
    "rag_chunks":        [ ... ],   # relevant code text (simple TF-IDF)
    "domain_constraints":[ ... ],   # loaded from constraints/*.json
    "context_summary":   { ... },   # token estimate + counts
  }
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Optional

from context.working_context import WorkingContext, Hypothesis
from context.recall_storage  import RecallStorage, RecallEntry
from context.archival_storage import ArchivalStorage
from context.code_graph       import CodeGraph


# ── Simple TF-IDF RAG (no external deps) ──────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _tfidf_score(query_terms: list[str], doc_terms: list[str],
                 all_docs: list[list[str]]) -> float:
    """Lightweight TF-IDF score — no sklearn needed."""
    N = len(all_docs)
    score = 0.0
    doc_set = set(doc_terms)
    for term in query_terms:
        tf  = doc_terms.count(term) / (len(doc_terms) + 1)
        df  = sum(1 for d in all_docs if term in d) + 1
        idf = math.log(N / df) + 1
        score += tf * idf
    return round(score, 4)


def _rag_retrieve(
    incident: dict,
    repo_path: str,
    top_k: int = 5,
) -> list[dict]:
    """
    Retrieve the most relevant code chunks for this incident.
    Chunks at function level using Python ast.
    Query = incident title + symptoms + error_class.
    """
    import ast

    query_text = " ".join([
        incident.get("title", ""),
        incident.get("error_class", ""),
        incident.get("service", ""),
        " ".join(incident.get("symptoms", [])),
    ])
    query_terms = _tokenize(query_text)

    # Collect all function-level chunks from the repo
    chunks = []
    repo   = Path(repo_path)

    for py_file in repo.rglob("*.py"):
        rel = str(py_file.relative_to(repo))
        try:
            source = py_file.read_text()
            tree   = ast.parse(source)
            lines  = source.splitlines()
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    start  = node.lineno - 1
                    end    = getattr(node, "end_lineno", node.lineno)
                    code   = "\n".join(lines[start:end])
                    # Include docstring if present
                    doc    = ast.get_docstring(node) or ""
                    full   = code + " " + doc
                    chunks.append({
                        "file":     rel,
                        "function": node.name,
                        "code":     code,
                        "terms":    _tokenize(full),
                    })
        except Exception:
            continue

    if not chunks:
        return []

    all_doc_terms = [c["terms"] for c in chunks]

    # Score and rank
    scored = []
    for chunk in chunks:
        score = _tfidf_score(query_terms, chunk["terms"], all_doc_terms)
        if score > 0:
            scored.append({
                "file":     chunk["file"],
                "function": chunk["function"],
                "code":     chunk["code"],
                "score":    score,
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


# ── Domain constraint loader ───────────────────────────────────────────────────

def _load_domain_constraints(incident: dict, repo_path: str) -> list[dict]:
    """Load constraints referenced by this incident."""
    constraint_ids = incident.get("domain_constraint_ids", [])
    constraints    = []
    constraints_dir = Path(repo_path) / "constraints"

    if not constraints_dir.exists():
        return []

    for cfile in constraints_dir.glob("*.json"):
        data = json.loads(cfile.read_text())
        rows = data if isinstance(data, list) else [data]
        for row in rows:
            if row.get("constraint_id") in constraint_ids:
                constraints.append(row)

    return constraints


# ── Token estimator ────────────────────────────────────────────────────────────

def _estimate_tokens(text: str) -> int:
    return int(len(text) * 0.25)


# ══════════════════════════════════════════════════════════════════════════════
# Main deliverable
# ══════════════════════════════════════════════════════════════════════════════

def build_context(
    incident:    dict,
    repo_path:   str = ".",
    recall_dir:  str = "memory/recall",
    archival_db: str = "memory/archival.json",
    rag_top_k:   int = 5,
    archival_top_k: int = 3,
) -> dict:
    """
    Person A's primary deliverable.
    Takes an incident dict, returns full context for Person B's agent.

    Args:
        incident:      loaded from incidents/*.json
        repo_path:     path to the toy repo root
        recall_dir:    where per-incident session logs live
        archival_db:   path to the permanent archival JSON store
        rag_top_k:     number of code chunks to retrieve
        archival_top_k:number of past incidents to surface

    Returns:
        context dict ready to be serialised as context.json
    """
    incident_id   = incident.get("incident_id", "unknown")
    error_class   = incident.get("error_class", "")
    service       = incident.get("service", "")
    affected_file = incident.get("affected_file", "")
    affected_fn   = incident.get("affected_function", "")
    symptoms      = incident.get("symptoms", [])

    print(f"[build_context] incident={incident_id}  service={service}")

    # ── 1. Working context — seed Tier 1 ────────────────────────────────────
    print("[build_context] step=working_context")
    wc = WorkingContext.from_incident(incident)

    # ── 2. Recall storage — search Tier 2 ───────────────────────────────────
    print("[build_context] step=recall_search")
    recall  = RecallStorage(recall_dir)
    query   = f"{error_class} {service} {' '.join(symptoms)}"
    recall_hits = recall.search(incident_id, query, top_k=5)

    # ── 3. Archival storage — search Tier 3 ─────────────────────────────────
    print("[build_context] step=archival_search")
    archival = ArchivalStorage(archival_db)
    archival.seed_defaults()   # no-op if already seeded

    archival_hits   = archival.search(query, record_type="incident",      top_k=archival_top_k)
    patch_patterns  = archival.search(query, record_type="patch_pattern", top_k=2)
    file_history    = archival.get_by_file(affected_file) if affected_file else []

    print(f"[archival] hits={len(archival_hits)}  patterns={len(patch_patterns)}")

    # Surface any archival match as an initial hypothesis
    if archival_hits:
        top = archival_hits[0]
        h   = Hypothesis(
            description=(
                f"Based on past incident '{top['title']}': "
                f"{top['root_cause']}"
            ),
            confidence=round(top.get("score", 0.5) * 0.9, 2),
            evidence_for=[
                f"Archival match: {top['record_id']} (score={top.get('score',0):.2f})",
                f"Same error class: {error_class}",
            ],
        )
        wc.add_hypothesis(h)
        print(f"[working_context] seeded hypothesis from archival: conf={h.confidence}")

    # ── 4. Code graph — expand from error site ───────────────────────────────
    print("[build_context] step=code_graph")
    graph     = CodeGraph.build(repo_path)
    graph_ctx = graph.expand(
        error_function=affected_fn   or error_class,
        error_file=    affected_file or "",
        depth=2,
    )

    # Attach function source for the error site
    if affected_fn and affected_file:
        source = graph.get_function_source(repo_path, affected_file, affected_fn)
        graph_ctx["error_function_source"] = source

    print(f"[code_graph] callers={len(graph_ctx['callers'])}  "
          f"callees={len(graph_ctx['callees'])}  "
          f"tests={len(graph_ctx['covering_tests'])}")

    # ── 5. RAG retrieval ─────────────────────────────────────────────────────
    print("[build_context] step=rag_retrieval")
    rag_chunks = _rag_retrieve(incident, repo_path, top_k=rag_top_k)
    print(f"[rag] retrieved {len(rag_chunks)} chunks")

    # ── 6. Domain constraints ────────────────────────────────────────────────
    constraints = _load_domain_constraints(incident, repo_path)
    print(f"[constraints] loaded {len(constraints)} domain rules")

    # ── 7. Write seed recall entry ───────────────────────────────────────────
    recall.write(RecallEntry(
        incident_id=incident_id,
        agent="context_builder",
        content=(
            f"Context built for {incident_id}. "
            f"Archival hits: {len(archival_hits)}. "
            f"RAG chunks: {len(rag_chunks)}. "
            f"Graph: callers={graph_ctx['callers']}, "
            f"tests={graph_ctx['covering_tests']}. "
            f"Initial hypothesis: {wc.active_hypothesis.description[:120] if wc.active_hypothesis else 'none'}"
        ),
        tags=["context_built", "initial"],
    ))

    # ── 8. Assemble output ───────────────────────────────────────────────────
    wc_dict   = wc.to_dict()
    full_text = json.dumps(wc_dict) + json.dumps(archival_hits) + json.dumps(rag_chunks)

    context = {
        "incident_id":        incident_id,
        "incident":           incident,

        # Tier 1 — working context
        "working_context":    wc_dict,

        # Tier 2 — recall (session log for this incident)
        "recall_hits":        recall_hits,

        # Tier 3 — archival (past RCAs and fix patterns)
        "archival_hits":      archival_hits,
        "patch_patterns":     patch_patterns,
        "file_history":       file_history,

        # Code graph expansion
        "code_graph":         graph_ctx,
        "graph_summary":      graph.summary(),

        # RAG code chunks
        "rag_chunks":         rag_chunks,

        # Domain constraints
        "domain_constraints": constraints,

        # Meta
        "context_summary": {
            "archival_hits":    len(archival_hits),
            "recall_hits":      len(recall_hits),
            "rag_chunks":       len(rag_chunks),
            "patch_patterns":   len(patch_patterns),
            "constraints":      len(constraints),
            "has_hypothesis":   wc.active_hypothesis is not None,
            "token_estimate":   _estimate_tokens(full_text),
        },
    }

    return context


# ── CLI runner ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    parser = argparse.ArgumentParser(description="DebugFlow context builder")
    parser.add_argument("--incident", required=True, help="path to incident JSON")
    parser.add_argument("--repo",     default=".",   help="repo root path")
    parser.add_argument("--out",      default=None,  help="output file for context JSON")
    parser.add_argument("--mode", default="debugflow")
    args = parser.parse_args()

    incident = json.loads(Path(args.incident).read_text())
    ctx      = build_context(incident, repo_path=args.repo)

    output = json.dumps(ctx, indent=2)
    if args.out:
        Path(args.out).write_text(output)
        print(f"\nContext written to {args.out}")
    else:
        print(output)
