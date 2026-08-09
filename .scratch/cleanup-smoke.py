"""清理冒烟测试残留数据:smoke agent + 冒烟需求(经 API 正规删除)。"""

import httpx

API = "http://localhost:8001"
PUREMI_PASSWORD = "123456789"


def main():
    api = httpx.Client(base_url=API, timeout=30)
    r = api.post("/api/auth/login", json={"username": "puremi", "password": PUREMI_PASSWORD})
    assert r.status_code == 200, r.text

    # 删需求(软删)
    for p in api.get("/api/projects").json():
        pid = p["id"]
        for req in api.get(f"/api/projects/{pid}/requirements").json().get("items", []):
            if "冒烟" in req["title"]:
                rr = api.post(f"/api/requirements/{req['id']}/delete", json={"confirm_task_count": 0})
                print(f"delete requirement {req['title']}: HTTP {rr.status_code}")

    # 删 smoke agent
    for a in api.get("/api/agents").json():
        if a["username"].startswith("smoke"):
            rr = api.delete(f"/api/agents/{a['id']}")
            print(f"delete agent {a['username']}: HTTP {rr.status_code}")


if __name__ == "__main__":
    main()
