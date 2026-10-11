"""Build every data artifact in order (plan §2.3, §7.1).

Run from the repo root:
  python -m scripts.bootstrap --source full      # download if needed, about 15-25 min on CPU
  python -m scripts.bootstrap --source sample    # committed 10k sample, a few minutes
Steps: download -> preprocess/label -> train ML (+ out-of-fold risk) -> prioritize -> index cases -> index KB.
Use --rebuild to re-embed even when cached embeddings exist.
"""
import argparse
import logging
import os
import time

from src.utils.net import use_system_certificates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["full", "sample"], default=None)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    use_system_certificates()
    if args.source:
        os.environ["DATA_SOURCE"] = args.source  # settings are read after this point

    from src.rag import preprocessing
    from src.rag.data_loader import RAW_DIR
    from src.rag.ingest import ingest_cases
    from src.services import prioritization
    from src.services.ml import train
    from src.utils.config import get_settings
    from src.utils.schema import DATASET_FILENAME

    s = get_settings()
    t0 = time.perf_counter()
    if s.data_source == "full" and not (RAW_DIR / DATASET_FILENAME).exists():
        from scripts import download_data
        import sys
        sys.argv = [sys.argv[0]]
        download_data.main()
    step = lambda name: logging.info("==> %s (%.0fs elapsed)", name, time.perf_counter() - t0)  # noqa: E731

    step(f"preprocess ({s.data_source})")
    preprocessing.build(s.data_source)
    step("train ML models")
    train.main()
    step("prioritize cases")
    prioritization.main()
    step("index cases (embeddings, Chroma, BM25)")
    info = ingest_cases(rebuild=args.rebuild)
    logging.info("cases indexed: %s", info)
    try:
        from src.rag.ingest import ingest_kb
    except ImportError:
        ingest_kb = None
    if ingest_kb is not None:
        step("index knowledge base")
        logging.info("kb indexed: %s", ingest_kb())
    step("done")


if __name__ == "__main__":
    main()
