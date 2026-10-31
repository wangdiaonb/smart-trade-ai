"""Workspace-scoped persistence for company profiles and customer records."""

import json
import re
from pathlib import Path

from database import connection
from tenancy import TenantContext

COMPANY_FIELDS = frozenset(("name", "website", "contact_name", "contact_email", "address", "industry", "products", "target_region", "agent_identity_md"))
CUSTOMER_FIELDS = (
    "name", "contact", "note", "country", "tier", "linkedin_url", "company_website",
    "social_media", "title", "email", "backup_email", "phone", "whatsapp", "wechat",
    "source", "buyer_type", "follow_up_note", "main_category", "match_score",
)


def _decode_customer(row):
    if row is None:
        return None
    result = dict(row)
    result["social_media"] = json.loads(result["social_media"])
    return result


class WorkspaceStore:
    def __init__(self, path: Path, tenant: TenantContext):
        self.path = path
        self.workspace_id = tenant.workspace_id
        self.company_id = tenant.company_id

    def get_company(self) -> dict | None:
        with connection(self.path) as conn:
            row = conn.execute("SELECT * FROM companies WHERE workspace_id = ? AND id = ?", (self.workspace_id, self.company_id)).fetchone()
        return dict(row) if row is not None else None

    def update_company(self, values: dict) -> dict | None:
        if not values.keys() <= COMPANY_FIELDS:
            raise ValueError("Unsupported company fields")
        if values:
            assignments = ", ".join(f"{field} = ?" for field in values)
            with connection(self.path) as conn:
                conn.execute(
                    f"UPDATE companies SET {assignments}, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE workspace_id = ? AND id = ?",
                    (*values.values(), self.workspace_id, self.company_id),
                )
                if "name" in values:
                    conn.execute("UPDATE workspaces SET name = ? WHERE id = ?", (values["name"], self.workspace_id))
        return self.get_company()

    def _customer_filters(self, q="", tier="", country=""):
        predicates = ["workspace_id = ?", "company_id = ?"]
        params = [self.workspace_id, self.company_id]
        if q:
            escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            predicates.append("(name LIKE ? ESCAPE '\\' OR contact LIKE ? ESCAPE '\\' OR email LIKE ? ESCAPE '\\' OR note LIKE ? ESCAPE '\\')")
            params.extend([f"%{escaped}%"] * 4)
        if tier:
            predicates.append("tier = ?")
            params.append(tier)
        if country:
            predicates.append("country = ?")
            params.append(country)
        return " AND ".join(predicates), params

    def list_customers(self, q="", tier="", country="", limit=50, offset=0) -> dict:
        where, params = self._customer_filters(q, tier, country)
        with connection(self.path) as conn:
            total = conn.execute(f"SELECT count(*) FROM customers WHERE {where}", params).fetchone()[0]
            rows = conn.execute(f"SELECT * FROM customers WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
        return {"items": [_decode_customer(row) for row in rows], "total": total}

    def export_customers(self, q="", tier="", country="") -> list[dict]:
        where, params = self._customer_filters(q, tier, country)
        with connection(self.path) as conn:
            rows = conn.execute(f"SELECT * FROM customers WHERE {where} ORDER BY id DESC", params).fetchall()
        return [_decode_customer(row) for row in rows]

    def get_customer(self, customer_id: int) -> dict | None:
        with connection(self.path) as conn:
            row = conn.execute("SELECT * FROM customers WHERE id = ? AND workspace_id = ? AND company_id = ?", (customer_id, self.workspace_id, self.company_id)).fetchone()
        return _decode_customer(row)

    def _insert_customer(self, conn, values):
        if not values.keys() <= set(CUSTOMER_FIELDS):
            raise ValueError("Unsupported customer fields")
        if self.company_id is None:
            raise ValueError("Company not found")
        values = dict(values)
        if "social_media" in values:
            values["social_media"] = json.dumps(values["social_media"], ensure_ascii=False)
        fields = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        cursor = conn.execute(
            f"INSERT INTO customers(workspace_id, company_id, {fields}) VALUES (?, ?, {placeholders})",
            (self.workspace_id, self.company_id, *values.values()),
        )
        return cursor.lastrowid

    def create_customer(self, values: dict) -> dict:
        with connection(self.path) as conn:
            customer_id = self._insert_customer(conn, values)
        return self.get_customer(customer_id)

    def import_customers(self, rows: list[dict]) -> int:
        with connection(self.path) as conn:
            for values in rows:
                self._insert_customer(conn, values)
        return len(rows)

    def import_customers_deduplicated(self, rows: list[dict]) -> dict:
        created_names = []
        skipped_names = []
        with connection(self.path) as conn:
            existing = conn.execute(
                'SELECT name,company_website,email,phone FROM customers WHERE workspace_id=? AND company_id=?',
                (self.workspace_id, self.company_id),
            ).fetchall()
            names = {str(row['name']).strip().casefold() for row in existing}
            websites = {str(row['company_website']).strip().casefold().rstrip('/') for row in existing if row['company_website']}
            emails = {str(row['email']).strip().casefold() for row in existing if row['email']}
            phones = {re.sub(r'\D', '', str(row['phone'])) for row in existing if row['phone']}
            for values in rows:
                name = str(values['name']).strip()
                website = str(values.get('company_website') or '').strip().casefold().rstrip('/')
                email = str(values.get('email') or '').strip().casefold()
                phone = re.sub(r'\D', '', str(values.get('phone') or ''))
                duplicate = (
                    (bool(website) and website in websites)
                    or (bool(email) and email in emails)
                    or (bool(phone) and phone in phones)
                    or (not website and not email and not phone and name.casefold() in names)
                )
                if duplicate:
                    skipped_names.append(name)
                    continue
                self._insert_customer(conn, values)
                created_names.append(name)
                names.add(name.casefold())
                if website:
                    websites.add(website)
                if email:
                    emails.add(email)
                if phone:
                    phones.add(phone)
        return {
            'created': len(created_names),
            'skipped': len(skipped_names),
            'created_names': created_names,
            'skipped_names': skipped_names,
        }

    def update_customer(self, customer_id: int, values: dict) -> dict | None:
        if not values.keys() <= set(CUSTOMER_FIELDS):
            raise ValueError("Unsupported customer fields")
        if values:
            values = dict(values)
            if "social_media" in values:
                values["social_media"] = json.dumps(values["social_media"], ensure_ascii=False)
            assignments = ", ".join(f"{field} = ?" for field in values)
            with connection(self.path) as conn:
                cursor = conn.execute(
                    f"UPDATE customers SET {assignments}, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id = ? AND workspace_id = ? AND company_id = ?",
                    (*values.values(), customer_id, self.workspace_id, self.company_id),
                )
                if cursor.rowcount == 0:
                    return None
        return self.get_customer(customer_id)

    def delete_customer(self, customer_id: int) -> bool:
        with connection(self.path) as conn:
            conn.execute('BEGIN IMMEDIATE')
            has_orders = conn.execute('SELECT 1 FROM orders WHERE customer_id = ? AND workspace_id = ? AND company_id = ? LIMIT 1', (customer_id, self.workspace_id, self.company_id)).fetchone()
            if has_orders:
                raise ValueError('该客户仍有关联订单，请先处理订单，不能直接删除客户。')
            cursor = conn.execute("DELETE FROM customers WHERE id = ? AND workspace_id = ? AND company_id = ?", (customer_id, self.workspace_id, self.company_id))
        return cursor.rowcount > 0

