## Context

v0.3 五个迭代功能(逐轮反馈 / 历史持久化 / 流式输出 / 打分校准 / 真实度检测)已全部落地,产品形态稳定。当前状态:
- 134 个测试全绿
- `app.py` 638 行单文件,Streamlit rerun 友好
- `storage.py` SQLite 3 表(sessions / turns / feedback),支持 PII 安全(candidate_id 用 MD5,不存简历原文)
- `llm.py` LLMError 包装 + `chat_stream()`
- 模型 MiniMax-M3,默认 base URL `https://api.MiniMax.chat/v1`
- 无任何 LLM 成本控制(无 token 计数、无每日 cap)
- 错误处理:LLMError 在 4 个调用点 catch,但未分类(Auth/RateLimit/Transient)
- 隐私:简历上传后才提示"对话保存到本地 SQLite(不含简历原文)",前置通知缺失
- 无 ToS / 无删除 UI / 无保留策略

目标:补齐三类就绪度,让产品能开放给 10-30 位 alpha 用户使用 2-4 周,不出 P0 级事故。

## Goals / Non-Goals

**Goals:**
- 用户上传简历前,明确知道数据存哪、怎么用、怎么删
- 首次使用必须接受 ToS(版本化)
- 用户可单条删除 session、批量清空全部历史
- 30 天自动清理过期 session
- LLM 每日 token 预算可控,接近/超限时 UI 警告
- 异常(网络断开、API key 无效、限流)有用户友好提示,带 troubleshooting 提示
- 文档完整(README troubleshooting / 成本估算 / alpha 邀请 + docs/ 三个子文档)
- 依赖锁定,alpha 用户 install 即用

**Non-Goals:**
- 多租户 / 多账号认证(本地单用户,alpha 不上云)
- 云部署 / Docker / K8s(alpha 本地 Streamlit 即可,部署留 v0.4)
- 跨设备同步(本地 SQLite 即可)
- GDPR / CCPA 完整合规(只覆盖 alpha 阶段 PII 通知 + 删除;正式合规留 v1.0)
- 真实成本核算(用 char/4 估算,±25% 精度足够,真实 usage 留 v0.4)
- 用户满意度评分(留 v0.4 反馈回路)
- 报告 PDF 导出(留 v0.4)

## Decisions

### 1. LLMError 分类:用子类而非 enum

**选项 A**:`LLMError` 子类 `AuthError(LLMError)` / `RateLimitError(LLMError)` / `TransientError(LLMError)` / `UnknownError(LLMError)`
**选项 B**:`LLMError` 加 `kind: Literal[...]` 字段

**选 A**。理由:`isinstance(e, AuthError)` 比 `e.kind == "auth"` 更 Pythonic;未来按子类定制提示/重试更自然;`except LLMError` 仍能兜底(向后兼容)。

**映射规则**:
- openai `AuthenticationError` / status 401 → `AuthError`
- openai `RateLimitError` / status 429 → `RateLimitError`
- openai `APITimeoutError` / `APIConnectionError` / status 5xx → `TransientError`
- 其他 → `UnknownError`(兜底)

### 2. Token 估算:char/4 而非 tiktoken

**选项 A**:引 `tiktoken` 依赖(精准,但 +5MB 安装包 + 启动 +200ms)
**选项 B**:用 `len(text) // 4` 粗估(中英文混合场景约 ±25% 误差)
**选项 C**:仅靠 `response.usage`(精确但事后,无法事前 cap)

**选 B**。理由:零新依赖、零启动开销、对预算 cap 这种"宁可放过不要误杀"的场景足够。文档明确标注「估算值,误差 ±25%」。

### 3. 预算 cap 模式:软警告 + 硬熔断

- `LLM_DAILY_TOKEN_CAP` 默认 200_000(约 2-3 场完整面试,留余量)
- 达到 80%(160k)→ sidebar 黄色横幅「⚠️ 已用 80% 今日预算」
- 达到 100%(200k)→ sidebar 红色横幅「❌ 今日预算已用完,明日 UTC 0 点重置」+ 主区禁用 chat_input
- 用户可通过 .env 调高 cap(给重度用户)

**为什么不硬熔断从一开始就禁用**:alpha 阶段要看到真实用量分布,过早 cap 会掩盖峰值场景。

### 4. ToS 版本化:hash + version 字符串,不存 ToS 文本

- `TOS_VERSION = "2026-07-22-v1"` 常量
- 存到 SQLite 新表 `consent_log(candidate_id, tos_version, accepted_at)`
- 加载时若 `consent_log` 无当前 `TOS_VERSION` 记录 → 强制显示 ToS 接受 modal
- ToS 文本在 `docs/privacy.md` + UI 内联显示(不存 DB,方便改)
- 改 ToS 内容时:改 `docs/privacy.md` + bump version constant + 写 migration 注释

### 5. 数据保留:lazy 清理而非 background scheduler

**选项 A**:`APScheduler` 后台定时清
**选项 B**:app load 时(`init_db` 之后)清一次

**选 B**。理由:零新依赖;Streamlit rerun 频率高(每次用户操作都 rerun),清理足够频繁;若用户 30 天没打开 app,过期数据反正没人看,下次打开时才清也无影响。

### 6. 全局异常兜底:wrap 整脚本 vs st.stop

