"""Conservative context checks for lightweight coaching labels."""
import re

REPEAT_PATTERN = re.compile(r"(再说(一遍|一次)|没听清|没听懂|重复(一下|一遍)?|能再说|pardon|repeat|say that again|didn'?t catch)", re.IGNORECASE)


REPEAT_TAIL_FILLERS = "？?。.!！一下遍次吗呢可以好谢你了，,、 　"

def is_repeat_request(text: str) -> bool:
    value = (text or "").strip()
    if len(value) > 40:
        return False
    if re.fullmatch(r"(Could you )?(repeat that|pardon|say that again)[?.! ]*", value, re.IGNORECASE):
        return True
    # 逐个候选判断：像「没听清，能再说一遍吗？」这种，最左匹配「没听清」后面还挂着内容，
    # 只看最左匹配会漏判；只要有一处候选之后只剩语气词，就当重复请求。
    for match in REPEAT_PATTERN.finditer(value):
        if not value[match.end():].strip(REPEAT_TAIL_FILLERS):
            return True
    return False


def affirmative_occurrences(text: str, pattern) -> int:
    compiled = re.compile(re.escape(pattern)) if isinstance(pattern, str) else pattern
    count = 0
    for match in compiled.finditer(text or ""):
        prefix = text[max(0, match.start() - 14):match.start()]
        suffix = text[match.end():match.end() + 10]
        if re.search(r"(?:不(?:会|该|能|要|再|应该)?|没(?:有)?|并非|从不)[‘'\"“]?\s*$", prefix):
            continue
        if re.search(r"(?:避免|拒绝|反对|不能说|不会说|不应该说).{0,6}$", prefix):
            continue
        if re.search(r"^[’'\"”]?\s*(?:是错误|是不对|不合适|不应该)", suffix):
            continue
        if re.search(r"^[’'\"”]?\s*(?:吗|么)", suffix):
            # 疑问/确认语气（“这个话题不关我的事吗？”）是在提问，不是推卸责任
            continue
        count += 1
    return count


def constructive_uncertainty(text: str) -> bool:
    return bool(re.search(r"不知道|不确定|不了解|未(?:实操|验证)|不能(?:直接)?(?:承诺|确定)", text)
                and re.search(r"(?:先|需要|会|可以).{0,12}(?:查|核实|确认|验证|测试)|验证步骤", text))
