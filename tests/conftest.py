import pytest

from odc.catalog import Catalog


@pytest.fixture(scope="session")
def cat() -> Catalog:
    return Catalog.load()
