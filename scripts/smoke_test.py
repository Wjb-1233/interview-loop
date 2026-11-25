"""上线冒烟测试：不依赖测试库，直接打真实服务，检查关键链路是否可用。

用法：
    python scripts/smoke_test.py --base https://your-domain.com
    python scripts/smoke_test.py --base http://127.0.0.1:8081 --api-only

退出码 0 表示全部通过，非 0 表示有检查项失败（可直接放进部署脚本）。
"""

from __future__ import annotations

import argparse
import random
import string
import sys
from datetime import datetime

import httpx

# 模型调用与三采样评分都在这条链路上，超时要给足
TIMEOUT = 120.0


def _force_utf8() -> None:
    """Windows 控制台默认 GBK，中文与符号会崩。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


class Smoke:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.client = httpx.Client(base_url=self.base, timeout=TIMEOUT, trust_env=False, follow_redirects=True)
        self.results: list[tuple[str, bool, str]] = []
        self.temporary_token: str | None = None

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.results.append((name, ok, detail))
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}{(' · ' + detail) if detail else ''}")

    def login(self, api: str) -> str | None:
        """只创建本次测试自己的账号，结束后注销，不依赖已移除的演示登录。"""
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        register = self.client.post(
            f"{api}/auth/register",
            json={
                "email": f"smoke-{suffix}@example.com",
                "password": "SmokeTest12345!",
                "displayName": "冒烟测试",
                "consent": True,
            },
            headers={"Referer": self.base + "/"},
        )
        if register.status_code in (200, 201):
            self.check("登录（临时账号）", True)
            self.temporary_token = register.json()["data"]["accessToken"]
            return self.temporary_token
        self.check("登录", False, f"register={register.status_code}")
        return None

    def run(self) -> int:
        try:
            self._run_checks()
        except Exception as exc:
            self.check("冒烟请求", False, type(exc).__name__)
        finally:
            if self.temporary_token:
                api = self.base if self.base.endswith("/api/v1") else self.base + "/api/v1"
                try:
                    deleted = self.client.request("DELETE", f"{api}/auth/me/delete",
                        json={"password": "SmokeTest12345!", "confirm": "注销"},
                        headers={"Authorization": f"Bearer {self.temporary_token}", "Referer": self.base + "/"})
                    self.check("清理临时账号与测试记录", deleted.status_code == 200)
                except Exception as exc:
                    self.check("清理临时账号与测试记录", False, type(exc).__name__)
            self.client.close()
        return self.summary()

    def _run_checks(self) -> None:
        api = self.base if self.base.endswith("/api/v1") else f"{self.base}/api/v1"

        health = self.client.get(f"{api}/health")
        self.check("健康检查", health.status_code == 200 and health.json().get("data", {}).get("status") == "ok")

        ready = self.client.get(f"{api}/ready")
        payload = ready.json().get("data", {}) if ready.status_code in (200, 503) else {}
        checks = payload.get("checks", {})
        self.check(
            "就绪检查",
            ready.status_code == 200,
            f"database={checks.get('database')} llm={checks.get('llm')} rateLimit={checks.get('rateLimit')}",
        )

        token = self.login(api)
        if not token:
            return

        auth = {"Authorization": f"Bearer {token}", "Referer": self.base + "/"}

        scenes = self.client.get(f"{api}/scenes", params={"size": 3}, headers=auth)
        items = scenes.json().get("data", []) if scenes.status_code == 200 else []
        self.check("场景列表", scenes.status_code == 200 and len(items) > 0, f"{len(items)} 个")

        if items:
            created = self.client.post(f"{api}/training-sessions", json={"sceneId": items[0]["id"]}, headers=auth)
            session_id = created.json().get("data", {}).get("id") if created.status_code == 201 else None
            self.check("创建训练会话", created.status_code == 201, f"HTTP {created.status_code}")

            if session_id:
                # 两轮满足正式成长统计的样本门槛。
                answers = [
                    "我负责过一个订单系统优化，把接口 P99 从 800ms 降到 200ms。",
                    "排查时先用链路追踪定位慢查询，再加缓存并补了压测回归。",
                ]
                for index, text in enumerate(answers):
                    reply = self.client.post(
                        f"{api}/training-sessions/{session_id}/messages/complete",
                        json={"content": text},
                        headers=auth,
                    )
                    self.check(f"提交回答 {index + 1}", reply.status_code == 200, f"HTTP {reply.status_code}")

                finished = self.client.post(
                    f"{api}/training-sessions/{session_id}/finish",
                    params={"create_plan": "false"},
                    headers=auth,
                )
                self.check("结束并评分", finished.status_code == 200, f"HTTP {finished.status_code}")

                report = self.client.get(f"{api}/evaluations/{session_id}", headers=auth)
                self.check("读取报告", report.status_code == 200, f"HTTP {report.status_code}")

        if not self.base.endswith("/api/v1"):
            page = self.client.get("/")
            self.check("前端页面", page.status_code == 200 and 'id="app"' in page.text, f"HTTP {page.status_code}")


    def summary(self) -> int:
        failed = [item for item in self.results if not item[1]]
        print("\n" + "=" * 48)
        print(f"共 {len(self.results)} 项，失败 {len(failed)} 项 · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        for name, _, detail in failed:
            print(f"  [x] {name} {detail}")
        return 0 if not failed else 1


def main() -> None:
    _force_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8081")
    parser.add_argument("--api-only", action="store_true", help="跳过前端首页检查")
    args = parser.parse_args()
    base = args.base if not args.api_only else (args.base if args.base.endswith("/api/v1") else args.base + "/api/v1")
    sys.exit(Smoke(base).run())


if __name__ == "__main__":
    main()
