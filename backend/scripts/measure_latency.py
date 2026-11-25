"""A-03：实测训练链路的响应延迟，输出 p50/p95。

测两件事：
1. 文字模式：从提交回答到首个 token、到整轮结束；
2. 语音模式（本地管线）：从说完最后一个音频包到面试官首个文字片段。

用法（后端需在 8081 运行）：
    python scripts/measure_latency.py --rounds 6 --out docs/延迟实测.md
    python scripts/measure_latency.py --text-only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.load_test import run_virtual_user, percentile as interpolated_percentile

BASE = "http://127.0.0.1:8081/api/v1"
SAMPLE_RATE = 16000
CHUNK = 640  # 20ms @16kHz s16le


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    return interpolated_percentile(values, pct / 100)


def summarize(name: str, values: list[float]) -> dict:
    if not values:
        return {"name": name, "count": 0}
    return {
        "name": name,
        "count": len(values),
        "p50": round(percentile(values, 50), 2),
        "p95": round(percentile(values, 95), 2),
        "mean": round(statistics.fmean(values), 2),
        "max": round(max(values), 2),
    }


async def ensure_user(client: httpx.AsyncClient) -> dict[str, str]:
    email = f"latency-{time.time_ns()}@example.com"
    response = await client.post(
        "/auth/register",
        json={"email": email, "password": "LatencyTest123", "displayName": "延迟实测", "consent": True},
    )
    response.raise_for_status()
    token = response.json()["data"]["accessToken"]
    return {"Authorization": f"Bearer {token}"}


async def measure_text(client: httpx.AsyncClient, headers: dict[str, str], rounds: int) -> tuple[list[dict], None]:
    scenes = (await client.get("/scenes", headers=headers, params={"size": 3})).json()["data"]
    samples = []
    start = asyncio.Event()
    start.set()
    for index in range(rounds):
        result = await run_virtual_user(index + 1, start=start, client=client,
            token=headers['Authorization'].removeprefix('Bearer '), scene_id=scenes[0]['id'],
            message='我负责课程项目的接口设计，用并发测试验证业务约束，尚未验证生产环境表现。')
        if not result.cleanup_success:
            raise RuntimeError('临时训练未清理成功，请检查测试环境')
        samples.append({'round': index + 1, 'first_token_ms': result.first_token_ms,
                        'total_ms': result.total_response_ms, 'success': result.success,
                        'degraded': result.degraded, 'cleanupSuccess': result.cleanup_success})
    return samples, None


async def tts_pcm(text: str) -> bytes:
    """用项目自己的 TTS 生成一段语音，再转成 16k s16le，模拟用户说话。"""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.infrastructure.narration import synthesize_slide

    import imageio_ffmpeg
    with tempfile.TemporaryDirectory(prefix='career-coach-latency-') as directory:
        audio, _, _ = synthesize_slide(text, Path(directory), 0, style="tutor")
        raw = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(audio), "-f", "s16le", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", "-"],
            capture_output=True, check=True)
        return raw.stdout


async def measure_voice(rounds: int, scene_id: str, client: httpx.AsyncClient, headers: dict) -> list[dict]:
    """先跑一轮预热（Whisper 首次加载），再计时 rounds 轮。"""
    import websockets

    pcm = await tts_pcm("你好，我先做个自我介绍。我之前负责订单系统的性能优化，把接口延迟从八百毫秒降到了两百毫秒。")
    if len(pcm) < CHUNK * 10:
        return []

    samples = []
    response = await client.post('/voice/ws-ticket', headers=headers)
    response.raise_for_status()
    ticket = response.json()['data']['ticket']
    uri = 'ws://127.0.0.1:8081/api/v1/voice/ws/pipeline?' + urlencode({'sceneId': scene_id, 'ticket': ticket})
    async with websockets.connect(uri, max_size=None) as socket:
        # The opening question is not a response to the benchmark utterance.
        async with asyncio.timeout(30):
            while True:
                opening = await socket.recv()
                if isinstance(opening, str) and json.loads(opening).get('type') == 'assistant_end':
                    break
        for index in range(rounds + 1):
            # 发送语音，尽量贴近实时节奏
            for offset in range(0, len(pcm), CHUNK):
                await socket.send(pcm[offset:offset + CHUNK])
                await asyncio.sleep(0.02)
            speech_end = time.perf_counter()
            # 0.5 秒静音，让 VAD 判定说完
            for _ in range(25):
                await socket.send(b"\x00" * CHUNK)
                await asyncio.sleep(0.02)
            first_reply = None
            deadline = time.perf_counter() + 30
            while time.perf_counter() < deadline:
                try:
                    message = await asyncio.wait_for(socket.recv(), timeout=10)
                except asyncio.TimeoutError:
                    break
                if isinstance(message, bytes):
                    continue
                payload = json.loads(message)
                if payload.get("type") == "assistant_delta" and first_reply is None:
                    first_reply = (time.perf_counter() - speech_end) * 1000
                if payload.get("type") == "assistant_end":
                    break
            if index == 0:
                continue  # 预热轮不计入
            if first_reply:
                samples.append({"round": index, "first_reply_ms": round(first_reply, 1)})
            else:
                samples.append({"round": index, "first_reply_ms": None, "timeout": True})
    return samples


def render_markdown(result: dict) -> str:
    lines = [
        "# 延迟实测（A-03）",
        "",
        f"> 生成时间：{result['generatedAt']}　样本：{result['rounds']} 轮/链路　执行标记：{result['executionLabel']}",
        "",
        "## 结果",
        "",
        "| 指标 | 样本数 | p50 | p95 | 平均 | 最大 |",
        "|---|---|---|---|---|---|",
    ]
    for item in result["metrics"]:
        if not item.get("count"):
            lines.append(f"| {item['name']} | 0 | — | — | — | — |")
            continue
        lines.append(
            f"| {item['name']} | {item['count']} | {item['p50']} ms | {item['p95']} ms | {item['mean']} ms | {item['max']} ms |"
        )
    lines += [
        "",
        "## 说明",
        "",
        "- 文字指标：从提交回答到 SSE 首个 token / 整轮结束，含模型排队与网络往返。",
        "- 语音指标：本地管线（Silero VAD → faster-whisper → DeepSeek → TTS），从最后一个音频包到面试官首个字幕片段。",
        "- 首轮作为预热，不计入上表；失败、降级和无首 token 见原始样本，不用整轮耗时冒充首 token。",
        "- 这些是**本次实测量**，不是产品承诺；换机器、换网络、换模型都会变。",
        "",
        "## 原始样本",
        "",
        "```json",
        json.dumps(result["samples"], ensure_ascii=False, indent=2)[:4000],
        "```",
        "",
    ]
    return "\n".join(lines)


async def collect_measurements(client, headers, args):
    text_samples, _ = await measure_text(client, headers, args.rounds)
    samples = {"text": text_samples}
    valid = [item for item in text_samples[1:] if item['success'] and not item['degraded']]
    metrics = [
        summarize('文字 · 首 token', [item['first_token_ms'] for item in valid if item.get('first_token_ms')]),
        summarize('文字 · 整轮回复', [item['total_ms'] for item in valid if item.get('total_ms')])]
    if not args.text_only:
        scenes = (await client.get('/scenes', headers=headers)).json()['data']
        try:
            voice_samples = await measure_voice(args.rounds, scenes[0]['id'], client, headers)
            samples['voice'] = voice_samples
            metrics.append(summarize('语音 · 说完到首个回应', [item['first_reply_ms'] for item in voice_samples if item.get('first_reply_ms')]))
        except Exception as exc:
            samples['voice_error'] = type(exc).__name__
            metrics.append({'name': '语音 · 说完到首个回应', 'count': 0})
    return samples, metrics


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--rounds', type=int, default=5)
    parser.add_argument('--text-only', action='store_true')
    parser.add_argument('--out', default='docs/延迟实测.md')
    parser.add_argument('--label', default='UNSPECIFIED')
    args = parser.parse_args()
    if not 2 <= args.rounds <= 10:
        parser.error('--rounds 必须为 2–10；首轮预热')
    async with httpx.AsyncClient(base_url=BASE, timeout=120, trust_env=False) as client:
        headers = await ensure_user(client)
        try:
            samples, metrics = await collect_measurements(client, headers, args)
        finally:
            deleted = await client.request('DELETE', '/auth/me/delete', headers=headers,
                                           json={'password': 'LatencyTest123', 'confirm': '注销'})
            deleted.raise_for_status()

    result = {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        'executionLabel': args.label,
        "rounds": args.rounds,
        "temporaryAccountDeleted": True,
        "metrics": metrics,
        "samples": samples,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(result), encoding="utf-8")
    json_path = out.with_suffix(".json")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"已写入 {out} 与 {json_path}")


if __name__ == "__main__":
    asyncio.run(main())
