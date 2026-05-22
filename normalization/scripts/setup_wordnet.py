from __future__ import annotations

import argparse
import os
from pathlib import Path

import nltk


REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_NLTK_DATA = REPO_ROOT / "data" / "wordnet"
REQUIRED_PACKAGES = ("wordnet", "omw-1.4")


def ensure_wordnet(local_dir: Path) -> None:
    local_dir.mkdir(parents=True, exist_ok=True)
    os.environ["NLTK_DATA"] = str(local_dir)
    nltk.data.path[:] = [str(local_dir)]

    for package in REQUIRED_PACKAGES:
        if _is_package_available(package):
            print(f"[ok] {package} already present in {local_dir}")
            continue
        print(f"[download] {package} -> {local_dir}")
        nltk.download(package, download_dir=str(local_dir), quiet=False, raise_on_error=True)

    # verify after download
    for package in REQUIRED_PACKAGES:
        if not _is_package_available(package):
            raise RuntimeError(f"Failed to verify NLTK package: {package}")
    print("[done] WordNet data ready.")


def _is_package_available(package: str) -> bool:
    candidates = [
        f"corpora/{package}",
        f"corpora/{package}.zip",
    ]
    for lookup_key in candidates:
        try:
            nltk.data.find(lookup_key)
            return True
        except LookupError:
            continue
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Download WordNet corpora to repo-local data/wordnet.")
    parser.add_argument(
        "--dir",
        dest="directory",
        default=str(LOCAL_NLTK_DATA),
        help="Target NLTK data directory (default: ./data/wordnet).",
    )
    args = parser.parse_args()
    ensure_wordnet(Path(args.directory).resolve())


if __name__ == "__main__":
    main()
