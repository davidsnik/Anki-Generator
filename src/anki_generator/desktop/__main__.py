"""Support Python and PyInstaller spawn before importing the application stack."""

import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from anki_generator.desktop.main import main

    raise SystemExit(main())
