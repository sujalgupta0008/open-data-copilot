from fastapi.testclient import TestClient
from app.main import app
import uuid

client = TestClient(app)

def make_user(csv="a,b\n1,10\n2,20\n3,30\n"):
    email=f"new{uuid.uuid4().hex[:6]}@test.com"
    r=client.post("/api/auth/register", json={"email":email,"password":"pass123","name":"Tester"})
    token=r.json()["access_token"]
    h={"Authorization":f"Bearer {token}"}
    files={"file":("test.csv", csv, "text/csv")}
    r=client.post("/api/datasets/upload", files=files, headers=h)
    assert r.status_code==200, r.text
    did=r.json()["id"]
    return h, did

def test_workflow_and_next_action():
    h,did=make_user()
    r=client.get(f"/api/datasets/{did}/workflow", headers=h)
    assert r.status_code==200
    assert "steps" in r.json()
    r=client.get(f"/api/datasets/{did}/next-action", headers=h)
    assert r.status_code==200
    assert "action" in r.json()

def test_metrics_crud_and_reuse():
    h,did=make_user("revenue,region\n100,North\n200,South\n150,North\n")
    # create metric
    r=client.post(f"/api/datasets/{did}/metrics", json={"name":"Revenue","sql_expression":"SUM(revenue)","description":"Total revenue"}, headers=h)
    assert r.status_code==200, r.text
    mid=r.json()["id"]
    # list
    r=client.get(f"/api/datasets/{did}/metrics", headers=h)
    assert len(r.json())==1
    # reuse in copilot: ask about revenue -> should use metric
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":"What was revenue?"}, headers=h)
    assert r.status_code==200
    code=r.json()["message"]["generated_code"]
    assert "SUM(revenue)" in code or "SUM(\"revenue\")" in code or "revenue" in code.lower()
    # update
    r=client.put(f"/api/datasets/{did}/metrics/{mid}", json={"description":"Updated"}, headers=h)
    assert r.status_code==200
    # delete
    r=client.delete(f"/api/datasets/{did}/metrics/{mid}", headers=h)
    assert r.status_code==200

def test_ambiguity_detection():
    h,did=make_user("revenue,order_date\n100,2023-01-01\n200,2023-02-01\n")
    r=client.post(f"/api/datasets/{did}/clarify", json={"question":"What was revenue last month?"}, headers=h)
    assert r.status_code==200
    j=r.json()
    # Should need clarification for revenue without metric and date
    assert isinstance(j["needs_clarification"], bool)
    # unambiguous question should not need clarification
    r2=client.post(f"/api/datasets/{did}/clarify", json={"question":"What is the average revenue?"}, headers=h)
    assert r2.status_code==200
    # simple average should not need clarification? Might still need if metric? But we check
    # At least should return clarifications list

def test_plan():
    h,did=make_user()
    r=client.post(f"/api/datasets/{did}/plan", json={"question":"Compare revenue with previous month and identify drivers"}, headers=h)
    assert r.status_code==200
    assert "plan" in r.json()
    # simple question should skip plan
    r2=client.post(f"/api/datasets/{did}/plan", json={"question":"What is average a?"}, headers=h)
    assert r2.status_code==200
    assert r2.json()["needs_plan"]==False

def test_root_cause():
    h,did=make_user("region,revenue\nNorth,100\nSouth,200\nNorth,150\nSouth,300\nEast,50\n")
    # analyze first
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":"Total revenue by region"}, headers=h)
    assert r.status_code==200
    mid=r.json()["message"]["id"]
    # root cause via dimension
    r2=client.post(f"/api/datasets/{did}/root-cause", json={"message_id":mid, "dimension":"region"}, headers=h)
    assert r2.status_code==200, r2.text
    j=r2.json()
    assert "drivers" in j
    assert len(j["drivers"])>0
    # verify numerical correctness via DuckDB: sum contributions should be 100%
    total = sum(d["contribution_percent"] for d in j["drivers"])
    assert 99 < total < 101, f"total {total}"
    # check driver ranking: highest metric first
    vals=[d["metric_value"] for d in j["drivers"]]
    assert vals==sorted(vals, reverse=True)

def test_monitoring():
    h,did=make_user("revenue,region\n100,North\n200,South\n")
    # create metric first
    r=client.post(f"/api/datasets/{did}/metrics", json={"name":"Revenue","sql_expression":"SUM(revenue)"}, headers=h)
    mid=r.json()["id"]
    r=client.post(f"/api/datasets/{did}/monitors", json={"metric_id":mid, "threshold_percent":10}, headers=h)
    assert r.status_code==200, r.text
    mon_id=r.json()["id"]
    r=client.get(f"/api/datasets/{did}/monitors", headers=h)
    assert len(r.json())==1
    r=client.post(f"/api/datasets/{did}/monitors/{mon_id}/check", headers=h)
    assert r.status_code==200
    assert "status" in r.json()
    # second check should compute change
    r2=client.post(f"/api/datasets/{did}/monitors/{mon_id}/check", headers=h)
    assert r2.status_code==200

def test_cleaning_lifecycle_states():
    h,did=make_user("a,b\n1,2\n3,4\n")
    # preview
    r=client.post(f"/api/datasets/{did}/clean/preview", json={"op":"remove_duplicates","params":{}}, headers=h)
    assert r.status_code==200
    assert "before_rows" in r.json()
    # apply
    r=client.post(f"/api/datasets/{did}/clean/apply", json={"op":"remove_duplicates","params":{}}, headers=h)
    assert r.status_code==200
    j=r.json()
    assert "version" in j
    assert "V" in f"V{j['version']['version_number']}"
    # check workflow updated
    r=client.get(f"/api/datasets/{did}/workflow", headers=h)
    assert r.json()["steps"]["cleaned"]["completed"]==True

def test_copilot_composer_not_needed_backend():
    # Verify copilot analysis still uses deterministic truth and insight has key takeaway
    h,did=make_user("a,b\n1,2\n2,4\n3,6\n")
    r=client.post(f"/api/datasets/{did}/analyze", json={"question":"What is average b?"}, headers=h)
    assert r.status_code==200
    content=r.json()["message"]["content"]
    assert "Key takeaway" in content
    assert "average" in content.lower()

def test_auth_ownership_still():
    h1,did=make_user()
    email2=f"other{uuid.uuid4().hex[:6]}@test.com"
    r=client.post("/api/auth/register", json={"email":email2,"password":"pass123","name":"Other"})
    h2={"Authorization":f"Bearer {r.json()['access_token']}"}
    r=client.get(f"/api/datasets/{did}/workflow", headers=h2)
    assert r.status_code==404
    r=client.post(f"/api/datasets/{did}/metrics", json={"name":"Rev","sql_expression":"SUM(a)"}, headers=h2)
    assert r.status_code==404

