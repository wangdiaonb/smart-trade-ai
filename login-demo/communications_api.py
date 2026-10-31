"""Explicit one-off email sending through a workspace-owned SMTP account."""

import re
import smtplib
import time
from email.message import EmailMessage
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, SecretStr, field_validator

from business_models import BusinessInput
from database import connection
from tenancy import TenantContext, require_tenant

router = APIRouter(prefix='/api', tags=['communications'])
EMAIL = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')


class SMTPInput(BusinessInput):
    host: str = Field(min_length=1, max_length=253, pattern=r'^[A-Za-z0-9.-]+$')
    port: int = Field(587, ge=1, le=65535)
    security: Literal['starttls', 'ssl', 'none'] = 'starttls'
    username: str = Field('', max_length=500)
    from_email: str = Field(min_length=3, max_length=254)
    password: SecretStr | None = Field(None, max_length=1000)
    clear_password: bool = False

    @field_validator('from_email')
    @classmethod
    def valid_from(cls, value):
        if not EMAIL.fullmatch(value) or any(char in value for char in '\r\n'):
            raise ValueError('Invalid sender email')
        return value


class MailInput(BusinessInput):
    to: str = Field(min_length=3, max_length=254)
    customer_id: int | None = Field(None, gt=0)
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=100000, pattern=r'\S')

    @field_validator('to')
    @classmethod
    def valid_to(cls, value):
        if not EMAIL.fullmatch(value) or any(char in value for char in '\r\n'):
            raise ValueError('Invalid recipient email')
        return value

    @field_validator('subject')
    @classmethod
    def valid_subject(cls, value):
        if '\r' in value or '\n' in value:
            raise ValueError('Subject cannot contain line breaks')
        return value.strip()


def context(request: Request, tenant: TenantContext = Depends(require_tenant)):
    return request, tenant


Context = Annotated[tuple, Depends(context)]


def _saved(path, wid):
    with connection(path) as conn:
        return conn.execute('SELECT * FROM smtp_settings WHERE workspace_id=?', (wid,)).fetchone()


def _public(row):
    if row is None:
        return {'host': '', 'port': 587, 'security': 'starttls', 'username': '', 'from_email': '', 'has_password': False}
    return {
        'host': row['host'],
        'port': row['port'],
        'security': row['security'],
        'username': row['username'],
        'from_email': row['from_email'],
        'has_password': bool(row['password_encrypted']),
    }


@router.get('/communications/settings')
def get_settings(context: Context):
    request, tenant = context
    return _public(_saved(request.app.state.db_path, tenant.workspace_id))


@router.put('/communications/settings')
def update_settings(payload: SMTPInput, context: Context):
    request, tenant = context
    if payload.password and payload.clear_password:
        raise HTTPException(422, '不能同时填写和清除 SMTP 密码。')
    current = _saved(request.app.state.db_path, tenant.workspace_id)
    encrypted = current['password_encrypted'] if current else ''
    if payload.clear_password:
        encrypted = ''
    elif payload.password and payload.password.get_secret_value().strip():
        encrypted = request.app.state.secret_store.encrypt(tenant.workspace_id, payload.password.get_secret_value().strip())
    with connection(request.app.state.db_path) as conn:
        conn.execute('''
            INSERT INTO smtp_settings(workspace_id,host,port,security,username,from_email,password_encrypted)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(workspace_id) DO UPDATE SET
                host=excluded.host,port=excluded.port,security=excluded.security,
                username=excluded.username,from_email=excluded.from_email,password_encrypted=excluded.password_encrypted
        ''', (tenant.workspace_id, payload.host, payload.port, payload.security, payload.username, payload.from_email, encrypted))
    return _public(_saved(request.app.state.db_path, tenant.workspace_id))


def _history_entry(path, wid, communication_id):
    with connection(path) as conn:
        row = conn.execute('''
            SELECT communications.id,communications.recipient,communications.subject,
                   communications.status,communications.error,communications.created_at,
                   communications.customer_id,customers.name AS customer_name
            FROM communications LEFT JOIN customers
              ON customers.id=communications.customer_id AND customers.workspace_id=communications.workspace_id
            WHERE communications.id=? AND communications.workspace_id=?
        ''', (communication_id, wid)).fetchone()
    return dict(row)


@router.post('/communications/send', status_code=201)
def send_email(payload: MailInput, context: Context):
    request, tenant = context
    path = request.app.state.db_path
    wid = tenant.workspace_id
    settings = _saved(path, wid)
    if settings is None:
        raise HTTPException(409, '请先配置 SMTP 邮箱。')
    now = time.time()
    with connection(path) as conn:
        recent = conn.execute('SELECT count(*) FROM communications WHERE workspace_id=? AND created_ts>?', (wid, now - 3600)).fetchone()[0]
        if recent >= 10:
            raise HTTPException(429, '本账号每小时最多发送 10 封邮件，请稍后再试。')
        if payload.customer_id is not None and conn.execute(
            'SELECT 1 FROM customers WHERE id=? AND workspace_id=?',
            (payload.customer_id, wid),
        ).fetchone() is None:
            raise HTTPException(404, 'Customer not found')
    try:
        password = request.app.state.secret_store.decrypt(wid, settings['password_encrypted']) if settings['password_encrypted'] else ''
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    message = EmailMessage()
    message['From'] = settings['from_email']
    message['To'] = payload.to
    message['Subject'] = payload.subject
    message.set_content(payload.body)
    status = 'sent'
    error = ''
    try:
        if settings['security'] == 'ssl':
            client = smtplib.SMTP_SSL(settings['host'], settings['port'], timeout=20)
        else:
            client = smtplib.SMTP(settings['host'], settings['port'], timeout=20)
        with client as smtp:
            smtp.ehlo()
            if settings['security'] == 'starttls':
                smtp.starttls()
                smtp.ehlo()
            if settings['username']:
                smtp.login(settings['username'], password)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError):
        status = 'error'
        error = '邮件服务发送失败，请检查 SMTP 配置和网络。'
    with connection(path) as conn:
        cursor = conn.execute('''
            INSERT INTO communications(workspace_id,customer_id,recipient,subject,status,error,created_ts)
            VALUES (?,?,?,?,?,?,?)
        ''', (wid, payload.customer_id, payload.to, payload.subject, status, error, now))
    entry = _history_entry(path, wid, cursor.lastrowid)
    if status == 'error':
        raise HTTPException(502, error)
    return entry


@router.get('/communications/history')
def history(context: Context):
    request, tenant = context
    with connection(request.app.state.db_path) as conn:
        rows = conn.execute('''
            SELECT communications.id,communications.recipient,communications.subject,
                   communications.status,communications.error,communications.created_at,
                   communications.customer_id,customers.name AS customer_name
            FROM communications LEFT JOIN customers
              ON customers.id=communications.customer_id AND customers.workspace_id=communications.workspace_id
            WHERE communications.workspace_id=? ORDER BY communications.id DESC LIMIT 100
        ''', (tenant.workspace_id,)).fetchall()
    return [dict(row) for row in rows]
