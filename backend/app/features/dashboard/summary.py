"""从同条件正式评分整理总结；读取看板不新增模型调用。"""

NEXT_ACTIONS = {
    'logic': '下一次先用一句话给出结论，再说明理由或关键步骤，让每一段都围绕同一个观点展开。',
    'relevance': '下一次先直接回答题目最关心的点，再补一条相关事实；结束前检查有没有答到原问题。',
    'correctness': '按题型补全关键信息：经历题交代职责、行动和结果，知识题说明机制与边界，只补充真实可核实的信息。',
    'concision': '下一次删去重复铺垫，每个观点只保留一条有用的事实，回答后再用一句话收束重点。',
}


def training_summary(recent, averages: dict[str, float], labels: dict[str, str]) -> dict:
    count = len(recent)
    if not count:
        return {
            'sampleCount': 0,
            'text': '当前比较范围内暂无正式评分，暂时不能总结优势、短板或变化。',
            'nextAction': '完成一次场景训练并生成正式评分后，这里会结合成绩和复盘给出总结。',
            'reportSummary': None,
        }
    latest = recent[0][0]
    average = round(sum(item[0].overall_score for item in recent) / count, 1)
    text = f'近 {count} 次同条件正式评分均分 {average:g} 分，最近一次 {latest.overall_score:g} 分。'
    if count < 3:
        text += f'目前只有 {count} 次可比较记录，暂不判断趋势。'
    low, high = min(averages.values()), max(averages.values())
    if high == low:
        text += f'四项能力均分均为 {low:g}/5，没有明显的单一短板。'
        action = '下一次按题型补全关键信息，先直接回答问题，再交代依据和结果或适用边界，最后删去重复铺垫。'
    else:
        stronger = '、'.join(labels[key] for key, score in averages.items() if score == high)
        weaker = '、'.join(labels[key] for key, score in averages.items() if score == low)
        text += f'相对更稳的是{stronger}（{high:g}/5），优先练习{weaker}（{low:g}/5）。'
        focus = next(key for key, score in averages.items() if score == low)
        action = NEXT_ACTIONS[focus]
    report = latest.summary.strip() if isinstance(latest.summary, str) else ''
    return {'sampleCount': count, 'text': text, 'nextAction': action, 'reportSummary': report[:600] or None}
