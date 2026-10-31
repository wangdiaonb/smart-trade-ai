"""Validated public business fields. Ownership fields are deliberately excluded."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
LongText = Annotated[str, StringConstraints(max_length=20000)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class BusinessInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def reject_explicit_null(cls, value):
        if value is None:
            raise ValueError("请填写有效值；清空文字请使用空字符串")
        return value


class CompanyUpdate(BusinessInput):
    name: Name | None = None
    website: ShortText | None = None
    contact_name: ShortText | None = None
    contact_email: ShortText | None = None
    address: ShortText | None = None
    industry: ShortText | None = None
    products: LongText | None = None
    target_region: ShortText | None = None
    agent_identity_md: LongText | None = None


class CustomerUpdate(BusinessInput):
    name: Name | None = None
    contact: ShortText | None = None
    note: LongText | None = None
    country: ShortText | None = None
    tier: Literal["", "A", "B", "C"] | None = None
    linkedin_url: ShortText | None = None
    company_website: ShortText | None = None
    social_media: dict[str, ShortText] | None = Field(None, max_length=20)
    title: ShortText | None = None
    email: ShortText | None = None
    backup_email: ShortText | None = None
    phone: ShortText | None = None
    whatsapp: ShortText | None = None
    wechat: ShortText | None = None
    source: ShortText | None = None
    buyer_type: ShortText | None = None
    follow_up_note: LongText | None = None
    main_category: ShortText | None = None
    match_score: int | None = Field(None, ge=0, le=5, strict=True)


class CustomerCreate(CustomerUpdate):
    name: Name


class CsvImport(BusinessInput):
    content: str = Field(min_length=1, max_length=2_000_000)

