import json

import pytest

from app.infrastructure.llm import LlmGateway


PAYLOAD = {'summary': '他说“我负责接口”，使用 "Redis"，路径 C:\\data。', 'observations': []}


@pytest.mark.parametrize('wrapper', ['plain', 'markdown', 'prose', 'encoded', 'escaped'])
def test_json_provider_envelopes_preserve_original_content(wrapper):
    raw = json.dumps(PAYLOAD, ensure_ascii=False, indent=2)
    if wrapper == 'markdown':
        raw = '```json\n' + raw + '\n```'
    elif wrapper == 'prose':
        raw = '结果如下：\n' + raw
    elif wrapper == 'encoded':
        raw = json.dumps(raw, ensure_ascii=False)
    elif wrapper == 'escaped':
        raw = json.dumps(raw, ensure_ascii=False)[1:-1]
    assert LlmGateway._parse_json(raw) == PAYLOAD


@pytest.mark.parametrize('raw', ['{"unfinished":', '[1,2]', '{broken}', '{\\"unfinished\\":'])
def test_invalid_or_truncated_json_is_not_silently_repaired(raw):
    with pytest.raises(ValueError):
        LlmGateway._parse_json(raw)
