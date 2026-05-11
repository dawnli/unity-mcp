import hashlib
import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_SCRIPT = REPO_ROOT / "unity-mcp-skill" / "scripts" / "project_path_hash.py"
CLAUDE_SCRIPT = (
    REPO_ROOT
    / ".claude"
    / "skills"
    / "unity-mcp-skill"
    / "scripts"
    / "project_path_hash.py"
)


def _load_script(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_project_path_hash_normalizes_absolute_assets_path(tmp_path):
    script = _load_script(ROOT_SCRIPT, "root_project_path_hash")

    raw_path = f"{tmp_path}\\MyGame\\Assets\\"
    tmp_normalized = str(tmp_path).replace("\\", "/").rstrip("/")
    expected_normalized = f"{tmp_normalized}/mygame".lower()
    expected_hash = hashlib.sha256(expected_normalized.encode("utf-8")).hexdigest()[:24]

    assert script.normalize_project_root(raw_path) == expected_normalized
    assert script.project_path_hash(raw_path) == expected_hash


def test_project_path_hash_requires_absolute_path():
    script = _load_script(ROOT_SCRIPT, "root_project_path_hash_relative")

    with pytest.raises(SystemExit):
        script.normalize_project_root("Relative/UnityProject")


def test_claude_skill_script_matches_root_skill_script(tmp_path):
    root_script = _load_script(ROOT_SCRIPT, "root_project_path_hash_match")
    claude_script = _load_script(CLAUDE_SCRIPT, "claude_project_path_hash_match")

    raw_path = f"{tmp_path}/MixedCaseProject/Assets/"

    assert claude_script.normalize_project_root(raw_path) == root_script.normalize_project_root(raw_path)
    assert claude_script.project_path_hash(raw_path) == root_script.project_path_hash(raw_path)
