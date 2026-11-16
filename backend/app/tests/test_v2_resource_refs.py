from uuid import UUID

import pytest

from app.errors import AppError
from app.v2.resource_refs import ResourceKind, ResourceRef


PROJECT = UUID("781dc77e-e4ee-4d4a-b1fb-e668244d5ce4")
OTHER_PROJECT = UUID("0228eca9-5cd9-422b-926a-72af64a3d7ef")


def test_same_short_code_keeps_project_scope_and_ignores_anchor_for_identity():
    first = ResourceRef(PROJECT, ResourceKind.WIKI, "DOC-1")
    other = ResourceRef(OTHER_PROJECT, ResourceKind.WIKI, "DOC-1")

    assert ResourceRef.from_markdown_href(first.path + "#section") == first
    assert ResourceRef.from_markdown_href(other.path) == other
    assert first != other


@pytest.mark.parametrize("prefix", ["https://external.example", "//external.example"])
def test_external_link_is_not_an_internal_reference(prefix):
    assert ResourceRef.from_markdown_href(f"{prefix}/projects/{PROJECT}/people/{OTHER_PROJECT}") is None


def test_nested_paths_or_query_strings_do_not_create_internal_references():
    root = f"/projects/{PROJECT}/wiki/DOC-1"

    assert ResourceRef.from_markdown_href(root + "/versions") is None
    assert ResourceRef.from_markdown_href(root + "?project=other") is None


@pytest.mark.parametrize("kind, identifier", [("tasks", "REQ-1"), ("wiki", "DOC-01"), ("files", "DOC-1")])
def test_invalid_known_resource_path_gets_public_error(kind, identifier):
    with pytest.raises(AppError) as caught:
        ResourceRef.from_markdown_href(f"/projects/{PROJECT}/{kind}/{identifier}")

    assert caught.value.code == "invalid_request"
