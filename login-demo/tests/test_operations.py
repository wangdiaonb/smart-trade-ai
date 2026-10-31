import pytest
from fastapi.testclient import TestClient

from app import create_app


@pytest.fixture
def clients(tmp_path):
    app = create_app(tmp_path/'ops.sqlite3', 'test-secret')
    first, second = TestClient(app), TestClient(app)
    for client,email in [(first,'a@example.com'),(second,'b@example.com')]:
        client.post('/api/register',json={'email':email,'password':'correct-horse-1'})
    return first,second


def buyer(client):
    return client.post('/api/customers',json={'name':'Buyer <script>bad()</script>'}).json()['id']


def order(client, **changes):
    payload={'customer_id':buyer(client),'order_no':'Q-001','items':[{'product_name':'Pump A','quantity':'3','unit_price':'10.10','unit':'pc'},{'product_name':'Seal','quantity':'2','unit_price':'0.25'}],**changes}
    response=client.post('/api/orders',json=payload)
    assert response.status_code==201,response.text
    return response.json()


def test_multi_item_order_exact_amounts_pending_price_and_quotation(clients):
    first,_=clients
    created=order(first)
    assert created['total_amount']=='30.80'
    assert created['items'][0]['total_amount']=='30.30'
    quote=first.get(f'/api/orders/{created["id"]}/quotation')
    assert quote.status_code==200
    assert '30.80' in quote.text and '&lt;script&gt;' in quote.text
    assert '<script>bad()' not in quote.text
    pending=order(first,items=[{'product_name':'Pending','quantity':'2','unit_price':None}])
    assert pending['items'][0]['unit_price'] is None
    assert pending['total_amount'] is None


def test_order_tenant_isolation_and_cross_customer_rejection(clients):
    first,second=clients
    created=order(first)
    assert second.get('/api/orders').json()==[]
    for method in ['get','put','delete']:
        kwargs={'json':{'notes':'steal'}} if method=='put' else {}
        assert getattr(second,method)(f'/api/orders/{created["id"]}',**kwargs).status_code==404
    assert second.get(f'/api/orders/{created["id"]}/quotation').status_code==404
    assert second.post('/api/orders',json={'customer_id':created['customer_id'],'items':[{'product_name':'A'}]}).status_code==404


def test_order_status_progression_and_validation(clients):
    first,_=clients
    created=order(first)
    url=f'/api/orders/{created["id"]}'
    assert first.put(url,json={'status':'已完成'}).status_code==409
    for state in ['已下单','已出货','已完成']:
        assert first.put(url,json={'status':state}).json()['status']==state
    assert first.put(url,json={'status':'报价中'}).status_code==409
    for value in ['-1','NaN','Infinity']:
        assert first.post('/api/orders',json={'customer_id':created['customer_id'],'items':[{'product_name':'Bad','quantity':value}]}).status_code==422
    assert first.post('/api/orders',json={'customer_id':created['customer_id'],'items':[]}).status_code==422


def test_customer_with_orders_cannot_be_deleted_without_handling_orders(clients):
    first,_=clients
    created=order(first)
    result=first.delete(f'/api/customers/{created["customer_id"]}')
    assert result.status_code==409
    assert first.get(f'/api/orders/{created["id"]}').status_code==200


def test_libraries_upload_download_text_and_soft_delete_are_scoped(clients):
    first,second=clients
    response=first.post('/api/libraries',json={'name':'产品资料'})
    assert response.status_code==201
    lib=response.json()['id']
    uploaded=first.post(f'/api/libraries/{lib}/files',files={'file':('spec.md','Water pump: stainless steel 水泵'.encode(),'text/markdown')})
    assert uploaded.status_code==201,uploaded.text
    doc=uploaded.json()
    assert 'root_path' not in doc and 'storage_name' not in doc
    assert first.get(f'/api/documents/{doc["id"]}/text').json()['text'].endswith('水泵')
    assert first.get(f'/api/documents/{doc["id"]}/download').content==b'Water pump: stainless steel '+ '水泵'.encode()
    assert second.get('/api/libraries').json()==[]
    assert second.get(f'/api/libraries/{lib}/files').status_code==404
    assert second.post(f'/api/libraries/{lib}/files',files={'file':('steal.txt',b'text','text/plain')}).status_code==404
    for path in [f'/api/documents/{doc["id"]}/text',f'/api/documents/{doc["id"]}/download']:
        assert second.get(path).status_code==404
    assert first.delete(f'/api/documents/{doc["id"]}').status_code==200
    assert first.get(f'/api/documents/{doc["id"]}/download').status_code==404


