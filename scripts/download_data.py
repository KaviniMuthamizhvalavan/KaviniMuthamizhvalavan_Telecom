"""Download the full 5G NetOps dataset (public, Apache-2.0) from the PRD's primary Hugging Face link.

Run from the repo root:  python -m scripts.download_data [--force]
"""
import argparse
import hashlib
import sys

import requests

from src.rag.data_loader import RAW_DIR
from src.utils.net import use_system_certificates
from src.utils.schema import DATASET_FILENAME, DATASET_URL


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="re-download even if the file exists")
    args = parser.parse_args()

    use_system_certificates()
    target = RAW_DIR / DATASET_FILENAME
    if target.exists() and not args.force:
        print(f"Already present: {target} ({target.stat().st_size:,} bytes). Use --force to re-download.")
        return
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".part")
    print(f"Downloading {DATASET_URL}")
    with requests.get(DATASET_URL, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        sha = hashlib.sha256()
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
                sha.update(chunk)
    tmp.replace(target)
    print(f"Saved {target} ({target.stat().st_size:,} bytes, sha256 {sha.hexdigest()[:16]}...)")


if __name__ == "__main__":
    sys.exit(main())
