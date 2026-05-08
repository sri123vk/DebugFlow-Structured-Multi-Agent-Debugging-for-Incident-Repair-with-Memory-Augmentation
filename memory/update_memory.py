import json
import os


RECALL_PATH = "memory/recall.json"


def load_recall_memory():
    if not os.path.exists(RECALL_PATH):
        return []

    with open(RECALL_PATH, "r") as f:
        return json.load(f)


def save_recall_memory(memory):
    with open(RECALL_PATH, "w") as f:
        json.dump(memory, f, indent=2)


def store_verified_incident(
    incident,
    patch_summary,
    verification_result
):
    # Store only successful repairs
    if not verification_result.get("passed", False):
        print("[memory] verification failed -> not storing")
        return

    memory = load_recall_memory()

    entry = {
        "incident_id": incident["incident_id"],
        "description": incident["description"],
        "patch_summary": patch_summary,
        "tests_passed": verification_result.get("tests_passed", 0),
        "constraint_violations": verification_result.get(
            "constraint_violations",
            []
        )
    }

    memory.append(entry)

    save_recall_memory(memory)

    print(f"[memory] stored verified incident: {incident['incident_id']}")
