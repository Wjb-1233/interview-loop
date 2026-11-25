# 评分校准与学习效果实验材料

本目录是 2026-11-25 准备的材料包。**没有真人评分、没有已招募参与者，也没有训练有效性的实测结论。** 合成回答只用于发现评分边界问题，不能代替真人验证。

| 内容 | 已准备 | 待实际执行 |
|---|---|---|
| 冻结标准 | `calibration/standard.md`、JSON、提示词 hash | 两位评审审核行为锚点 |
| 校准样本 | 8 个题目族、48 份编写回答、四维共 192 行/评审 | 两位评审独立打分 |
| 数据划分 | 开发集 24 份、留出集 24 份；按题目族划分 | 冻结后一次性验收留出集 |
| 迁移题 | 四项能力 × 三档难度 × 三道题；编写草案 | 专家核对、试测等难度 |
| 前后测 | 12 个空白计划槽位、AB/BA 平衡顺序、独立 C 卷 | 自愿招募、实际训练与测量 |
| 设备与性能 | 检查清单、并发脚本、资源和用量采样 | 物理设备与可用上游模型验收 |

所有命令在项目 `backend` 目录运行，使用 `.venv/Scripts/python.exe`。这套工具只读写材料文件，不写入成长看板或业务训练记录。

## 先复制，再采集

本目录保留空白模板。实际填写前复制到被 Git 忽略的 `research/runs/`，例如在项目根目录执行：

```powershell
New-Item -ItemType Directory -Force research/runs | Out-Null
Copy-Item -Recurse research/2026-11-25/calibration research/runs/calibration-01
Copy-Item -Recurse research/2026-11-25/study research/runs/study-01
```

不要把带真人回答的运行目录或评审表提交到仓库。`private` 只交给协调人；不要把整包直接交给评分员。模板里没有账号密钥。

## 两位独立评审校准

1. 协调人阅读 `calibration/questions.json`，审核考察要点、可接受的不同方案、事实性错误及难度。没有人工审核前保持 `AUTHOR_DRAFT`。
2. 分别向 A、B 发放对应的 `rater_a.csv` 或 `rater_b.csv`、`standard.md`。可提供不含回答与编写类型的题目考察点。不得提供模型结果、编写意图标签或另一人的评分。
3. 评审只修改 `human_score`（1–5 整数）和 `note`。分数应根据原话、题型和行为锚点，不根据篇幅或术语数量。信息不足时也按锚点判断，并说明未知；不能补造经历。
4. 协调人在 `raters.json` 填写两位不同评审的匿名编号。A/B 表不得由同一人填写。
5. 先分析开发集。检查逐维 MAE、Spearman、完全一致率、一档内一致率、线性加权 Cohen κ 和分歧 ID。常数或不足样本的相关性/κ 可为 null，不能改写为 100% 一致性。
6. 对分歧进行人工讨论，保留原始两份评分和裁决记录。工具比较模型与 A、模型与 B，**不会自动把均值当作专家金标准**。样本不足或缺分时不输出不完整的一致性结论。

```powershell
.venv/Scripts/python.exe scripts/research.py analyze-calibration --pack ../research/runs/calibration-01 --split development --out ../research/runs/calibration-01/development-report.json
```

需要模型输出时，先确认模型可用。默认只执行 4 个开发样本；这里是原始单题模型评分，未复现完整会话报告的多次采样、客观指标融合和质量闸门，不能称为正式报告准确率。

```powershell
.venv/Scripts/python.exe scripts/research.py score-calibration --pack ../research/runs/calibration-01 --limit 24 --out ../research/runs/calibration-01/private/model-dev-v1.csv
.venv/Scripts/python.exe scripts/research.py analyze-calibration --pack ../research/runs/calibration-01 --model ../research/runs/calibration-01/private/model-dev-v1.csv --out ../research/runs/calibration-01/model-dev-report.json
```

默认输出路径不得覆盖旧模型结果，材料准备命令也不会覆盖已有目录。评分正文、模型名、标准 hash、错误类型及调用耗时会留下记录。401/402/403/429 会停止继续调用。未上报 token 不等同零费用。

调参时只看开发集。冻结评分说明和模型版本后，才通过 `--split holdout --release-holdout --limit 24` 导出留出集结果，再用 `analyze-calibration --split holdout` 分析。留出集若推动了调参，下一轮应另外准备新题，不能继续把已看过的样本称为盲测。

同一题目多种回答、同一回答四个维度具有相关性；不要把 192 行写成 192 个独立受试者。当前 8 个题目族的覆盖也不足以代表所有岗位或难度。

## 前测、训练、后测、迁移

见 [实验执行说明](study/实验执行说明.md) 和 [知情说明模板](study/知情说明模板.md)。`participants.csv` 是 12 个待安排槽位，不是 12 位已参加者；所有实际会话、同意记录、时长和回答留空。

```powershell
# 先完成实际采集，再生成评分员专用的新目录。
.venv/Scripts/python.exe scripts/research.py blind-study --pack ../research/runs/study-01 --out ../research/runs/study-blind-01
# 两位评审填写后；匿名编号填在 blind 目录的 raters.json。
.venv/Scripts/python.exe scripts/research.py analyze-study --pack ../research/runs/study-01 --blind ../research/runs/study-blind-01 --out ../research/runs/study-01/results.json
```

未采集完成时可直接执行 `analyze-study`（省略 `--blind`）检查缺口；只返回待采集状态，不生成提升幅度。统计单位是参与者，报告前后均分差、迁移差、参与者重采样区间。单组设计只能提供探索性变化，不能证明提升由系统造成。

## 新批次与版本

```powershell
.venv/Scripts/python.exe scripts/research.py prepare-calibration --out ../research/runs/new-calibration
.venv/Scripts/python.exe scripts/research.py prepare-study --out ../research/runs/new-study --slots 12
```

新批次冻结当时的标准；旧材料和旧面试不会随代码更新自动改写。研究题面冻结在材料包里。若修改评分标准，保留旧版本结果，并新建批次重新验证。
