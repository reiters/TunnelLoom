from __future__ import annotations

from .backend import SoftEtherBackend
from .config import load_config


def main() -> int:
    config = load_config()
    backend = SoftEtherBackend(config)

    print("Testing the same privileged launch path used by the GUI...")
    print("A graphical administrator-password prompt should appear.")
    print(f"Launch directory: {backend.softether_dir or '(not set)'}")
    print("Executable argument used by helper: ./vpncmd")
    print("SoftEther command: AccountList")

    try:
        backend.validate()
        result = backend._run_batch(["AccountList"], timeout=20, secrets=())
    except Exception as exc:
        print(f"Probe could not run vpncmd: {exc}")
        return 1
    finally:
        backend.close()

    print(f"Return code: {result.returncode}")
    if result.output.strip():
        print("--- stdout/output file ---")
        print(result.output.rstrip())
    if result.stderr.strip():
        print("--- stderr ---")
        print(result.stderr.rstrip())
    return 0 if result.returncode == 0 else result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
