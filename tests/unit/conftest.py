"""Initialize OpsMesh driver and reset global singletons between tests."""

import opsmesh
import pytest

from qq_admin import MANAGER, Config, reset_modules

try:
    opsmesh.get_driver()
except ValueError:
    opsmesh.init()


@pytest.fixture(autouse=True)
def _clean_singletons() -> None:
    MANAGER.setup(Config())
    reset_modules()
