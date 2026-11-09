"""Minimal frozen entry, including safe multiprocessing re-entry."""

if __name__ == "__main__":
    from multiprocessing import freeze_support

    freeze_support()

    from anki_generator.desktop.main import main

    raise SystemExit(main())