def test_upload_extension_limits_and_libraries_cannot_choose_paths(clients):
    first,_=clients
    assert first.post('/api/libraries',json={'name':'A','root_path':'C:/Windows'}).status_code==422
    lib=first.post('/api/libraries',json={'name':'A'}).json()['id']
    assert first.post(f'/api/libraries/{lib}/files',files={'file':('run.exe',b'executable','application/octet-stream')}).status_code==422
    assert first.post(f'/api/libraries/{lib}/files',files={'file':('large.txt',b'x'*(12*1024*1024+1),'text/plain')}).status_code==413


def test_templates_are_owned_and_rendered_as_plain_text(clients):
    first,second=clients
    result=first.post('/api/templates',json={'name':'Cold email','content':'Hello {{customer}}, from {{company}}.'})
    assert result.status_code==201
    tid=result.json()['id']
    assert second.get('/api/templates').json()==[]
    assert second.put(f'/api/templates/{tid}',json={'name':'stolen','content':'x'}).status_code==404
    rendered=first.post(f'/api/templates/{tid}/render',json={'customer':'Acme','company':'Factory'}).json()['content']
    assert rendered=='Hello Acme, from Factory.'
    assert first.delete(f'/api/templates/{tid}').status_code==200


def test_customer_library_associations_are_scoped(clients):
    first,second=clients
    customer=first.post('/api/customers',json={'name':'Linked Buyer'}).json()
    library=first.post('/api/libraries',json={'name':'Buyer documents'}).json()
    assert first.post(f'/api/customers/{customer["id"]}/libraries/{library["id"]}').status_code==200
    assert first.get(f'/api/customers/{customer["id"]}/libraries').json()==[{'id':library['id'],'name':'Buyer documents','description':''}]
    assert second.get(f'/api/customers/{customer["id"]}/libraries').status_code==404
    assert first.delete(f'/api/customers/{customer["id"]}/libraries/{library["id"]}').status_code==200
    assert first.get(f'/api/customers/{customer["id"]}/libraries').json()==[]


def test_library_can_scan_owned_local_folder_idempotently(clients,tmp_path):
    first,second=clients
    folder=tmp_path/'buyer-files';folder.mkdir()
    (folder/'spec.txt').write_text('Stainless steel pump, model X1',encoding='utf-8')
    (folder/'ignored.exe').write_bytes(b'MZ')
    created=first.post('/api/libraries',json={'name':'Local files','root_path':str(folder)})
    assert created.status_code==201,created.text
    lib=created.json();assert lib['root_path']==str(folder.resolve())
    first_scan=first.post(f'/api/libraries/{lib["id"]}/scan')
    assert first_scan.status_code==200,first_scan.text
    assert first_scan.json()['found']==1
    second_scan=first.post(f'/api/libraries/{lib["id"]}/scan')
    assert second_scan.json()['found']==1
    documents=first.get(f'/api/libraries/{lib["id"]}/files').json()
    assert len(documents)==1 and documents[0]['filename']=='spec.txt'
    doc=documents[0]
    assert first.get(f'/api/documents/{doc["id"]}/text').json()['text']=='Stainless steel pump, model X1'
    assert first.get(f'/api/documents/{doc["id"]}/download').content==b'Stainless steel pump, model X1'
    assert second.get(f'/api/documents/{doc["id"]}/download').status_code==404


def test_library_rejects_missing_or_system_folders(clients,tmp_path):
    first,_=clients
    assert first.post('/api/libraries',json={'name':'Missing','root_path':str(tmp_path/'missing')}).status_code==422
    assert first.post('/api/libraries',json={'name':'Root','root_path':str(__import__('pathlib').Path.home())}).status_code==422


def test_operations_require_auth(tmp_path):
    client=TestClient(create_app(tmp_path/'db.sqlite3','test-secret'))
    for path in ['/api/orders','/api/libraries','/api/templates','/api/documents/1/download']:
        assert client.get(path).status_code==401
