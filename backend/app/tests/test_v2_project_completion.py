from datetime import datetime, timezone

import pytest

from app.errors import AppError
from app.models import Document, Project
from app.services.requirements import create_requirement
from app.v2.project_completion import LIMIT, completion_candidates, get_person
from app.tests.conftest import login


def test_people_include_active_inherited_agents_visible_to_project_viewers(db, world):
    project = world["project"]
    member = world["member"]
    agent = world["agent"]
    agent.nickname = "同名"
    world["agent_owner"].nickname = agent.nickname
    db.commit()

    items = completion_candidates(db, member, project.id, "people", "同名")
    assert {(row["id"], row["kind"]) for row in items} == {
        (str(agent.id), "agent"),
        (str(world["agent_owner"].id), "member"),
    }
    assert get_person(db, member, project.id, agent.id)["href"] == f"/projects/{project.id}/people/{agent.id}"

    world["agent_owner"].deleted_at = datetime.now(timezone.utc)
    db.commit()
    assert completion_candidates(db, member, project.id, "people", "同名") == []
    with pytest.raises(AppError) as error:
        get_person(db, member, project.id, agent.id)
    assert error.value.code == "not_found"


def test_reference_candidates_limit_and_skip_same_short_codes_in_other_projects(db, world):
    project = world["project"]
    other = Project(team_id=project.team_id, name="其他项目")
    db.add(other)
    db.commit()
    rid = create_requirement(db, world["admin"], project.id, "活动需求").code
    assert create_requirement(db, world["admin"], other.id, "其他项目需求").code == rid
    db.add_all([
        Document(project_id=project.id, code=f"DOC-{i}", title=f"发布手册 {i:02}", doc_type="wiki")
        for i in range(1, LIMIT + 3)
    ])
    db.add(Document(project_id=other.id, code="DOC-1", title="不应被找到", doc_type="wiki"))
    db.commit()

    items = completion_candidates(db, world["member"], project.id, "reference", "DOC-")
    assert len(items) == LIMIT
    assert all(row["href"] == f"/projects/{project.id}/wiki/{row['id']}" for row in items)
    matches = completion_candidates(db, world["member"], project.id, "reference", rid)
    assert [row["label"] for row in matches] == ["活动需求"]
    with pytest.raises(AppError) as error:
        completion_candidates(db, world["member"], other.id, "reference", rid)
    assert error.value.code == "not_found"


def test_http_completion_uses_existing_viewer_scope(client, world):
    project = world["project"]
    route = f"/api/projects/{project.id}"
    assert client.get(f"{route}/completions?mode=people").status_code == 401
    login(client, "admin", "admin-pass-1")
    response = client.get(f"{route}/completions?mode=people&q=agent-a")
    assert response.status_code == 200
    [person] = response.json()["items"]
    assert person["kind"] == "agent"
    assert client.get(f"{route}/people/{person['id']}").json() == person
