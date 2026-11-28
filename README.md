# InterviewLoop · 言阶

InterviewLoop 提供文字、语音和视频模拟面试。AI 面试官根据岗位和回答进行多轮追问，训练结束后提供带原话证据的四维评分和提升计划。

**想按步骤启动？双击打开 [`docs/启动指南.md`](docs/启动指南.md)。** 指南优先介绍在 PyCharm 和 Docker Desktop 中的操作；仅在功能不可用时才用备用命令。

**岗位/行业面试场景 → AI 角色多轮追问 → 四维评分 → 生成带编号的提升计划（复盘 → 改写 → 微课与练习 → 同条件复测）→ 再练一轮并对比分数**。话术优化是独立功能，可将自己的原话改写成三种风格并对比收藏。

## 技术栈

- 后端：Python 3.10+、FastAPI、SQLAlchemy、LangGraph、SSE
- 前端：Vue 3、TypeScript、Vite、Axios，桌面浏览器界面
- 数据库：MySQL
- 训练数据与进度：MySQL；限流：Redis
- 大模型：DeepSeek、豆包或通义千问的 OpenAI 兼容 API

界面采用桌面布局，页面最低宽度 1200px，建议使用 Chrome 或 Edge，并保持浏览器窗口宽度在 1280px 以上。

要体验完整的训练流程，请配置 MySQL、Redis 和可用的大模型 API Key。项目保留 SQLite、内存限流和本地教练模板用于测试或离线运行。文字页面使用完整回复接口，SSE 端点供流式客户端与压测使用；实时语音与视频使用 WebSocket。

新工程师接手请先阅读 [开发接手指南](docs/开发接手指南.md)，其中包含核心链路、业务术语和测试入口。

## 一、准备环境

需要安装：

- Python 3.10 或更高版本；
- Node.js；
- Docker Desktop；

复制环境变量模板：

```powershell
# 在项目根目录执行
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

打开 `.env`，把下面一项替换为自己的大模型 Key：

```dotenv
LLM_API_KEY=你的Key
```

默认配置使用 DeepSeek：

```dotenv
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
```

Key 不能提交到 Git，也不要写进 Python 或 Vue 源码。

## 二、启动 MySQL、Redis

在项目根目录执行：

```powershell
docker compose --project-name career-coach up -d
docker compose --project-name career-coach ps
```

第一次下载镜像会比较慢；MySQL 和 Redis 显示 healthy 后再启动后端。

本机 Docker MySQL 映射到 `3308`、Redis 映射到 `6380`；`3307` 已被另一个项目占用。

## 三、启动后端

首次安装依赖：

```powershell
# 从项目根目录进入后端目录
Set-Location .\backend
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install --constraint constraints.txt --requirement requirements-dev.txt
.venv\Scripts\python.exe -m alembic upgrade head
```

启动（固定走 venv 的脚本，任何终端都一致）：

```powershell
# 在项目根目录执行；需要热重载时追加 --reload
.\scripts\start-backend.cmd
```

后端固定监听 `127.0.0.1:8081`，同一时间只能有一个实例；端口被占用时脚本会直接失败，请先关掉旧进程。任务管理器里会出现两个 python 进程：venv 的 `Scripts\python.exe` 启动器，以及它派生的真正服务进程，二者同属这一套 venv，属于正常现象。

浏览器打开 `http://127.0.0.1:8081/docs`，能看到接口页面即成功。

不要用系统全局 Python（例如 `D:\Astudy\...` 下的解释器）启动本项目：依赖装不全时会拿到一个绑定了端口却不接连接的死进程。

在 PyCharm 中可新建 Python 运行配置：

- Module name：`uvicorn`
- Parameters：`app.main:app --host 127.0.0.1 --port 8081 --reload`
- Working directory：仓库下的 `backend/`
- Python interpreter：仓库下的 `backend/.venv/Scripts/python.exe`

## 四、启动前端

另开一个终端：

```powershell
# 从项目根目录进入前端目录
Set-Location .\frontend
npm install
npm run dev
```

访问 `http://localhost:5173`。


场景卡片可选文字、语音或视频；三种方式共用简历、岗位 JD 和强度准备。语音/视频提供 5、10、15、30、60 分钟；系统自动选择语音引擎。录制按隐私页说明保存和删除。

开始面试时可选上传文字版 `.docx` 简历（不超过 2 MB），AI 面试官会按当前面试阶段，围绕简历里明确写出的经历、项目或技术栈提问、追问；不上传仍按原场景训练。原始 Word 文件不会保存，仅提取文字并发送到已配置的大模型；训练页可单独清除简历文字，训练记录页可彻底删除整个会话。

