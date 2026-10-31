import csv
import io

import pytest
from fastapi.testclient import TestClient

from app import create_app


@pytest.fixture
def clients(tmp_path):
    app = create_app(tmp_path / "accounts.sqlite3", "test-secret")
    first, second = TestClient(app), TestClient(app)
    for client, email in [(first, "first@example.com"), (second, "second@example.com")]:
        assert client.post("/api/register", json={"email": email, "password": "correct-horse-1"}).status_code == 201
    return first, second


def test_company_profile_is_private_and_updates_workspace_name(clients):
    first, second = clients
    assert first.get("/api/company").status_code == 200
    update = first.put("/api/company", json={"name": "远航机械", "products": "工业水泵", "target_region": "欧洲"})
    assert update.status_code == 200
    assert update.json()["name"] == "远航机械"
    assert first.get("/api/workspace").json()["name"] == "远航机械"
    assert second.get("/api/company").json()["name"] == "我的公司"
    assert first.put("/api/company", json={"workspace_id": 999, "name": "入侵"}).status_code == 422
    assert first.put("/api/company", json={"name": "   "}).status_code == 422


def test_customer_crud_preserves_fields_and_filters(clients):
    first, _ = clients
    payload = {"name": "Acme Pumps", "contact": "Alice", "tier": "A", "country": "德国", "email": "alice@acme.example", "source": "exhibition", "match_score": 5, "social_media": {"linkedin": "https://example.com/alice"}}
    result = first.post("/api/customers", json=payload)
    assert result.status_code == 201
    customer = result.json()
    for field, value in payload.items():
        assert customer[field] == value
    customer_id = customer["id"]
    updated = first.put(f"/api/customers/{customer_id}", json={"note": "已发样品"})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Acme Pumps"
    assert updated.json()["note"] == "已发样品"
    found = first.get("/api/customers", params={"q": "Alice", "tier": "A", "country": "德国"}).json()
    assert found["total"] == 1
    assert found["items"][0]["id"] == customer_id
    assert first.get("/api/customers", params={"tier": "C"}).json()["total"] == 0
    assert first.delete(f"/api/customers/{customer_id}").status_code == 200
    assert first.get(f"/api/customers/{customer_id}").status_code == 404


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_other_account_cannot_access_customer_by_id(clients, method):
    first, second = clients
    created = first.post("/api/customers", json={"name": "Private buyer"})
    assert created.status_code == 201
    url = f'/api/customers/{created.json()["id"]}'
    kwargs = {"json": {"name": "Stolen"}} if method == "put" else {}
    assert getattr(second, method)(url, **kwargs).status_code == 404
    assert first.get(url).json()["name"] == "Private buyer"
    assert second.get("/api/customers").json() == {"items": [], "total": 0}


@pytest.mark.parametrize("field", ["user_id", "workspace_id", "company_id"])
def test_customer_body_cannot_select_owner(clients, field):
    first, _ = clients
    response = first.post("/api/customers", json={"name": "Acme", field: 999})
    assert response.status_code == 422
    assert first.get("/api/customers").json()["total"] == 0


@pytest.mark.parametrize("payload", [{"name": "  "}, {"name": "A", "tier": "D"}, {"name": "A", "match_score": 6}, {"name": "A", "match_score": -1}, {"name": "A", "match_score": 1.5}, {"name": None}])
def test_customer_validation(clients, payload):
    assert clients[0].post("/api/customers", json=payload).status_code == 422


def test_two_accounts_can_have_same_customer_name_and_pagination_is_scoped(clients):
    first, second = clients
    for client in [first, second]:
        assert client.post("/api/customers", json={"name": "Same buyer"}).status_code == 201
    first.post("/api/customers", json={"name": "Second buyer"})
    page = first.get("/api/customers?limit=1&offset=1").json()
    assert page["total"] == 2
    assert len(page["items"]) == 1
    assert second.get("/api/customers").json()["total"] == 1
    # SQL wildcard characters in search are literal input, not an unbounded query.
    assert first.get("/api/customers", params={"q": "%"}).json()["total"] == 0


def test_csv_round_trip_is_scoped_and_does_not_execute_formula_cells(clients):
    first, second = clients
    assert first.post("/api/customers", json={"name": "=1+1", "note": "中文,换行\n备注"}).status_code == 201
    assert second.post("/api/customers", json={"name": "Other buyer"}).status_code == 201
    response = first.get("/api/customers/export")
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert len(rows) == 1
    assert rows[0]["name"] == "'=1+1"
    assert "workspace_id" not in rows[0]
    imported = second.post("/api/customers/import", json={"content": "name,contact,tier,country\n新客户,张三,B,法国\n"})
    assert imported.status_code == 201
    assert imported.json() == {"imported": 1}
    assert second.get("/api/customers").json()["total"] == 2
    assert first.get("/api/customers").json()["total"] == 1


def test_csv_import_is_atomic_and_rejects_owner_columns(clients):
    first, _ = clients
    for content in ["name,tier\nGood,A\nBad,D\n", "name,workspace_id\nStolen,999\n", "wrong\nvalue\n"]:
        response = first.post("/api/customers/import", json={"content": content})
        assert response.status_code == 422
        assert first.get("/api/customers").json()["total"] == 0


def test_account_can_switch_owned_companies_and_business_data_stays_separate(clients):
    first,second=clients
    original=first.get('/api/company').json()
    created=first.post('/api/companies',json={'name':'Second company'})
    assert created.status_code==201
    second_company=created.json()
    assert first.get('/api/company').json()['name']=='Second company'
    assert first.post('/api/customers',json={'name':'Second buyer'}).status_code==201
    assert first.post('/api/libraries',json={'name':'Second docs'}).status_code==201
    assert first.get('/api/customers').json()['total']==1
    assert first.post(f'/api/companies/{original["id"]}/select').status_code==200
    assert first.get('/api/company').json()['name']=='我的公司'
    assert first.get('/api/customers').json()['total']==0
    assert first.get('/api/libraries').json()==[]
    forged=first.get('/api/company',headers={'X-Company-ID':str(second_company['id'])})
    assert forged.json()['id']==original['id']
    assert second.get('/api/companies').json()==[{'id':second.get('/api/company').json()['id'],'name':'我的公司','website':'','contact_name':'','contact_email':'','address':'','industry':'','products':'','target_region':'','agent_identity_md':'','updated_at':second.get('/api/company').json()['updated_at']}]


@pytest.mark.parametrize("path", ["/api/company", "/api/customers", "/api/customers/1", "/api/customers/export"])
def test_business_endpoints_require_login(tmp_path, path):
    client = TestClient(create_app(tmp_path / "accounts.sqlite3", "test-secret"))
    assert client.get(path).status_code == 401
