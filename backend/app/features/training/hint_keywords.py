"""提示卡关键词：从当前问题切名词性片段，场景固定标签只做兜底。

项目没有分词依赖，切分只依赖标点与功能词边界，因此每个保留下来的片段都是完整的
语义单元：宁可少取一个词，也不把「增长和留存冲」这种被截断的残词放进提示卡。
"""

from __future__ import annotations

import re
from collections.abc import Sequence

MAX_KEYWORDS = 6
QUESTION_TERM_LIMIT = 4
SCENE_TERM_LIMIT = 2
MIN_LENGTH = 2
# 题目关键词不足这个数时，先补维度词，保证提示卡还贴着评分维度
MIN_KEYWORDS = 3

# 疑问词与功能词：出现的位置就是切分边界，本身不进关键词
_STOPWORDS = (
    "为什么", "怎么办", "怎么样", "什么", "怎么", "如何", "哪些", "哪个", "多少",
    "是否", "以及", "还是", "或者", "就是", "会不会", "能不能", "可不可以", "如果",
    "那么", "这个", "那个", "一个", "一下", "一些", "你们", "我们", "他们", "自己",
    "介绍", "说说", "谈谈", "讲讲", "请",
    "的", "了", "和", "与", "及", "在", "是", "吗", "呢", "吧", "啊", "你", "您",
    "我", "他", "她", "它", "们", "把", "被",
)
_STOPWORD_RE = re.compile("|".join(sorted((re.escape(item) for item in _STOPWORDS), key=len, reverse=True)))
# 片段首尾的虚词与时间/方位词：去掉它们才留下名词性子串（「留存冲突时」→「留存冲突」）
_EDGE_CHARS = "的了和与及在是时后前中上下里呢吗吧啊你您我他她它们个些更把被"
# 片段尾部的动词残留（「复盘出」→「复盘」）：只在片段还剩 3 字以上时削，避免削掉「产出」
_TRAILING_VERBS = "出掉起到说完做看想管去来"
_SEGMENT_RE = re.compile(r"[，。！？；：、,.?!;:\s()（）\[\]【】《》“”\"'`‘’「」/\\|—~·]+")
_EN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#.]*")
_EN_STOPWORDS = frozenset(
    """
    a an the of to in on at for with about and or but is are was were be been being
    do does did you your me my we our i it its this that these those tell describe give
    can could would should will what how why when which who whom whose time times some any
    there here have has had not
    """.split()
)

# 维度兜底词：题目本身切不出足够关键词时，用评分维度对应的答题抓手补位
_DIMENSION_TERMS: dict[str, tuple[str, ...]] = {
    "内容与逻辑": ("结论", "依据"),
    "贴合问题": ("问题要点",),
    "信息完整": ("背景", "结果"),
    "表达干净": ("结论先行",),
}


def _subsumed(terms: Sequence[str], candidate: str) -> bool:
    """候选与已有词互为子串（增长 / 增长与留存）时只保留一个，避免同义堆叠。"""
    lowered = candidate.lower()
    for term in terms:
        current = term.lower()
        if lowered in current or current in lowered:
            return True
    return False


def _append(terms: list[str], candidate: str) -> bool:
    if _subsumed(terms, candidate):
        return False
    terms.append(candidate)
    return True


def _english_terms(segment: str) -> list[str]:
    terms = []
    for match in _EN_WORD_RE.findall(segment):
        word = match.strip(".")
        # DAU / ARPU 这类缩写保留原大小写，只丢掉不足两字符的噪声
        if len(word) < MIN_LENGTH or word.lower() in _EN_STOPWORDS:
            continue
        terms.append(word)
    return terms


def _chinese_terms(segment: str) -> list[str]:
    terms = []
    for chunk in _STOPWORD_RE.split(segment):
        chunk = chunk.strip(_EDGE_CHARS)
        while len(chunk) > MIN_LENGTH and chunk[-1] in _TRAILING_VERBS:
            chunk = chunk[:-1].strip(_EDGE_CHARS)
        chunk = chunk.strip()
        if not re.search(r"[\u4e00-\u9fa5]", chunk):
            continue
        if len(chunk) < MIN_LENGTH:
            continue
        terms.append(chunk)
    return terms


def extract_terms(question: str, limit: int = QUESTION_TERM_LIMIT) -> list[str]:
    """按标点与功能词把问题切成片段，返回前 limit 个名词性片段。"""
    terms: list[str] = []
    for segment in _SEGMENT_RE.split(question or ""):
        if not segment.strip():
            continue
        for term in _english_terms(segment) + _chinese_terms(segment):
            if _append(terms, term) and len(terms) >= limit:
                return terms
    return terms


def _clean_label(label: str | None) -> str:
    text = re.sub(r"\s*/\s*", "/", (label or "").strip())
    text = re.sub(r"\s+", " ", text).strip(_EDGE_CHARS + " /")
    return text if len(re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5]", "", text)) >= MIN_LENGTH else ""


def build_hint_keywords(
    question: str,
    *,
    dimension: str = "",
    scene_terms: Sequence[str | None] = (),
) -> list[str]:
    """题目关键词优先（<=4），不足时补维度词，场景固定标签最后兜底且最多 2 个。"""
    keywords = extract_terms(question)
    for term in _DIMENSION_TERMS.get(dimension or "", ()):
        if len(keywords) >= MIN_KEYWORDS:
            break
        _append(keywords, term)
    used = 0
    for label in scene_terms:
        if used >= SCENE_TERM_LIMIT or len(keywords) >= MAX_KEYWORDS:
            break
        cleaned = _clean_label(label)
        if not cleaned:
            continue
        if _append(keywords, cleaned):
            used += 1
    return keywords[:MAX_KEYWORDS]
