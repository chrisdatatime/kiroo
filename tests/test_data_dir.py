"""Nada persistente fora de STUDIO_DATA_DIR"""
from .backup_common import *  # noqa: F401,F403
from .backup_common import _clean_backup_env  # noqa: F401
from .test_accounts import app  # noqa: F401


# ------------------------------------------------------------------ nada persistente fora de STUDIO_DATA_DIR
def test_no_persistent_sink_outside_data_dir_in_source():
    """Auditoria estática: o app não usa tempfile/tmp nem grava em home/cwd. Se alguém acrescentar, este teste obriga a documentar."""
    banned = re.compile(r"\btempfile\b|gettempdir|mkdtemp|/tmp/|\"/var/|expanduser\(\s*[\"']~")
    hits = []
    for f in (ROOT / "src" / "studio").rglob("*.py"):
        if f.name == "migrations.py":
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if banned.search(line) and "os.environ" not in line:
                hits.append(f"{f.relative_to(ROOT)}:{n}: {line.strip()[:90]}")
    # product_prep lê um caminho informado pelo usuário (expanduser só para LER); nenhuma gravação.
    assert [h for h in hits if "product_prep.py" not in h] == []


def test_all_persistent_paths_derive_from_data_dir(settings):
    from studio.logs import setup_logging
    import logging
    data = settings.data_dir.resolve()
    assert settings.db_path.resolve().parent == data
    setup_logging(settings.data_dir / "logs", [])
    try:
        logfile = [h.baseFilename for h in logging.getLogger("studio").handlers if hasattr(h, "baseFilename")]
        assert logfile and all(Path(p).resolve().is_relative_to(data) for p in logfile)
    finally:
        logging.getLogger("studio").handlers.clear()
    lock = runtime.acquire_instance_lock(settings.data_dir)
    try:
        assert (data / runtime.LOCK_NAME).exists()
    finally:
        runtime.release_instance_lock(lock)


