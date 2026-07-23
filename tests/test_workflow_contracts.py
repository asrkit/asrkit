"""关键 GitHub Actions 契约的快速回归保护。"""
from pathlib import Path

ROOT = Path(__file__).parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

ACTION_REFS = {
    "actions/checkout": "fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09",
    "actions/setup-python": "ece7cb06caefa5fff74198d8649806c4678c61a1",
    "actions/setup-node": "249970729cb0ef3589644e2896645e5dc5ba9c38",
    "actions/upload-artifact": "330a01c490aca151604b8cf639adc76d48f6c5d4",
    "actions/download-artifact": "018cc2cf5baa6db3ef3c5f8a56943fffe632ef53",
    "pypa/gh-action-pypi-publish": "ba38be9e461d3875417946c167d0b5f3d385a247",
}


def test_actions_are_node24_generation_and_sha_pinned() -> None:
    for workflow in WORKFLOWS.glob("*.yml"):
        text = workflow.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "uses:" not in line:
                continue
            action, ref = line.split("uses:", 1)[1].strip().split()[0].rsplit("@", 1)
            assert action in ACTION_REFS, f"unreviewed action in {workflow.name}: {action}"
            assert ref == ACTION_REFS[action], f"unpinned or stale action in {workflow.name}: {line}"


def test_official_sdk_contract_is_exact_and_non_optional() -> None:
    workflow = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert '"openai==2.47.0"' in workflow
    assert "npm ci --prefix e2e/openai-node --ignore-scripts" in workflow
    assert "python e2e/test_openai_python_sdk.py" in workflow
    assert "node e2e/openai-node/contract.mjs" in workflow
    assert "continue-on-error" not in workflow
    package = (ROOT / "e2e" / "openai-node" / "package.json").read_text(encoding="utf-8")
    assert '"openai": "6.48.0"' in package


def test_cloud_e2e_is_manual_protected_and_hard_failing() -> None:
    workflow = (WORKFLOWS / "cloud-e2e.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    for automatic_trigger in ("pull_request:", "push:", "schedule:"):
        assert automatic_trigger not in workflow
    assert "environment: cloud-e2e" in workflow
    assert "DASHSCOPE_API_KEY: ${{ secrets.DASHSCOPE_API_KEY }}" in workflow
    assert "SILICONFLOW_API_KEY: ${{ secrets.SILICONFLOW_API_KEY }}" in workflow
    assert "secrets.token_urlsafe(32)" in workflow
    assert "export ASRKIT_GATEWAY_TOKEN" in workflow
    assert "python e2e/test_cloud_providers.py" in workflow
    assert "continue-on-error" not in workflow
    runner = (ROOT / "e2e" / "test_cloud_providers.py").read_text(encoding="utf-8")
    assert "pytest.skip" not in runner
    assert "importorskip" not in runner


def test_release_distinguishes_github_and_pypi_availability() -> None:
    workflow = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    assert "gh release view" in workflow
    assert "Verify version is available on PyPI" in workflow
    assert "https://pypi.org/pypi/asrkit/$version/json" in workflow
