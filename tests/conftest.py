"""Shared test fixture: a small simulator dataset in a temp folder."""

import pytest

from cloudsleuth_zeroth.simulator.generate import generate


@pytest.fixture(scope="session")
def small_dataset(tmp_path_factory):
    out = tmp_path_factory.mktemp("sim data")      # note: a space in the path on purpose
    generate(out, cases_per_kind=2, normal_cases=2, seed=7)
    return out
