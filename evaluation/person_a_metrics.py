import json
import argparse


EXPECTED_ROOT_CAUSES = {
    "INC-DUP-001": "bugs/duplicate_event_pipeline.py",
    "INC-BQ-002": "bugs/bq_cost_query.py",
}


def collect_files(context):
    files = set()

    # RAG chunks
    for chunk in context.get("rag_chunks", []):
        if isinstance(chunk, dict):
            file_name = chunk.get("file")
            if file_name:
                files.add(file_name)

    # Code graph
    code_graph = context.get("code_graph", {})

    for key in ["callers", "callees", "covering_tests"]:
        for item in code_graph.get(key, []):
            if isinstance(item, dict):
                file_name = item.get("file")
                if file_name:
                    files.add(file_name)
            elif isinstance(item, str):
                files.add(item)

    # Error file from graph if present
    if code_graph.get("error_file"):
        files.add(code_graph["error_file"])

    # Incident affected file
    incident = context.get("incident", {})
    if incident.get("affected_file"):
        files.add(incident["affected_file"])

    return files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    with open(args.context, "r") as f:
        context = json.load(f)

    incident_id = context.get("incident_id")
    expected_root = EXPECTED_ROOT_CAUSES.get(incident_id)

    retrieved_files = collect_files(context)

    root_cause_found = (
        expected_root in retrieved_files if expected_root else False
    )

    code_graph = context.get("code_graph", {})

    metrics = {
        "incident_id": incident_id,
        "expected_root_cause_file": expected_root,
        "root_cause_file_retrieved": root_cause_found,
        "num_rag_chunks": len(context.get("rag_chunks", [])),
        "num_graph_callers": len(code_graph.get("callers", [])),
        "num_graph_callees": len(code_graph.get("callees", [])),
        "num_tests": len(code_graph.get("covering_tests", [])),
        "num_constraints": len(context.get("domain_constraints", [])),
        "num_recall_hits": len(context.get("recall_hits", [])),
        "num_archival_hits": len(context.get("archival_hits", [])),
        "num_patch_patterns": len(context.get("patch_patterns", [])),
        "retrieved_files": sorted(retrieved_files),
    }

    if args.out:
        with open(args.out, "w") as f:
            json.dump(metrics, f, indent=2)
        print(f"[saved] metrics -> {args.out}")
    else:
        print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
