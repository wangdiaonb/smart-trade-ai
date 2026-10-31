"""Authenticated company/customer endpoints; no client-selected ownership."""

import csv
import io
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError

from business import CUSTOMER_FIELDS, WorkspaceStore
from business_models import CompanyUpdate, CsvImport, CustomerCreate, CustomerUpdate
from tenancy import TenantContext, require_tenant

router = APIRouter(prefix="/api", tags=["workspace business"])


def get_store(request: Request, tenant: TenantContext = Depends(require_tenant)) -> WorkspaceStore:
    return WorkspaceStore(request.app.state.db_path, tenant)


Store = Annotated[WorkspaceStore, Depends(get_store)]


def found(value):
    if value is None:
        raise HTTPException(404, "Record not found")
    return value


@router.get("/company")
def company(store: Store):
    return found(store.get_company())


@router.put("/company")
def update_company(payload: CompanyUpdate, store: Store):
    return found(store.update_company(payload.model_dump(exclude_unset=True)))


@router.get("/customers")
def list_customers(store: Store, q: str = Query("", max_length=200), tier: Literal["", "A", "B", "C"] = "", country: str = Query("", max_length=200), limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    return store.list_customers(q.strip(), tier, country.strip(), limit, offset)


@router.post("/customers", status_code=201)
def create_customer(payload: CustomerCreate, store: Store):
    return store.create_customer(payload.model_dump(exclude_unset=True))


def spreadsheet_safe(value) -> str:
    value = str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


@router.get("/customers/export")
def export_customers(store: Store, q: str = Query("", max_length=200), tier: Literal["", "A", "B", "C"] = "", country: str = Query("", max_length=200)):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CUSTOMER_FIELDS)
    writer.writeheader()
    for customer in store.export_customers(q.strip(), tier, country.strip()):
        row = {field: customer[field] for field in CUSTOMER_FIELDS}
        row["social_media"] = json.dumps(row["social_media"], ensure_ascii=False)
        writer.writerow({key: spreadsheet_safe(value) for key, value in row.items()})
    return Response(output.getvalue().encode("utf-8-sig"), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="customers.csv"'})


@router.post("/customers/import", status_code=201)
def import_customers(payload: CsvImport, store: Store):
    reader = csv.DictReader(io.StringIO(payload.content.lstrip("\ufeff"), newline=""), strict=True)
    rows = []
    try:
        fields = reader.fieldnames
        if not fields or "name" not in fields or len(fields) != len(set(fields)) or not set(fields) <= set(CUSTOMER_FIELDS):
            raise HTTPException(422, "CSV 表头必须包含 name，且只能使用客户字段")
        for index, row in enumerate(reader, start=2):
            if len(rows) >= 1000:
                raise HTTPException(422, "每次最多导入 1000 行客户")
            if None in row or any(value is None for value in row.values()):
                raise HTTPException(422, f"CSV 第 {index} 行列数不正确")
            values = dict(row)
            if "match_score" in values:
                values["match_score"] = int(values["match_score"] or "0")
            if "social_media" in values:
                values["social_media"] = json.loads(values["social_media"] or "{}")
            try:
                rows.append(CustomerCreate.model_validate(values).model_dump(exclude_unset=True))
            except ValidationError as exc:
                raise HTTPException(422, f"CSV 第 {index} 行无效，请检查姓名、分级和评分") from exc
    except (csv.Error, ValueError) as exc:
        raise HTTPException(422, "CSV 内容无效，请使用 UTF-8 编码和合法字段值") from exc
    if not rows:
        raise HTTPException(422, "CSV 中没有客户数据")
    return {"imported": store.import_customers(rows)}


@router.get("/customers/{customer_id}")
def get_customer(customer_id: int, store: Store):
    return found(store.get_customer(customer_id))


@router.put("/customers/{customer_id}")
def update_customer(customer_id: int, payload: CustomerUpdate, store: Store):
    return found(store.update_customer(customer_id, payload.model_dump(exclude_unset=True)))


@router.delete("/customers/{customer_id}")
def delete_customer(customer_id: int, store: Store):
    if not store.delete_customer(customer_id):
        raise HTTPException(404, "Record not found")
    return {"ok": True}

