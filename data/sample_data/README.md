# Sample data

`netops_sample_10k.csv` is a 9,996-row stratified sample of the **5G Network Operations (NetOps) Dataset**, in the original raw CSV format (27 columns, UTF-8).

- **Source:** https://huggingface.co/datasets/fenar/5g_netops (file `5G_netops_data_100K.csv.xz`, 100,000 rows)
- **License:** Apache-2.0 (as declared on the dataset page)
- **Sampling:** about 10% of each primary-category × season stratum, seed 42, built by `python -m scripts.make_sample`. Per-stratum rounding gives 9,996 rows. Category shares match the full data within 0.01 percentage points.
- **Purpose:** lets the project run quickly without the full download (`python -m src.rag.preprocessing --source sample`). The full dataset is downloaded by `python -m scripts.download_data` into `data/raw/` (not committed).

The data is synthetic (Faker-style city names, mostly uniform distributions). See `docs/assets/eda/` for the measured profile.
