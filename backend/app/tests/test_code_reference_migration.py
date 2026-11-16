"""API reference module removal: model/migration package no longer exists."""

import importlib.util


def test_code_reference_model_module_is_removed():
    assert importlib.util.find_spec("app.models.code_reference") is None
