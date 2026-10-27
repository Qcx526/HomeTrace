"""Backward-compatible CLI for the packaged owner-statement memory module."""
import sys

from hometrace.household_memory import HouseholdMemory, MemoryContractError, main

__all__ = ["HouseholdMemory", "MemoryContractError", "main"]


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
