import argparse
import json
import os
import subprocess

from context.builder import build_context


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--incident", required=True)
    parser.add_argument("--repo", required=True)

    args = parser.parse_args()

    os.makedirs("outputs", exist_ok=True)

    # Load incident
    with open(args.incident, "r") as f:
        incident = json.load(f)

    # Build context
    context = build_context(
        incident=incident,
        repo_path=args.repo
    )

    incident_id = incident["incident_id"]

    context_out = f"outputs/{incident_id}_context.json"

    with open(context_out, "w") as f:
        json.dump(context, f, indent=2)

    print(f"[saved] context -> {context_out}")

    # Run verifier
    print("[running verifier]")

    result = subprocess.run(
        [
            "python",
            "-m",
            "verifier",
            "--incident",
            args.incident,
            "--repo",
            args.repo
        ],
        capture_output=True,
        text=True
    )

    verification_out = f"outputs/{incident_id}_verification.txt"

    with open(verification_out, "w") as f:
        f.write(result.stdout)
        f.write("\n")
        f.write(result.stderr)

    print(f"[saved] verification -> {verification_out}")


if __name__ == "__main__":
    main()
