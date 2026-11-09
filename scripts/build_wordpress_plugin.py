"""Build the installable plugin from canonical sources, with deterministic ZIP metadata."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "woo-rag-auth.php": ROOT / "wordpress/woo-rag-auth.php",
    "woo-rag-admin.php": ROOT / "wordpress/woo-rag-admin.php",
    "widget/chat.js": ROOT / "widget/chat.js",
    "readme.txt": ROOT / "wordpress/readme.txt",
}


def build(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, source in sorted(FILES.items()):
            info = ZipInfo("woo-rag-assistant/" + name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, source.read_bytes(), compresslevel=9)


if __name__ == "__main__":
    build(ROOT / "dist/woo-rag-assistant.zip")
