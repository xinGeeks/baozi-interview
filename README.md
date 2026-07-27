# AI 面试官 (MVP)

一个给求职者用的面试实战模拟工具,基于个人简历 + 目标岗位 JD + 6 档职级,定制一场一对一模拟面试,并在结束后生成六维评估报告。

## 快速开始

```bash
# 1. 安装依赖(alpha 用户)
pip install -r requirements.txt
# 开发者(测试 + 类型检查)
pip install -r requirements.txt -r requirements-dev.txt

# 2. 配置 API key
cp .env.example .env
# 编辑 .env,填入 LLM_API_KEY

# 3. 启动
streamlit run app.py
```

浏览器打开 http://localhost:8501,按菜单栏顺序:配置 → 专项练习 / 面试 → 报告。

## 4 个页面

| 页面 | 用途 | 是否需要 JD / 简历 |
|---|---|---|
| **配置** | 简历上传、JD 粘贴、难度 / 风格选择,点"开始面试" | 简历可选,JD 必填 |
| **专项练习** | 围绕单个主题深挖(例:kafka 高可用) | 都不要 |
| **面试** | 对话循环 + 逐轮反馈 + 真实度检测 | 由入口页决定 |
| **报告** | 本场六维报告 + 历史报告列表 | — |

## 配置项

通过环境变量或 `.env` 文件配置(`.env` 在 `config.py` 启动时自动加载):

| 变量 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `LLM_API_KEY` | 是 | (空) | MiniMax 平台 API key |
| `LLM_BASE_URL` | 否 | `https://api.MiniMax.chat/v1` | OpenAI 兼容接口 |
| `LLM_MODEL` | 否 | `MiniMax-M3` | 模型名 |
| `LLM_DAILY_TOKEN_CAP` | 否 | `200000` | 每日 token 预算(估算,±25% 误差);0 = 不限制 |
| `STORAGE_RETENTION_DAYS` | 否 | `30` | 历史会话保留天数;0 = 不自动清理 |

更详细的成本估算见 [`docs/llm-cost.md`](docs/llm-cost.md)。

## 6 档职级

校招 / 实习 / 社招(初级 1-2年) / 社招(中级 3-5年) / 社招(高级 5-8年) / 社招(资深 8年+)

## 2 档面试风格

温和引导 / 压力深挖

## Demo 流程

**A. 社招中级 + 压力**(正常面试)

1. 进 **配置** 页,上传 PDF 简历(自己的或 `tests/fixtures/sample_resume.pdf`)
2. 选 **社招(中级)** + **压力深挖**
3. 主区粘贴一段 JD(可用 `tests/fixtures/sample_jd.txt`)
4. 点"开始面试" → AI 出第一题
5. 在输入框回答 5 轮(可用"结束面试"关键词提前结束)
6. 自动跳到 **报告** 页 → 查看六维评估

**B. 主题深挖**(专项练习,不需要 JD / 简历)

1. 进 **专项练习** 页
2. 填一个主题(例:`kafka 高可用`、`Redis 缓存击穿`、`系统设计能力`)
3. 选难度 / 风格(默认继承上次选择)
4. 点"启动专项练习" → AI 首题直接切入主题,不做自我介绍
5. 回答 5 轮后,点"退出专项练习并出报告" → 看主题掌握度评估

## 报告维度

**正常面试**:

1. 岗位匹配度
2. 专业技术能力
3. 项目实战能力
4. 逻辑思维能力
5. 沟通表达能力
6. 职级适配度
7. 真实性维度(可选,v0.3 Feature E 落地)

**专项练习**(无目标岗位,第 1 维换成主题掌握度):

1. 主题掌握度(对焦点主题的理解深度与完整度)
2. 专业技术能力
3. 项目实战能力
4. 逻辑思维能力
5. 沟通表达能力
6. 职级适配度

每项 0-10 分,附打分依据。报告主体是**给求职者的改进建议**(不是"录用判定")。

## 数据与隐私

- 面试对话存在本地 SQLite(`data/interviews.db`),可单条删除 / 一键清空
- 30 天自动清理过期 session(`STORAGE_RETENTION_DAYS` 可调)
- 简历原文仅在面试进行中作为草稿持久化(autosave),用于刷新后续答

## 开发

```bash
# 跑测试
pytest
# 含覆盖率
pytest --cov=. --cov-report=term-missing

# 手动 smoke(需 API key)
# 见 tests/manual/smoke.md

# 类型检查
mypy *.py
```

## Troubleshooting

| 症状 | 原因 | 解决 |
|---|---|---|
| sidebar 红色提示"未配置 LLM_API_KEY" | `.env` 缺 key 或没复制 | `cp .env.example .env` 后填入 `LLM_API_KEY` |
| 启动后立刻报 `AuthError` / `API key 无效` | key 错 / 平台余额不足 | 检查 `.env`;登录 MiniMax 控制台查余额 |
| 报 `RateLimitError` / 请求过快 | 单日请求超过平台配额 | 暂停几分钟;或切到更便宜模型 |
| 报 `TransientError` / 网络不稳定 | VPN / 防火墙 / 平台抖动 | 重试;若持续失败检查网络 |
| sidebar 红色"今日预算已用完" | 估算 token 达到 `LLM_DAILY_TOKEN_CAP` | 调高 `.env` 中 `LLM_DAILY_TOKEN_CAP`;或等到 UTC 0 点重置 |
| 历史区空白 | DB 文件被删 / 换了机器 | 检查 `data/interviews.db` 路径;`STORAGE_DB_PATH` 显式设置 |
| 上传 PDF 后报错"简历解析失败" | PDF 是扫描件 / 加密 | 转 Word / 纯文本粘贴 |

## 范围边界(MVP)

**做**:PDF 简历 + JD + 6 档 + 2 风格 + 一问一答 + 六维报告 + 逐轮反馈 + 历史持久化 + 流式输出 + 真实度检测 + 主题专项练习(无需 JD / 简历)
**不做**:Word 简历 / 语音 / 英文 / 跨设备同步 / 云部署 / 真实成本核算(估算,±25% 误差) / 训练图谱 / topic 抽取

详见 `openspec/changes/archive/`。

## 相关文档

- [`docs/alpha.md`](docs/alpha.md) — Alpha 邀请计划 + 时间窗 + 成功标准
- [`docs/llm-cost.md`](docs/llm-cost.md) — 单场面试成本估算 + 模型选型
