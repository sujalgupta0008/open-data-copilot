import uuid
from fastapi.testclient import TestClient
from app.main import app
from app.core.database import init_db
import time
from datetime import datetime, timezone, timedelta

init_db()
client = TestClient(app)

def user(email):
    r = client.post("/api/auth/register", json={"email":email,"password":"passwd123"})
    if r.status_code==400:
        r = client.post("/api/auth/login", json={"email":email,"password":"passwd123"})
    assert r.status_code==200, r.text
    return r.json()["access_token"]

def test_share_token_create():
    tok=user(f"share_create_{uuid.uuid4().hex[:6]}@test.com")
    h={"Authorization":f"Bearer {tok}"}
    csv="a,b\n1,2\n3,4\n"
    did=client.post("/api/datasets/upload", files={"file":("a.csv",csv,"text/csv")}, headers=h).json()["id"]
    r=client.post("/api/reports/generate", headers=h, json={"dataset_id":did, "topic":"What is total a?", "title":"ShareCreate"})
    assert r.status_code==200, r.text
    rid=r.json()["id"]
    assert rid!="clarification"
    # create share
    r=client.post(f"/api/reports/{rid}/share", headers=h, json={"expires_in_days":30})
    assert r.status_code==200, r.text
    j=r.json()
    assert "share_url" in j
    assert "token" in j
    assert j["share_url"].endswith(j["token"])
    assert "expires_at" in j
    assert j["role"]=="viewer"
    # list shares
    r=client.get(f"/api/reports/{rid}/shares", headers=h)
    assert r.status_code==200
    lst=r.json()
    assert len(lst)>=1
    assert lst[0]["token_preview"] == j["token"][:8]
    assert lst[0]["is_active"]==True
    assert lst[0]["view_count"]==0

def test_share_token_public_access():
    tok=user(f"share_pub_{uuid.uuid4().hex[:6]}@test.com")
    h={"Authorization":f"Bearer {tok}"}
    csv="a,b\n1,2\n3,4\n"
    did=client.post("/api/datasets/upload", files={"file":("a.csv",csv,"text/csv")}, headers=h).json()["id"]
    r=client.post("/api/reports/generate", headers=h, json={"dataset_id":did, "topic":"What is total a?", "title":"Pub"})
    rid=r.json()["id"]
    r=client.post(f"/api/reports/{rid}/share", headers=h, json={"expires_in_days":30})
    token=r.json()["token"]
    # public access without auth
    r=client.get(f"/api/shared/r/{token}")
    assert r.status_code==200, r.text
    j=r.json()
    assert j["id"]==rid
    assert "title" in j
    assert "content" in j
    # no owner info
    assert "user_id" not in str(j).lower() or "owner" not in str(j).lower() # ensure no leak
    assert "email" not in str(j).lower()
    # view count incremented
    r2=client.get(f"/api/reports/{rid}/shares", headers=h)
    assert r2.json()[0]["view_count"]>=1
    # second public access increments again
    client.get(f"/api/shared/r/{token}")
    r3=client.get(f"/api/reports/{rid}/shares", headers=h)
    assert r3.json()[0]["view_count"]>=2

def test_share_token_expired():
    tok=user(f"share_exp_{uuid.uuid4().hex[:6]}@test.com")
    h={"Authorization":f"Bearer {tok}"}
    csv="a,b\n1,2\n"
    did=client.post("/api/datasets/upload", files={"file":("a.csv",csv,"text/csv")}, headers=h).json()["id"]
    r=client.post("/api/reports/generate", headers=h, json={"dataset_id":did, "topic":"What is total a?", "title":"Exp"})
    rid=r.json()["id"]
    # create share then manually expire via DB
    r=client.post(f"/api/reports/{rid}/share", headers=h, json={"expires_in_days":1})
    token=r.json()["token"]
    # expire it by直接 updating DB
    from app.core.database import SessionLocal
    from app.models.models import ShareToken
    db=SessionLocal()
    st=db.query(ShareToken).filter(ShareToken.token==token).first()
    st.expires_at=datetime.now(timezone.utc)-timedelta(days=1)
    db.commit()
    db.close()
    # now public should 404
    r=client.get(f"/api/shared/r/{token}")
    assert r.status_code==404, r.text
    assert "expired" in r.text.lower() or "not found" in r.text.lower()

