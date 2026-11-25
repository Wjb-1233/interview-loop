# 系统架构

## 关键决策

1. 采用按功能域组织的模块化单体，便于独立测试各业务模块和后续拆分。
2. Vue 客户端通过版本化 REST API 读写业务数据；文字页面使用完整回复接口，SSE 供流式客户端与压测使用，实时语音/视频使用 WebSocket。
3. LangGraph `StateGraph` 将对话阶段编排为 `OPENING → DISCOVERY → CHALLENGE → CLOSING`；训练完成由独立的 `ACTIVE / FINISHED` 状态表达，报告生成另有生命周期，最多 12 轮。
4. DeepSeek、豆包、通义千问通过统一 OpenAI 兼容客户端接入；上游异常时切换本地教练模板。
5. 业务数据按用户 ID 隔离，管理员端通过 RBAC 放行。
6. MySQL 保存业务数据与训练进度；Redis 仅承担限流；SQLite/内存限流仅供测试或离线演示。
7. API 使用结构化 JSON 日志和请求 ID，`/ready` 显示各项依赖状态。
8. 前端面向桌面浏览器，使用固定侧栏和桌面布局，通过同源 API 访问 FastAPI。页面最低宽度 1200px，建议在 1280px 以上窗口使用。

## 前端组件边界

- `AppShell`：导航、用户状态与路由出口。
- `SceneCard`：只展示场景并发出选择事件。
- `DialoguePanel`：展示消息、输入回答并发出发送/结束事件。
- `ScoreRadar`：只负责四维评分可视化。
- `useTrainingSession`：封装训练读取、完整回复接口和结束训练的副作用；SSE 端点供流式客户端与压测使用。
- 计划详情页：四步任务（复盘 / 改写 / 微课与练习 / 同条件复测）+ 复盘批注区，批注来自评分建议与证据。
- `useTrainingPlan`：封装计划读取、任务打卡和进度刷新。
- `NetworkStatusBanner`：断网时说明离线可用范围。
- `useNetworkStatus`：封装浏览器在线/离线事件。
- 路由页只负责组合组件与加载页面数据。

## API

- `POST /api/v1/auth/register|login|refresh|logout`
- `GET /api/v1/scenes`，`POST /api/v1/scenes/{id}/favorite`
- `POST /api/v1/scripts/generate`
- `GET /api/v1/scripts`，`POST /api/v1/scripts/{id}/favorite`
- `POST /api/v1/training-sessions`
- `GET /api/v1/training-sessions`，`GET /api/v1/training-sessions/export`
- `POST /api/v1/training-sessions/{id}/messages`（SSE）
- `POST /api/v1/training-sessions/{id}/finish`
- `GET /api/v1/evaluations/{sessionId}`
- `GET /api/v1/dashboard`
- `GET /api/v1/training-plans/{id}`，`POST /api/v1/training-plans/{id}/tasks/{key}/complete`
- `GET /api/v1/courses`，`POST /api/v1/courses/{id}/progress`
- `GET /api/v1/admin/overview`
- `GET|PATCH /api/v1/admin/users`、`GET|POST|PATCH|DELETE /api/v1/admin/scenes`
- `GET|POST|PATCH /api/v1/admin/courses`（停用/启用走 PATCH `active`）、`GET /api/v1/admin/sessions`
- `GET /api/v1/admin/learners/{userId}/report` 与个人/全量 CSV 导出
- `POST /api/v1/training-sessions/{id}/archive|restore`、`GET /api/v1/training-sessions?archived=true`
- `DELETE /api/v1/scripts/{id}`；话术版本保存亮点、收藏；支持逐字差异高亮对比
- `GET /api/v1/health`（存活检查），`GET /api/v1/ready`（依赖就绪检查）

## 运行拓扑

```text
桌面浏览器 → Vue 3 → FastAPI
                              ├─ MySQL
                              ├─ Redis
                              └─ DeepSeek / 豆包 / 通义千问 API
```

`docker-compose.yml` 负责启动 MySQL 和 Redis；前后端仍在
前后端可分别从 PyCharm 或终端启动，便于查看各自的运行日志。

## 历史兼容边界（2026-11-17）

计划任务使用 `tasks_version=2`。迁移 `20261117_0048` 将旧任务的默认字段、课程快照、计划内来源及此前读时补出的复测任务固定保存。读取计划只校验与序列化，不再根据最近训练猜来源或补任务。

旧录像上传分析已退役，`POST /video-interviews` 与旧任务重跑接口返回 410。实时视频仍通过 `/voice/sessions` 保存并使用 Whisper/MediaPipe 分析。历史任务只读接口、历史录像与报告保留，不再启动后台分析 worker。

评分只产生四维结果；得体性数据库列与旧证据用于历史兼容，不再实时计算或接受新增第五维证据。旧课程文件名、旧语言标记及必要的旧维度文字兼容仍保留。

## 性能验收

`backend/scripts/load_test.py` 使用共享的异步 HTTP 连接池并发创建训练会话、读取 SSE，分别记录响应头、
首个事件、首个 AI token 和完整响应延迟。默认 20 个虚拟用户、首 token p95 门槛 3000ms；任何请求失败、
真实环境发生模型降级或 p95 超标都会返回非零退出码，并生成不含密码和 token 的 JSON 报告。

流式训练接口的认证数据库依赖使用 function scope，在返回 `StreamingResponse` 前完成用户校验并归还连接；
流生成器自行创建短事务会话，避免慢速 SSE 响应长期占用认证连接并耗尽连接池。

