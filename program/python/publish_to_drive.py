from __future__ import annotations

def main() -> None:
    try:
        from upload_to_google_drive import main as upload_main
    except ModuleNotFoundError as exc:
        print(f"[Drive] Skipped: missing dependency ({exc.name}).")
        return

    upload_main()


if __name__ == "__main__":
    main()