def test_share_token_revoke():
    tok=user(f"share_rev_{uuid.uuid4().hex[:6]}@test.com")
    h={"Authorization":f"Bearer {tok}"}
    csv="a,b\n1,2\n"
    did=client.post("/api/datasets/upload", files={"file":("a.csv",csv,"text/csv")}, headers=h).json()["id"]
    r=client.post("/api/reports/generate", headers=h, json={"dataset_id":did, "topic":"What is total a?", "title":"Rev"})
    rid=r.json()["id"]
    r=client.post(f"/api/reports/{rid}/share", headers=h, json={"expires_in_days":30})
    token=r.json()["token"]
    tid=r.json()["id"]
    # public works before revoke
    assert client.get(f"/api/shared/r/{token}").status_code==200
    # revoke
    r=client.delete(f"/api/reports/{rid}/shares/{tid}", headers=h)
    assert r.status_code==200
    # public now 404
    r=client.get(f"/api/shared/r/{token}")
    assert r.status_code==404
    # list should be empty or inactive
    r=client.get(f"/api/reports/{rid}/shares", headers=h)
    assert len(r.json())==0

def test_share_token_no_owner_leak():
    tokA=user(f"share_owner_{uuid.uuid4().hex[:6]}@test.com")
    hA={"Authorization":f"Bearer {tokA}"}
    tokB=user(f"share_other_{uuid.uuid4().hex[:6]}@test.com")
    hB={"Authorization":f"Bearer {tokB}"}
    csv="a,b\n1,2\n"
    did=client.post("/api/datasets/upload", files={"file":("a.csv",csv,"text/csv")}, headers=hA).json()["id"]
    r=client.post("/api/reports/generate", headers=hA, json={"dataset_id":did, "topic":"What is total a?", "title":"NoLeak"})
    rid=r.json()["id"]
    r=client.post(f"/api/reports/{rid}/share", headers=hA, json={"expires_in_days":30})
    token=r.json()["token"]
    # cross-user tries to list shares -> 404 owner only
    assert client.get(f"/api/reports/{rid}/shares", headers=hB).status_code==404
    assert client.post(f"/api/reports/{rid}/share", headers=hB, json={"expires_in_days":30}).status_code==404
    # public access does not reveal owner
    r=client.get(f"/api/shared/r/{token}")
    txt=r.text.lower()
    assert "owner" not in txt
    assert "user_id" not in txt
    assert tokA not in txt
    # invalid token 404
    assert client.get("/api/shared/r/invalid-token-xyz").status_code==404

def test_share_token_slack_validation():
    tok=user(f"share_slack_{uuid.uuid4().hex[:6]}@test.com")
    h={"Authorization":f"Bearer {tok}"}
    csv="a,b\n1,2\n"
    did=client.post("/api/datasets/upload", files={"file":("a.csv",csv,"text/csv")}, headers=h).json()["id"]
    r=client.post("/api/reports/generate", headers=h, json={"dataset_id":did, "topic":"What is total a?", "title":"Slack"})
    rid=r.json()["id"]
    # non-slack url rejected
    r=client.post(f"/api/reports/{rid}/export/slack", headers=h, json={"webhook_url":"https://evil.com/hook"})
    assert r.status_code==400
    assert "hooks.slack.com" in r.text
    # missing prefix rejected
    r=client.post(f"/api/reports/{rid}/export/slack", headers=h, json={"webhook_url":"http://hooks.slack.com/hook"})
    assert r.status_code==400

def test_analysis_share():
    tok=user(f"share_ana_{uuid.uuid4().hex[:6]}@test.com")
    h={"Authorization":f"Bearer {tok}"}
    csv="a,b\n1,2\n3,4\n"
    did=client.post("/api/datasets/upload", files={"file":("a.csv",csv,"text/csv")}, headers=h).json()["id"]
    r=client.post(f"/api/datasets/{did}/analyze", headers=h, json={"question":"What is total a?"})
    assert r.status_code==200, r.text
    sess=r.json()["session_id"]
    # share analysis
    r=client.post(f"/api/analysis/{sess}/share", headers=h, json={"expires_in_days":30})
    assert r.status_code==200, r.text
    token=r.json()["token"]
    # public access
    r=client.get(f"/api/shared/a/{token}")
    assert r.status_code==200, r.text
    j=r.json()
    assert j["id"]==sess
    assert "messages" in j
    # no owner leak
    assert "email" not in r.text.lower()
