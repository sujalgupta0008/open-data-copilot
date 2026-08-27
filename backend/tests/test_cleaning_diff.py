from fastapi.testclient import TestClient
from app.main import app
import uuid

client = TestClient(app)

def make_user():
    email=f"diff{uuid.uuid4().hex[:6]}@test.com"
    r=client.post("/api/auth/register", json={"email":email,"password":"pass123","name":"Test"})
    token=r.json()["access_token"]
    return {"Authorization":f"Bearer {token}"}

def upload(h, content, name="test.csv"):
    files={"file":(name, content, "text/csv")}
    r=client.post("/api/datasets/upload", files=files, headers=h)
    assert r.status_code==200, r.text
    return r.json()["id"]

def get_diff(h, did):
    r=client.get(f"/api/datasets/{did}/diff", headers=h)
    assert r.status_code==200, r.text
    return r.json()

def test_missing_value_fix():
    h=make_user()
    csv="a,b\n1,2\n2,\n3,4\n"
    did=upload(h, csv)
    before=get_diff(h, did)["missing_cells"]["before"]
    assert before==1
    r=client.post(f"/api/datasets/{did}/clean/apply", json={"op":"missing","params":{"column":"b","method":"fill_median"}}, headers=h)
    assert r.status_code==200
    diff=get_diff(h, did)
    assert diff["missing_cells"]["before"]==1
    assert diff["missing_cells"]["after"]==0
    assert diff["changes_applied"]["missing_resolved"]==1
    assert diff["changes_applied"]["columns_added"]==[]
    # Verify matches actual DataFrame state: after missing should be 0
    # Already via diff

def test_row_filter():
    h=make_user()
    csv="a,b\n1,2\n2,3\n3,4\n4,5\n"
    did=upload(h, csv)
    r=client.post(f"/api/datasets/{did}/clean/apply", json={"op":"row_filter","params":{"sub_operation":"filter_by_value","column":"a","value":"2"}}, headers=h)
    assert r.status_code==200
    diff=get_diff(h, did)
    assert diff["rows"]["before"]==4
    assert diff["rows"]["after"]==1
    assert diff["changes_applied"]["rows_removed"]==3

def test_column_removal():
    h=make_user()
    csv="a,b,c\n1,2,3\n4,5,6\n"
    did=upload(h, csv)
    r=client.post(f"/api/datasets/{did}/clean/apply", json={"op":"column","params":{"sub_operation":"remove","column":"b"}}, headers=h)
    assert r.status_code==200
    diff=get_diff(h, did)
    assert diff["columns"]["before"]==3
    assert diff["columns"]["after"]==2
    assert "b" in diff["columns_removed"]
    assert diff["columns_added"]==[]

def test_rename():
    h=make_user()
    csv="a,b\n1,2\n3,4\n"
    did=upload(h, csv)
    r=client.post(f"/api/datasets/{did}/clean/apply", json={"op":"column","params":{"sub_operation":"rename","old_name":"a","new_name":"a_renamed"}}, headers=h)
    assert r.status_code==200
    diff=get_diff(h, did)
    assert diff["columns"]["before"]==2
    assert diff["columns"]["after"]==2
    assert "a_renamed" in diff["columns_added"]
    assert "a" in diff["columns_removed"]

def test_deduplication():
    h=make_user()
    csv="a,b\n1,2\n1,2\n3,4\n"
    did=upload(h, csv)
    r=client.post(f"/api/datasets/{did}/clean/apply", json={"op":"remove_duplicates","params":{}}, headers=h)
    assert r.status_code==200
    diff=get_diff(h, did)
    assert diff["duplicates"]["before"]==1
    assert diff["duplicates"]["after"]==0
    assert diff["changes_applied"]["duplicates_removed"]==1

def test_type_conversion():
    h=make_user()
    csv="a,b\n1,2\n3,4\n"
    did=upload(h, csv)
    r=client.post(f"/api/datasets/{did}/clean/apply", json={"op":"column","params":{"sub_operation":"change_type","column":"a","dtype":"string"}}, headers=h)
    assert r.status_code==200
    diff=get_diff(h, did)
    assert diff["columns"]["before"]==2
    assert diff["columns"]["after"]==2
    # No columns added/removed for type conversion
    assert diff["columns_added"]==[] and diff["columns_removed"]==[]

def test_add_columns_flag():
    h=make_user()
    # Use varied 'b' with IQR>0 so outlier is detected (avoid high-cardinality identifier)
    csv="a,b\n1,10\n2,12\n3,11\n4,1000\n5,13\n6,11\n7,10\n8,12\n9,11\n10,13\n11,10\n12,12\n13,11\n"
    did=upload(h, csv)
    r=client.post(f"/api/datasets/{did}/clean/apply", json={"op":"numeric","params":{"column":"b","sub_operation":"handle_outliers","method":"flag"}}, headers=h)
    assert r.status_code==200, r.text
    diff=get_diff(h, did)
    assert len(diff["columns_added"])==1
    assert "b_is_outlier" in diff["columns_added"]
    assert diff["columns"]["before"]==2
    assert diff["columns"]["after"]==3

def test_metadata_matches_state():
    h=make_user()
    csv="a,b\n1,2\n2,\n3,4\n"
    did=upload(h, csv)
    # Get before state
    diff_before=get_diff(h, did)
    rows_before=diff_before["rows"]["before"]
    missing_before=diff_before["missing_cells"]["before"]
    r=client.post(f"/api/datasets/{did}/clean/apply", json={"op":"missing","params":{"column":"b","method":"fill_median"}}, headers=h)
    assert r.status_code==200
    diff=get_diff(h, did)
    # Verify metadata matches actual diff
    meta=diff["metadata"]
    assert meta["rows_before"]==rows_before
    assert meta["missing_before"]==missing_before
    assert meta["rows_after"]==diff["rows"]["after"]
    assert meta["missing_after"]==diff["missing_cells"]["after"]
    assert meta["quality_before"]==diff["quality"]["before"]
    assert meta["quality_after"]==diff["quality"]["after"]
