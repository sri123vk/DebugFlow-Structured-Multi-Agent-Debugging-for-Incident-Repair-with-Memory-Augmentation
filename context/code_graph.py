"""
context/code_graph.py
──────────────────────
Code graph builder for the DebugFlow toy repo.

Uses Python's built-in `ast` module — no Tree-sitter needed for
a small Python codebase.

Builds a graph with:
  Nodes  — files, classes, functions, tests
  Edges  — calls, imports, defines, tested_by

Given an incident (error_class, affected_function, affected_file),
expands outward from the error site:
  • callers  — functions that call the error function
  • callees  — functions the error function calls
  • tests    — test functions that import or test the affected file
  • imports  — names imported by the affected file

Returns a graph dict that the context builder packages for Person B.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── AST helpers ───────────────────────────────────────────────────────────────

def _parse_file(path: Path) -> Optional[ast.Module]:
    try:
        return ast.parse(path.read_text(), filename=str(path))
    except SyntaxError:
        return None


def _get_functions(tree: ast.Module, file_path: str) -> list[dict]:
    """Extract all function definitions with their source lines."""
    functions = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append({
                "name":        node.name,
                "file":        file_path,
                "lineno":      node.lineno,
                "end_lineno":  getattr(node, "end_lineno", node.lineno),
                "args":        [a.arg for a in node.args.args],
            })
    return functions


def _get_calls(tree: ast.Module) -> list[str]:
    """Extract all function/method call names from a module."""
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.append(node.func.attr)
    return list(set(calls))


def _get_imports(tree: ast.Module) -> list[str]:
    """Extract imported names."""
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imports.extend(f"{module}.{alias.name}" for alias in node.names)
            imports.extend(alias.name for alias in node.names)
    return list(set(imports))


def _extract_function_source(path: Path, func_name: str) -> Optional[str]:
    """Extract the source code of a specific function."""
    try:
        source = path.read_text()
        tree   = ast.parse(source)
        lines  = source.splitlines()
        for node in ast.walk(tree):
            if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == func_name):
                start = node.lineno - 1
                end   = getattr(node, "end_lineno", node.lineno)
                return "\n".join(lines[start:end])
    except Exception:
        pass
    return None


# ── Graph builder ─────────────────────────────────────────────────────────────

@dataclass
class CodeGraph:
    """
    In-memory code graph for the toy repo.
    Built once, queried per incident.
    """
    # file → list of functions defined in it
    file_functions:  dict[str, list[dict]] = field(default_factory=dict)
    # file → list of function names called
    file_calls:      dict[str, list[str]]  = field(default_factory=dict)
    # file → list of imported names
    file_imports:    dict[str, list[str]]  = field(default_factory=dict)
    # function name → list of files that call it
    callers_of:      dict[str, list[str]]  = field(default_factory=dict)
    # test file → list of files it imports
    test_covers:     dict[str, list[str]]  = field(default_factory=dict)

    @classmethod
    def build(cls, repo_path: str) -> "CodeGraph":
        """
        Scan all Python files under repo_path and build the graph.
        """
        graph    = cls()
        repo     = Path(repo_path)
        py_files = list(repo.rglob("*.py"))

        for py_file in py_files:
            rel = str(py_file.relative_to(repo))
            tree = _parse_file(py_file)
            if tree is None:
                continue

            funcs   = _get_functions(tree, rel)
            calls   = _get_calls(tree)
            imports = _get_imports(tree)

            graph.file_functions[rel] = funcs
            graph.file_calls[rel]     = calls
            graph.file_imports[rel]   = imports

            # Build reverse caller map
            for called_fn in calls:
                if called_fn not in graph.callers_of:
                    graph.callers_of[called_fn] = []
                if rel not in graph.callers_of[called_fn]:
                    graph.callers_of[called_fn].append(rel)

            # Track test coverage
            if rel.startswith("tests/") or "test" in rel.lower():
                for imported in imports:
                    imported_file = imported.replace(".", "/") + ".py"
                    graph.test_covers[rel] = graph.test_covers.get(rel, [])
                    graph.test_covers[rel].append(imported)

        return graph

    def expand(
        self,
        error_function: str,
        error_file:     str,
        depth:          int = 2,
    ) -> dict:
        """
        BFS expansion from the error site.
        Returns the structural context an agent needs to localise the bug.
        """
        # Callers — who calls the error function?
        callers = self.callers_of.get(error_function, [])

        # Callees — what does the error file call?
        callees = self.file_calls.get(error_file, [])

        # All functions defined in the error file
        own_functions = [
            f["name"] for f in self.file_functions.get(error_file, [])
        ]

        # Tests that cover the error file
        covering_tests = []
        for test_file, imported_names in self.test_covers.items():
            # Match by module path fragments
            error_module = error_file.replace("/", ".").replace(".py", "")
            base_name    = Path(error_file).stem
            if any(base_name in name or error_module in name
                   for name in imported_names):
                covering_tests.append(test_file)

        # Imports of the error file
        imports = self.file_imports.get(error_file, [])

        # Neighbouring files (files that share callee functions)
        neighbour_files = list({
            f for fn in callees
            for f in self.callers_of.get(fn, [])
            if f != error_file
        })[:5]

        # Recent change hint (static for toy repo — commit a3f9 in bq bug)
        change_hints = []
        if "bq_cost" in error_file:
            change_hints.append("commit a3f9: removed partition filter default (2h ago)")
        if "duplicate" in error_file:
            change_hints.append("commit b72d: changed dedup logic to plain set() (1d ago)")

        return {
            "error_site":       error_function,
            "error_file":       error_file,
            "own_functions":    own_functions,
            "callers":          callers,          # files that call error_function
            "callees":          callees[:10],     # functions the error file calls
            "covering_tests":   covering_tests,   # test files covering error_file
            "imports":          imports[:10],     # names imported by error_file
            "neighbour_files":  neighbour_files,  # files sharing callees
            "change_hints":     change_hints,     # recent git-style hints
        }

    def get_function_source(self, repo_path: str, file_path: str, func_name: str) -> Optional[str]:
        """Retrieve source code of a specific function."""
        full_path = Path(repo_path) / file_path
        return _extract_function_source(full_path, func_name)

    def summary(self) -> dict:
        return {
            "total_files":     len(self.file_functions),
            "total_functions": sum(len(v) for v in self.file_functions.values()),
            "total_call_edges":sum(len(v) for v in self.file_calls.values()),
            "test_files":      len(self.test_covers),
        }
