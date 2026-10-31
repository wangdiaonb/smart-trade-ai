"""Workspace order tracking and escaped, printable quotations."""

import html
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from business_models import Name, ShortText
from business import WorkspaceStore
from database import connection
from tenancy import TenantContext, require_tenant

router=APIRouter(prefix='/api',tags=['orders'])
Number=Annotated[Decimal,Field(ge=0,le=1_000_000_000,max_digits=18,decimal_places=6,allow_inf_nan=False)]
Status=Literal['报价中','已下单','已出货','已完成','已取消']
TRANSITIONS={'报价中':{'已下单','已取消'},'已下单':{'已出货','已取消'},'已出货':{'已完成'},'已完成':set(),'已取消':set()}


class Item(BaseModel):
    model_config=ConfigDict(extra='forbid')
    product_name: Name
    quantity: Number|None=None
    unit: ShortText=''
    unit_price: Number|None=None


class OrderInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    customer_id: int=Field(gt=0)
    order_no: ShortText=''
    currency: str=Field('USD',pattern=r'^[A-Z]{3}$')
    items: list[Item]=Field(min_length=1,max_length=100)
    delivery_date: ShortText=''
    payment_terms: ShortText=''
    notes: str=Field('',max_length=20000)


class OrderUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    order_no: ShortText|None=None
    currency: str|None=Field(None,pattern=r'^[A-Z]{3}$')
    items: list[Item]|None=Field(None,min_length=1,max_length=100)
    status: Status|None=None
    delivery_date: ShortText|None=None
    payment_terms: ShortText|None=None
    notes: str|None=Field(None,max_length=20000)


def order_context(request:Request,tenant:TenantContext=Depends(require_tenant)):
    return request.app.state.db_path,tenant


Context=Annotated[tuple,Depends(order_context)]


def get_order(path,wid,oid):
    with connection(path) as conn:
        row=conn.execute('SELECT orders.*,customers.name AS customer_name FROM orders JOIN customers ON customers.id=orders.customer_id AND customers.workspace_id=orders.workspace_id WHERE orders.id=? AND orders.workspace_id=?',(oid,wid)).fetchone()
        if row is None:raise HTTPException(404,'Order not found')
        items=conn.execute('SELECT product_name,quantity,unit,unit_price,total_amount FROM order_items WHERE order_id=? AND workspace_id=? ORDER BY position',(oid,wid)).fetchall()
    return {**dict(row),'items':[dict(item) for item in items]}


def write_items(conn,wid,oid,items):
    conn.execute('DELETE FROM order_items WHERE order_id=? AND workspace_id=?',(oid,wid))
    total=Decimal(0)
    pending=False
    for index,item in enumerate(items):
        amount=None if item.quantity is None or item.unit_price is None else (item.quantity*item.unit_price).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        if amount is None:pending=True
        else:total+=amount
        conn.execute('INSERT INTO order_items(workspace_id,order_id,position,product_name,quantity,unit,unit_price,total_amount) VALUES (?,?,?,?,?,?,?,?)',(wid,oid,index,item.product_name,str(item.quantity) if item.quantity is not None else None,item.unit,str(item.unit_price) if item.unit_price is not None else None,str(amount) if amount is not None else None))
    conn.execute('UPDATE orders SET total_amount=? WHERE id=? AND workspace_id=?',(None if pending else str(total.quantize(Decimal('.01'))),oid,wid))


@router.get('/orders')
def list_orders(context:Context):
    path,tenant=context
    with connection(path) as conn:
        rows=conn.execute('SELECT orders.*,customers.name AS customer_name FROM orders JOIN customers ON customers.id=orders.customer_id AND customers.workspace_id=orders.workspace_id WHERE orders.workspace_id=? ORDER BY orders.id DESC LIMIT 500',(tenant.workspace_id,)).fetchall()
    return [dict(row) for row in rows]


