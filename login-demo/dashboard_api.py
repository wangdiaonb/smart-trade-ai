"""Read-only overview metrics scoped to the authenticated workspace."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from database import connection
from tenancy import TenantContext, require_tenant

router = APIRouter(prefix='/api', tags=['dashboard'])


def context(request: Request, tenant: TenantContext = Depends(require_tenant)):
    return request.app.state.db_path, tenant


Context = Annotated[tuple, Depends(context)]


@router.get('/dashboard')
def dashboard(context: Context):
    path, tenant = context
    wid = tenant.workspace_id
    with connection(path) as conn:
        queries = {
            'customers': 'SELECT count(*) FROM customers WHERE workspace_id=?',
            'open_orders': "SELECT count(*) FROM orders WHERE workspace_id=? AND status IN ('报价中','已下单','已出货')",
            'documents': 'SELECT count(*) FROM documents WHERE workspace_id=? AND deleted=0',
            'templates': 'SELECT count(*) FROM templates WHERE workspace_id=?',
            'conversations': 'SELECT count(*) FROM conversations WHERE workspace_id=?',
            'automations': 'SELECT count(*) FROM automations WHERE workspace_id=? AND enabled=1',
        }
        counts = {key: conn.execute(sql, (wid,)).fetchone()[0] for key, sql in queries.items()}
        recent_orders = conn.execute('''
            SELECT orders.id,orders.order_no,orders.status,orders.currency,orders.total_amount,
                   orders.created_at,customers.name AS customer_name
            FROM orders JOIN customers ON customers.id=orders.customer_id AND customers.workspace_id=orders.workspace_id
            WHERE orders.workspace_id=? ORDER BY orders.id DESC LIMIT 5
        ''', (wid,)).fetchall()
        next_tasks = conn.execute('''
            SELECT id,name,next_run_at,frequency,time_of_day FROM automations
            WHERE workspace_id=? AND enabled=1 ORDER BY next_run_at LIMIT 5
        ''', (wid,)).fetchall()
    return {
        'counts': counts,
        'recent_orders': [dict(row) for row in recent_orders],
        'next_tasks': [dict(row) for row in next_tasks],
    }
