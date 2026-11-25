# 延迟实测（A-03）

> 生成时间：2026-11-25 15:14　样本：3 轮/链路　执行标记：CONTROLLED_STUB

## 结果

| 指标 | 样本数 | p50 | p95 | 平均 | 最大 |
|---|---|---|---|---|---|
| 文字 · 首 token | 2 | 508.3 ms | 525.49 ms | 508.3 ms | 527.4 ms |
| 文字 · 整轮回复 | 2 | 630.31 ms | 648.96 ms | 630.31 ms | 651.03 ms |

## 说明

- 文字指标：从提交回答到 SSE 首个 token / 整轮结束，含模型排队与网络往返。
- 语音指标：本地管线（Silero VAD → faster-whisper → DeepSeek → TTS），从最后一个音频包到面试官首个字幕片段。
- 首轮作为预热，不计入上表；失败、降级和无首 token 见原始样本，不用整轮耗时冒充首 token。
- 这些是**本次实测量**，不是产品承诺；换机器、换网络、换模型都会变。

## 原始样本

```json
{
  "text": [
    {
      "round": 1,
      "first_token_ms": 430.99,
      "total_ms": 555.17,
      "success": true,
      "degraded": false,
      "cleanupSuccess": true
    },
    {
      "round": 2,
      "first_token_ms": 489.21,
      "total_ms": 609.59,
      "success": true,
      "degraded": false,
      "cleanupSuccess": true
    },
    {
      "round": 3,
      "first_token_ms": 527.4,
      "total_ms": 651.03,
      "success": true,
      "degraded": false,
      "cleanupSuccess": true
    }
  ]
}
```
