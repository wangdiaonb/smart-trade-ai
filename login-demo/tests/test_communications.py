import smtplib

import pytest
from fastapi.testclient import TestClient

from app import create_app
from database import connection


class FakeSMTP:
    sent=[]
    fail=False
    def __init__(self,host,port,timeout):
        self.host=host;self.port=port;self.started_tls=False;self.logged_in=False
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def ehlo(self):return None
    def login(self,username,password):self.logged_in=(username,password)
    def starttls(self):self.started_tls=True
    def send_message(self,message):
        if self.fail:raise smtplib.SMTPException('provider failure')
        self.sent.append(message)


@pytest.fixture
def clients(tmp_path,monkeypatch):
    FakeSMTP.sent=[];FakeSMTP.fail=False
    monkeypatch.setattr(smtplib,'SMTP',FakeSMTP)
    app=create_app(tmp_path/'mail.sqlite3','test-secret')
    first,second=TestClient(app),TestClient(app)
    for client,email in [(first,'mail-a@example.com'),(second,'mail-b@example.com')]:
        client.post('/api/register',json={'email':email,'password':'correct-horse-1'})
    return first,second,tmp_path/'mail.sqlite3'


def configure(client):
    return client.put('/api/communications/settings',json={
        'host':'smtp.example.com','port':587,'security':'starttls',
        'username':'sender@example.com','from_email':'sender@example.com',
        'password':'smtp-private-password',
    })


def test_smtp_settings_hide_and_encrypt_password(clients):
    first,second,path=clients
    response=configure(first)
    assert response.status_code==200
    assert response.json()['has_password'] is True
    assert 'smtp-private-password' not in response.text
    assert second.get('/api/communications/settings').json()['host']==''
    with connection(path) as conn:
        raw=conn.execute('SELECT password_encrypted FROM smtp_settings').fetchone()[0]
    assert 'smtp-private-password' not in raw


def test_send_single_email_with_ssl_or_starttls_and_scope_history(clients):
    first,second,path=clients
    configure(first)
    customer=first.post('/api/customers',json={'name':'Mail Buyer','email':'buyer@example.com'}).json()
    result=first.post('/api/communications/send',json={'customer_id':customer['id'],'to':'buyer@example.com','subject':'Quotation follow-up','body':'Hello Buyer,\nPlease find our offer.'})
    assert result.status_code==201,result.text
    assert result.json()['status']=='sent'
    assert len(FakeSMTP.sent)==1
    message=FakeSMTP.sent[0]
    assert message['To']=='buyer@example.com'
    assert message['Subject']=='Quotation follow-up'
    assert second.get('/api/communications/history').json()==[]
    assert first.get('/api/communications/history').json()[0]['customer_name']=='Mail Buyer'


def test_mail_errors_are_saved_without_leaking_password(clients):
    first,_,_=clients
    configure(first)
    FakeSMTP.fail=True
    response=first.post('/api/communications/send',json={'to':'buyer@example.com','subject':'Test','body':'Hello'})
    assert response.status_code==502
    assert 'smtp-private-password' not in response.text
    history=first.get('/api/communications/history').json()
    assert history[0]['status']=='error'
    assert 'smtp-private-password' not in str(history)


@pytest.mark.parametrize('payload',[
    {'to':'bad','subject':'Test','body':'Hello'},
    {'to':'a@example.com\nBcc:bad@example.com','subject':'Test','body':'Hello'},
    {'to':'a@example.com','subject':'Bad\nBcc: x','body':'Hello'},
    {'to':'a@example.com','subject':'Test','body':''},
])
def test_send_rejects_injection_and_empty_body(clients,payload):
    first,_,_=clients
    configure(first)
    assert first.post('/api/communications/send',json=payload).status_code==422


def test_cannot_bind_another_tenants_customer(clients):
    first,second,_=clients
    configure(first)
    customer=second.post('/api/customers',json={'name':'Private','email':'private@example.com'}).json()
    response=first.post('/api/communications/send',json={'customer_id':customer['id'],'to':'private@example.com','subject':'Test','body':'Hello'})
    assert response.status_code==404
    assert FakeSMTP.sent==[]


def test_send_rate_limit_is_workspace_scoped(clients):
    first,second,_=clients
    configure(first);configure(second)
    payload={'to':'buyer@example.com','subject':'Test','body':'Hello'}
    for _ in range(10):
        assert first.post('/api/communications/send',json=payload).status_code==201
    assert first.post('/api/communications/send',json=payload).status_code==429
    assert second.post('/api/communications/send',json=payload).status_code==201


@pytest.mark.parametrize('path',['/api/communications/settings','/api/communications/history'])
def test_communications_require_login(tmp_path,path):
    client=TestClient(create_app(tmp_path/'mail-auth.sqlite3','test-secret'))
    assert client.get(path).status_code==401
