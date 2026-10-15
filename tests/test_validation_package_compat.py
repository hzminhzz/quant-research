"""Legacy validation public API remains importable after package migration."""

from src import validation
from src.validation import ValidationContractError, purge_and_embargo
from src.validation.oracle import reconstruct_paths


def test_legacy_and_canonical_exports():
    assert validation.ValidationContractError is ValidationContractError
    assert validation.purge_and_embargo is purge_and_embargo
    assert callable(reconstruct_paths)
