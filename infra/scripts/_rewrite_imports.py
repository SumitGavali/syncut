"""One-shot import rewriter after package migration. Run from repo root."""
from pathlib import Path
import re

REPLACEMENTS = [
    (r"from config import", "from synccut.config import"),
    (r"from paths import", "from synccut.paths import"),
    (r"from sync_engine import", "from synccut.core.sync_engine import"),
    (r"from drift import", "from synccut.core.drift import"),
    (r"from confidence import", "from synccut.core.confidence import"),
    (r"from robustness import", "from synccut.core.robustness import"),
    (r"from camera_switch import", "from synccut.core.camera_switch import"),
    (r"from rough_cut import", "from synccut.ai.rough_cut import"),
    (r"from extract import", "from synccut.media.extract import"),
    (r"from timeline_builder import", "from synccut.export.timeline_builder import"),
    (r"from fcp7_exporter import", "from synccut.export.fcp7_exporter import"),
    (r"from export_switch_timeline import", "from synccut.export.switch_timeline import"),
    (r"from job_manager import", "from synccut.api.job_manager import"),
    (r"import job_manager, db", "from synccut.api import job_manager, db"),
    (r"from db import", "from synccut.api.db import"),
    (r"from app import find_free_port", "from synccut.api.factory import find_free_port"),
    (r"from app import", "from synccut.api.factory import"),
]


def main() -> None:
    roots = [Path("synccut"), Path("tests"), Path("eval"), Path("conftest.py"), Path("app.py")]
    files: list[Path] = []
    for r in roots:
        if r.is_file():
            files.append(r)
        elif r.is_dir():
            files.extend(r.rglob("*.py"))

    for path in files:
        text = path.read_text(encoding="utf-8")
        orig = text
        for pat, repl in REPLACEMENTS:
            text = re.sub(pat, repl, text)
        if text != orig:
            path.write_text(text, encoding="utf-8")
            print(f"updated: {path.as_posix()}")


if __name__ == "__main__":
    main()
