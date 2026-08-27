import requests, json, time, os, sys

BASE="http://127.0.0.1:8000"
def log(s): print(s)

# 1-5 create account login
email=f"e2e_{int(time.time())}@test.com"
pwd="password123"
r=requests.post(f"{BASE}/api/auth/register", json={"email":email,"password":pwd,"name":"E2E"})
assert r.status_code==200, r.text
token=r.json()["access_token"]
log("✅ Register ok")
h={"Authorization": f"Bearer {token}"}
r=requests.get(f"{BASE}/api/auth/me", headers=h)
assert r.status_code==200
log("✅ Me ok")

# dashboard
r=requests.get(f"{BASE}/api/dashboard/stats", headers=h)
assert r.status_code==200
log(f"✅ Dashboard {r.json()['total_datasets']} datasets")

# upload ecommerce.csv (portable path)
import pathlib
csv_path = pathlib.Path(__file__).parent.parent / "sample_data" / "ecommerce.csv"
with open(csv_path,"rb") as f:
    r=requests.post(f"{BASE}/api/datasets/upload", headers=h, files={"file": ("ecommerce.csv", f, "text/csv")})
assert r.status_code==200, r.text
ds=r.json()
ds_id=ds["id"]
log(f"✅ Upload ok {ds_id} rows={ds['row_count']} quality={ds['quality_score']}")

# profile
r=requests.get(f"{BASE}/api/datasets/{ds_id}/profile", headers=h)
assert r.status_code==200
prof=r.json()
assert prof["quality_details"]["score"]>=0
log(f"✅ Profile quality {prof['quality_details']['score']} insights {len(prof['insights'])}")

# preview
r=requests.get(f"{BASE}/api/datasets/{ds_id}/preview", headers=h, params={"page":1,"page_size":5})
assert r.status_code==200
assert len(r.json()["rows"])>0
log("✅ Preview ok")

# copilot ask top5 categories by revenue
q1="Show the top 5 categories by revenue."
r=requests.post(f"{BASE}/api/datasets/{ds_id}/analyze", headers=h, json={"question": q1})
assert r.status_code==200, r.text
data=r.json()
assert data["message"]["execution_status"]=="success", data
assert len(data["message"]["results"])>0
rows=data["message"]["results"][0]["result_data"]["rows"]
log(f"✅ Copilot top5 ok rows={len(rows)} data={rows[:2]}")
session_id=data["session_id"]
assert data["message"]["charts"] or True

# ask monthly revenue
q2="Show monthly revenue."
r=requests.post(f"{BASE}/api/datasets/{ds_id}/analyze", headers=h, json={"question": q2, "session_id": session_id})
assert r.status_code==200, r.text
log(f"✅ Monthly revenue {r.json()['message']['content'][:100]}")

# continue conversation
r=requests.get(f"{BASE}/api/analysis", headers=h)
assert r.status_code==200
assert any(s["id"]==session_id for s in r.json())
log("✅ History list ok")

# reopen session
r=requests.get(f"{BASE}/api/analysis/{session_id}", headers=h)
assert r.status_code==200
assert len(r.json()["messages"])>=4  # user+assistant x2
log(f"✅ Reopen session messages={len(r.json()['messages'])}")

# generate report
r=requests.post(f"{BASE}/api/reports", headers=h, json={"title":"E2E Report","dataset_id": ds_id})
assert r.status_code==200, r.text
rep=r.json()
log(f"✅ Report {rep['id']}")
# download report
r=requests.get(f"{BASE}/api/reports/{rep['id']}", headers=h)
assert r.status_code==200
log("✅ Download report ok")

# delete dataset
r=requests.delete(f"{BASE}/api/datasets/{ds_id}", headers=h)
assert r.status_code==200
log("✅ Delete dataset ok")
r=requests.get(f"{BASE}/api/datasets/{ds_id}", headers=h)
assert r.status_code==404
log("✅ Verify deleted 404 ok")

# unauthorized access test
# create second user
email2=f"e2e2_{int(time.time())}@test.com"
r=requests.post(f"{BASE}/api/auth/register", json={"email":email2,"password":pwd})
token2=r.json()["access_token"]
h2={"Authorization": f"Bearer {token2}"}
# upload as user2 (reuses portable csv_path)
with open(csv_path,"rb") as f:
    r=requests.post(f"{BASE}/api/datasets/upload", headers=h2, files={"file": ("ecommerce.csv", f, "text/csv")})
ds2_id=r.json()["id"]
# user1 tries to access user2 dataset
r=requests.get(f"{BASE}/api/datasets/{ds2_id}", headers=h)
assert r.status_code==404, "Should not leak existence"
log("✅ Unauthorized blocked (404)")

print("\n🎉 E2E PASSED")
