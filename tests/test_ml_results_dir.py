"""ML training writes the published results (evaluation/results/final/ml) only for the full dataset in the project's own
artifacts folder; sample or scratch builds keep theirs next to their artifacts (bug fix, 2026-10-09)."""
from src.services.ml.train import FINAL_RESULTS_DIR, results_dir
from src.utils.config import PROJECT_ROOT, Settings


def test_full_dataset_in_project_artifacts_writes_published_results():
    s = Settings(_env_file=None, data_source="full", artifacts_dir=PROJECT_ROOT / "artifacts")
    assert results_dir(s) == FINAL_RESULTS_DIR


def test_sample_build_never_writes_published_results(tmp_path):
    assert results_dir(Settings(_env_file=None, data_source="sample", artifacts_dir=tmp_path)) == tmp_path / "ml_results"
    project = Settings(_env_file=None, data_source="sample", artifacts_dir=PROJECT_ROOT / "artifacts")
    assert results_dir(project) != FINAL_RESULTS_DIR


def test_full_build_in_a_scratch_folder_never_writes_published_results(tmp_path):
    assert results_dir(Settings(_env_file=None, data_source="full", artifacts_dir=tmp_path)) == tmp_path / "ml_results"
