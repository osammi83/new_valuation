from __future__ import annotations

import argparse

from sync_universe_master import main as sync_main


def main() -> None:
    sync_main()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync assumptions.csv with universe.csv")
    _ = parser.parse_args()
    main()