@router.post('/orders',status_code=201)
def create_order(payload:OrderInput,context:Context):
    path,tenant=context;wid=tenant.workspace_id
    with connection(path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT 1 FROM customers WHERE id=? AND workspace_id=?',(payload.customer_id,wid)).fetchone() is None:raise HTTPException(404,'Customer not found')
        cursor=conn.execute('INSERT INTO orders(workspace_id,customer_id,order_no,currency,delivery_date,payment_terms,notes) VALUES (?,?,?,?,?,?,?)',(wid,payload.customer_id,payload.order_no,payload.currency,payload.delivery_date,payload.payment_terms,payload.notes))
        oid=cursor.lastrowid
        write_items(conn,wid,oid,payload.items)
    return get_order(path,wid,oid)


@router.get('/orders/{oid}')
def read_order(oid:int,context:Context):
    path,tenant=context
    return get_order(path,tenant.workspace_id,oid)


@router.put('/orders/{oid}')
def update_order(oid:int,payload:OrderUpdate,context:Context):
    path,tenant=context;wid=tenant.workspace_id
    values=payload.model_dump(exclude_unset=True,exclude_none=True,exclude={'items'})
    with connection(path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        old=conn.execute('SELECT status FROM orders WHERE id=? AND workspace_id=?',(oid,wid)).fetchone()
        if old is None:raise HTTPException(404,'Order not found')
        new=values.get('status',old['status'])
        if new!=old['status'] and new not in TRANSITIONS[old['status']]:raise HTTPException(409,'订单状态必须按报价、下单、出货、完成的顺序更新。')
        if values:
            assignments=','.join(f'{field}=?' for field in values)
            conn.execute(f"UPDATE orders SET {assignments},updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND workspace_id=?",(*values.values(),oid,wid))
        if payload.items is not None:write_items(conn,wid,oid,payload.items)
    return get_order(path,wid,oid)


@router.delete('/orders/{oid}')
def delete_order(oid:int,context:Context):
    path,tenant=context
    with connection(path) as conn:
        row=conn.execute('SELECT status FROM orders WHERE id=? AND workspace_id=?',(oid,tenant.workspace_id)).fetchone()
        if row is None:raise HTTPException(404,'Order not found')
        if row['status'] not in {'报价中','已取消'}:raise HTTPException(409,'仅可删除报价中或已取消的订单。')
        conn.execute('DELETE FROM orders WHERE id=? AND workspace_id=?',(oid,tenant.workspace_id))
    return {'ok':True}


@router.get('/orders/{oid}/quotation',response_class=HTMLResponse)
def quotation(oid:int,context:Context):
    path,tenant=context
    order=get_order(path,tenant.workspace_id,oid)
    company=WorkspaceStore(path,tenant).get_company()
    esc=lambda value:html.escape(str(value if value is not None else '待谈'))
    rows=''.join('<tr>'+''.join(f'<td>{esc(item[field])}</td>' for field in ['product_name','quantity','unit','unit_price','total_amount'])+'</tr>' for item in order['items'])
    body=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Quotation {esc(order['order_no'])}</title><style>body{{font-family:Arial,"Microsoft YaHei",sans-serif;max-width:900px;margin:45px auto;color:#18362a;padding:20px}}h1{{letter-spacing:2px}}table{{width:100%;border-collapse:collapse;margin:30px 0}}th,td{{padding:12px;border-bottom:1px solid #ccd8d0;text-align:left}}p{{white-space:pre-wrap}}.total{{text-align:right;font-size:20px}}@media print{{body{{margin:0}}}}</style><h1>QUOTATION / 报价单</h1><h2>{esc(company['name'])}</h2><p>{esc(company['address'])}</p><p>To: {esc(order['customer_name'])}<br>Quotation No.: {esc(order['order_no'])}<br>Currency: {esc(order['currency'])}</p><table><thead><tr><th>Product</th><th>Quantity</th><th>Unit</th><th>Unit price</th><th>Amount</th></tr></thead><tbody>{rows}</tbody></table><p class="total">Total: {esc(order['currency'])} {esc(order['total_amount'])}</p><p>Delivery: {esc(order['delivery_date'])}<br>Payment: {esc(order['payment_terms'])}</p><p>{esc(order['notes'])}</p><p>可通过浏览器打印或另存为 PDF。</p></html>'''
    return HTMLResponse(body,headers={'Cache-Control':'no-store','Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"})
