import pytest

from deepvista_cli.output.formatter import set_project_ref_resolver


@pytest.fixture(autouse=True)
def _reset_project_ref_resolver():
    yield
    set_project_ref_resolver(None)
