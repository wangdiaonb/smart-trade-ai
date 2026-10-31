"""Validated app-native tools for chat operations that change business data."""

import json
import re

from pydantic import ValidationError

from business_models import CustomerCreate


class CustomerToolError(Exception):
    pass


CUSTOMER_IMPORT_TOOL = {
    'type': 'function',
    'function': {
        'name': 'import_customers',
        'description': '将先前对话中已经列出的客户批量写入当前公司客户库。只有用户明确要求入库时才能调用。',
        'parameters': {
            'type': 'object',
            'properties': {
                'customers': {
                    'type': 'array',
                    'minItems': 1,
                    'maxItems': 100,
                    'items': {
                        'type': 'object',
                        'properties': {
                            'name': {'type': 'string'},
                            'company_website': {'type': 'string'},
                            'contact': {'type': 'string'},
                            'title': {'type': 'string'},
                            'email': {'type': 'string'},
                            'phone': {'type': 'string'},
                            'whatsapp': {'type': 'string'},
                            'country': {'type': 'string'},
                            'tier': {'type': 'string', 'enum': ['A', 'B', 'C']},
                            'buyer_type': {'type': 'string'},
                            'main_category': {'type': 'string'},
                            'source': {'type': 'string'},
                            'note': {'type': 'string'},
                        },
                        'required': ['name'],
                    },
                },
            },
            'required': ['customers'],
        },
    },
}

CUSTOMER_IMPORT_INSTRUCTION = (
    '用户本轮明确要求把先前对话中的客户写入当前公司客户库。'
    '必须调用 import_customers 工具，只提取对话中已经出现的客户，不得虚构联系人、邮箱或网站；'
    '没有信息的字段留空。'
)

_IMPORT_VERB = r'(写入|保存|导入|加入|放进|存到|存进|添加到|录入)'
_CUSTOMER_LIBRARY = r'(客户库|客户列表|客户管理)'


def wants_customer_import(content: str) -> bool:
    text = content.casefold()
    return bool(
        re.search(f'{_IMPORT_VERB}.{{0,16}}{_CUSTOMER_LIBRARY}', text)
        or re.search(f'{_CUSTOMER_LIBRARY}.{{0,10}}{_IMPORT_VERB}', text)
        or re.search(r'(add|save|import).{0,30}(customer library|customer list)', text)
    )


def _customer_rows(calls: list[dict]) -> list[dict]:
    rows = []
    for call in calls:
        name = call.get('name')
        if name != 'import_customers':
            raise CustomerToolError('模型请求了未知的数据工具，没有写入任何客户。')
        try:
            arguments = json.loads(call.get('arguments') or '')
        except (json.JSONDecodeError, TypeError) as exc:
            raise CustomerToolError('客户数据格式无效，没有写入任何客户。') from exc
        customers = arguments.get('customers') if isinstance(arguments, dict) else None
        if not isinstance(customers, list) or not customers or len(customers) > 100:
            raise CustomerToolError('客户数据为空或超过 100 家，没有写入任何客户。')
        for item in customers:
            if not isinstance(item, dict):
                raise CustomerToolError('客户数据格式无效，没有写入任何客户。')
            values = {key: value for key, value in item.items() if value is not None}
            for alias, field in (
                ('website', 'company_website'),
                ('website_url', 'company_website'),
                ('phone_number', 'phone'),
                ('contact_phone', 'phone'),
                ('category', 'main_category'),
                ('type', 'buyer_type'),
            ):
                if alias in values and field not in values:
                    values[field] = values.pop(alias)
            if not values.get('source'):
                values['source'] = 'AI 对话检索'
            try:
                rows.append(CustomerCreate.model_validate(values).model_dump(exclude_unset=True))
            except ValidationError as exc:
                raise CustomerToolError('客户字段校验失败，没有写入任何客户。请检查名称、分级和联系方式。') from exc
    return rows


def execute_customer_import(store, calls: list[dict]) -> tuple[list[dict], dict, str]:
    rows = _customer_rows(calls)
    result = store.import_customers_deduplicated(rows)
    counts = {tier: sum(1 for row in rows if row.get('tier') == tier) for tier in ('A', 'B', 'C')}
    breakdown = '、'.join(f'{tier}级{count}家' for tier, count in counts.items() if count)
    summary = f'已写入 {result["created"]} 家客户'
    summary += f'（{breakdown}）' if breakdown else ''
    summary += '。'
    if result['skipped']:
        summary += f'已跳过重复 {result["skipped"]} 家。'
    summary += '公开联系方式仍建议逐条核验后再发送开发信。'
    return rows, result, summary
