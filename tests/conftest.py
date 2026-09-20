import pytest

from cua.execution.policy import Policy
from test_environment import DEFAULT_POLICY
from test_environment.app import reset
from test_environment.contract import development_capability
from test_environment.server import LabServer


@pytest.fixture(scope="session")
def server(tmp_path_factory):
    with LabServer(tmp_path_factory.mktemp("lab") / "bank.sqlite3") as lab:
        yield lab


@pytest.fixture
def lab(server):
    reset(server.database)
    return server


@pytest.fixture
def policy(lab):
    result = Policy.load(DEFAULT_POLICY)
    result.origins = [lab.url]
    return result


@pytest.fixture
def capability():
    return development_capability()