- Streamlit 没有 app-level exception handler
- 在 `app.py` 末尾(`if __name__ == "__main__":` 等价)用 try/except 包裹主逻辑不可行(Streamlit 是脚本式)
- 改为:**关键副作用处用 `try/except Exception` 兜底** + 在 `app.py` 最末尾加 `_install_global_error_handler()` 注册 `sys.excepthook`,把未捕获异常显示为 `st.error` + 写 `data/error.log`

`sys.excepthook` 在 Streamlit 上下文里能 catch 大多数未处理异常,但 rerun 中部分异步/回调异常 hook 不到 —— 这是已知 trade-off,文档注明。

### 7. 删除 UI:单条 + 批量分开

- sidebar 历史区每条加 🗑️ 按钮(confirm dialog,二次确认)
- sidebar 底部加"清空我的全部历史"按钮(强制输入"确认删除"才能点)
- 删除后 rerun,刷新历史区

### 8. PII 通知位置:sidebar 顶部 + 上传时再次提示

- sidebar 顶部固定显示一段灰色 caption:「📌 简历原文不会保存,仅用于本场面试上下文。对话记录保存在本地 SQLite,可在历史区删除。」
- `file_uploader` 加 `help=` 参数(悬浮提示相同内容)
- 上传成功时已有 `st.info("💾 面试对话将保存在本地 SQLite(不含简历原文)")`,保留

### 9. 依赖锁定策略:`==` pin + dev 分离

- `requirements.txt`:`streamlit==1.36.2` / `openai==1.51.0` / `pypdf==4.3.1`(从 `pip freeze` 取当前版本)
- `requirements-dev.txt`:继承 + `pytest==8.3.2` / `pytest-cov==5.0.0` / `mypy==1.10.0`
- README 加 `pip install -r requirements.txt -r requirements-dev.txt` 步骤

## Risks / Trade-offs

- **[Streamlit 全局异常 hook 不完整]** → Mitigation:在每个 rerun entry point(`_start_interview` / `_handle_user_answer` / `_generate_report` / 报告下载)显式 try/except;`sys.excepthook` 兜底剩余;`tests/test_resilience.py` 用 monkeypatch 注入异常验证。
- **[Token 估算误差 ±25% 可能误熔断]** → Mitigation:默认 cap 200k(估 2-3 场,留余量);UI 显示"估算值";错误信息提示"如误判可调高 `LLM_DAILY_TOKEN_CAP`"。
- **[sys.excepthook 在 Streamlit rerun 中可能失效]** → Mitigation:已知 trade-off,文档注明「alpha 阶段如果看到未捕获异常导致页面空白,请刷新并截图反馈」。
- **[ToS 版本 bump 时旧用户需重新接受]** → Migration:在 `consent_log` 上加 unique(candidate_id, tos_version)约束;运行时检查"无当前版本记录"即触发 modal。无需数据迁移,只是用户多一次点击。
- **[批量删除无 undo]** → Mitigation:删除前 confirm dialog + 列出"将删除 N 条 session"(从 storage 查实时数);不实现 undo(alpha 阶段非核心)。
- **[依赖 pin 可能与 Streamlit Cloud 不兼容]** → Mitigation:Streamlit Cloud 不在 alpha 范围(本地运行);v0.4 上云时重新评估。
- **[doc 文档(privacy/alpha/llm-cost)写在 docs/ 但 docs 目录是新的]** → Mitigation:新建 `docs/` 目录 + README 添加 docs 索引段;`.gitkeep` 占位。

## Migration Plan

无 schema 迁移:`storage.py` 新增 `consent_log` 表用 `CREATE TABLE IF NOT EXISTS` 幂等创建;`interview_sessions` schema 不变。旧 session 仍然能加载(无 consent 但能浏览历史 —— 弹一次性 ToS 即可)。

部署步骤(本地):
1. `git pull` 后 `pip install -r requirements.txt -r requirements-dev.txt`(版本变化,需重装)
2. `.env` 新增 `LLM_DAILY_TOKEN_CAP=200000` / `STORAGE_RETENTION_DAYS=30`(可选,有默认值)
3. 启动 `streamlit run app.py`,首次进入弹 ToS 接受 modal
4. 历史区 🗑️ 单条删除 / 一键清空按钮可用

回滚:所有新功能独立可控,ToS 可临时跳过(`TOS_VERSION=""` 即跳过检查,留作应急);成本 cap 可设 `LLM_DAILY_TOKEN_CAP=0` 即不限制。

## Open Questions

- **(已解决)** 哪些 P0 子项优先?答:按提案顺序,先依赖锁定 → PII/ToS → 删除 UI → 成本 → 错误分类。
- **(已解决)** 邀请 10-30 位用户怎么选?答:写进 `docs/alpha.md`,产品/工程朋友优先 + 一两位陌生求职者。
- **(未解决)** `LLM_DAILY_TOKEN_CAP` 默认值 200k 是合理还是过低?实施时跑 1 场完整面试,实测再调;用户反馈再调。
- **(未解决)** ToS modal 该多严格?目前设计是"必须勾选 + 点确认才能进",是否需要"读完 10 秒倒计时"?alpha 阶段先用基础 modal,反馈再迭代。
- **(未解决)** `data/error.log` 是否脱敏?目前计划记 `repr(exception)`,若异常带 resume content 会泄漏。Mitigation:只记 `type(e).__name__ + str(e)[:200]`,不记 resume 字段;实施时验证。
