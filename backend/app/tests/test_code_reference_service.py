"""API reference module removal: service package no longer exists."""

import importlib.util


def test_code_reference_service_module_is_removed():
    assert importlib.util.find_spec("app.services.code_reference") is None
