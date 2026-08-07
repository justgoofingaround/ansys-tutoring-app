"""Build a downloadable desktop-guide bundle for the current tutorial.

The bundle gives testers the guide scripts and tutorial assets without having
to clone the repository from GitHub. It preserves the repo-relative layout so
the downloaded folder can be unzipped and run locally.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from ..config import REPO_ROOT
from . import tutorial_store


_HELPER_FILES = (
    "spikes/guide_tut1.py",
    "spikes/locate.py",
    "spikes/verify.py",
    "spikes/report_verify.py",
    "spikes/README.md",
    "spikes/tessdata/eng.traineddata",
    "tools/register_guide_protocol.py",
    "tools/guide_launcher.py",
    "requirements.txt",
    "mock_server/data/README.md",
)


def _safe_arcname(path: str) -> str:
    return Path(path).as_posix()


def _add_file(zf: zipfile.ZipFile, rel_path: str) -> None:
    file_path = REPO_ROOT / rel_path
    if file_path.is_file():
        zf.write(file_path, _safe_arcname(rel_path))


def _referenced_images(content: dict) -> set[str]:
    images: set[str] = set()
    for section in content.get("sections", []):
        for step in section.get("steps", []):
            source_image = step.get("source_image")
            if isinstance(source_image, str) and source_image.strip():
                images.add(source_image.replace("\\", "/"))
    return images


def build_desktop_guide_bundle(conn, tutorial_id: str) -> tuple[bytes, str, list[str]]:
    found = tutorial_store.get_published(conn, tutorial_id)
    if found is None:
        raise ValueError("tutorial_not_found")
    content, meta = found

    buffer = io.BytesIO()
    missing: list[str] = []

    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "README.txt",
            "This bundle contains the desktop-guide scripts and assets for the "
            f"tutorial '{tutorial_id}'.\n\n"
            "Unzip it anywhere, then run the guide from the extracted folder. "
            "The structure mirrors the repository layout expected by the guide.\n",
        )
        zf.writestr(
            f"mock_server/data/{tutorial_id}.json",
            json.dumps(content, indent=2, ensure_ascii=False),
        )

        for rel_path in _HELPER_FILES:
            _add_file(zf, rel_path)

        for rel_path in sorted(_referenced_images(content)):
            file_path = REPO_ROOT / rel_path
            if file_path.is_file():
                zf.write(file_path, _safe_arcname(rel_path))
            else:
                missing.append(rel_path)

        if missing:
            zf.writestr(
                "MISSING_ASSETS.txt",
                "The tutorial references these image files, but they were not found in the repo:\n"
                + "\n".join(f"- {item}" for item in missing)
                + "\n\nIf the tutorial needs them, add the files to mock_server/data/images/ or "
                "publish a new tutorial version that points at existing assets.\n",
            )

        zf.writestr(
            "bundle-manifest.json",
            json.dumps(
                {
                    "tutorial_id": tutorial_id,
                    "title": meta["title"],
                    "version": meta["latest_published_version"],
                    "helper_files": list(_HELPER_FILES),
                    "missing_assets": missing,
                },
                indent=2,
                ensure_ascii=False,
            ),
        )

    filename = f"{tutorial_id}_desktop_guide_bundle.zip"
    return buffer.getvalue(), filename, missing