演示账号：

- 学员：`student@example.com` / `Student123!`
- 管理员：`admin@example.com` / `Admin123!`

登录页也可以直接注册新学员。

## 五、体验一次完整训练

1. 登录学员账号。
2. 先选行业、岗位，再从适用的 HR 初面、技术一面、技术二面 / 复面、交叉面 / 总监面、HRBP/HR 终面、高管终面中选阶段和难度。不同岗位显示的阶段不一定相同。
3. 进入场景选择文字、语音或视频对练；可选上传 `.docx` 简历体验针对性技术追问。点击“结束面试”按已经提交的回答生成总结；直接退出不保留本场记录。少量回答的总结仅作本次参考，计划任务另有达标轮次要求。
4. 查看内容与逻辑、贴合问题、信息完整、表达干净四维评分及原句证据。
5. 进入“能力提升”按上一场面试类型查看复盘：文字面试是逐轮批注 + 微课；语音面试加对话与表达节奏；视频面试再加镜头表现，然后按计划的场景复练。
6. 打开计划页：先读逐轮复盘批注，再按任务卡完成场景再练、视频面试与个性化微课（可看视频版）。
7. 回到原场景再练一轮，在计划页与报告页对比四维前后分数、提升判定及下一步建议；成长看板和训练记录保留历史。
8. 进入独立“话术优化”页（新用户也可使用），粘贴自己的原话，生成正式、亲和、简洁三种版本并对比收藏。

评分或话术生成遇到模型不可用时会明确显示降级状态；需要正式评分时，请确认 Key 和模型服务可用。

命令行启动步骤、功能验收流程和常见问题见 [本地运行与功能验收](docs/本地运行与功能验收.md)。

## 六、大模型切换

DeepSeek：

```dotenv
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
```

豆包：

```dotenv
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_MODEL=火山方舟推理接入点ID
```

通义千问：

```dotenv
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
```

修改 `.env` 后需要重启后端。没有 Key 或模型接口临时失败时，系统会自动使用本地教练模板，
仍可体验基础对练。

## 七、验证项目

后端测试：

```powershell
# 从项目根目录进入后端目录
Set-Location .\backend
.venv\Scripts\python.exe -m pytest -q
```

前端构建：

```powershell
# 从项目根目录进入前端目录
Set-Location .\frontend
npm run build
```

性能参数需要验收时，可在后端已启动后运行：

```powershell
$env:LOAD_TEST_EMAIL='student@example.com'
$env:LOAD_TEST_PASSWORD='Student123!'
.venv\Scripts\python.exe scripts\load_test.py --users 20 --output reports\load-test.json
```

## 八、上线部署

生产环境用两个镜像 + 四个容器：`web`（nginx 托管前端并反代 API）、`backend`（uvicorn）、`mysql`、`redis`。

```bash
cp .env.production.example .env      # 填域名、密码、模型 Key
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml run --rm backend alembic upgrade head
python3 scripts/smoke_test.py --base https://your-domain.com
```

- 完整步骤（TLS、备份、升级、回滚、排查）：[`docs/部署指南.md`](docs/部署指南.md)
- 发布前逐项检查：[`docs/上线检查清单.md`](docs/上线检查清单.md)
- 冒烟脚本：`scripts/smoke_test.py`，一条命令检查健康、就绪、登录、场景、训练、评分、报告
- 备份脚本：`scripts/backup.sh`（数据库 + 录像/微课/TTS，默认保留 14 天）

## 目录说明

- `backend/app/features/`：登录、场景、话术、训练、评分、计划和看板业务
- `backend/app/infrastructure/`：大模型和 Redis 接入
- `backend/migrations/`：MySQL 数据库迁移
- `frontend/src/`：Vue 3 页面、组件和接口调用
- `docker-compose.yml`：开发环境 MySQL、Redis
- `docker-compose.prod.yml`：生产编排（mysql / redis / backend / web）
- `backend/Dockerfile`、`frontend/Dockerfile`、`frontend/nginx.conf`：生产镜像与反向代理
- `scripts/smoke_test.py`、`scripts/backup.sh`：上线冒烟与备份
- `docs/architecture.md`：系统架构说明
- [`docs/技术说明.md`](docs/技术说明.md) 介绍模型接入、评分规则及音视频实现

## 本轮升级

详见 [功能升级与验收](docs/功能升级与验收.md)。已有数据库先在 backend 中运行 `.venv\Scripts\python.exe -m alembic upgrade head`。
