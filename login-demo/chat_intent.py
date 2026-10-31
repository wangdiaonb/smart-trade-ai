"""Small, deterministic routing rules for conversational chat requests."""

import re


_CONTINUATION = re.compile(
    r'^(请)?(继续|接着|然后|往下|接着说|继续说|继续写|接着写|continue|goon|keepgoing)',
    re.IGNORECASE,
)
_TOOL_INTENT = re.compile(
    r'(查|搜索|检索|浏览|网页|官网|链接|文件|下载|抓取|打开|'
    r'search|browse|website|url|file|download|fetch)',
    re.IGNORECASE,
)


def is_plain_continuation(content: str) -> bool:
    text = str(content or '').strip()
    if not text or len(text) > 40 or _TOOL_INTENT.search(text):
        return False
    compact = re.sub(r'[\s，。！？,.!?;；:：]+', '', text)
    return bool(_CONTINUATION.match(compact))
