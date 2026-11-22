"""保守识别口头语；单字语气词须独立出现，避免命中“名额、金额”等正常词。"""
import re


def count_fillers(text: str, words) -> dict[str, int]:
    counts = {}
    for word in words:
        if len(word) == 1:
            matches = re.findall(r'(?<![\w])' + re.escape(word) + r'+(?![\w])', text)
            count = sum(len(match) for match in matches)
        else:
            count = text.count(word)
        if count:
            counts[word] = count
    return counts
