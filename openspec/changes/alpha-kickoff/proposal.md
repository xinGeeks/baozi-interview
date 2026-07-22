## Why

v0.3 五项功能(逐轮反馈 / 历史持久化 / 流式输出 / 打分校准 / 真实度检测)全部落地,产品形态已经稳定,可以开放给真实用户。但要让 10-30 位 alpha 用户放心使用,我们必须补齐三类就绪度:**用户数据隐私可控**(PII 通知、ToS 接受、数据删除)、**LLM 成本可控**(防止单用户/单日把 token 预算打爆)、**技术稳定性兜底**(网络断开、API key 失效、限流等异常有用户友好提示)。这三条都是 alpha 阶段"敢发出去"的硬门槛,缺一不可。

## What Changes

- **新增 `user-data-privacy` 能力**:上传简历前显示 PII 通知;首次使用时强制接受 ToS;UI 提供按 session 删除 + 一键清空全部历史;30 天保留策略自动清理。
- **新增 `llm-cost-control` 能力**:`.env` 暴露 `LLM_DAILY_TOKEN_CAP`;内存计数器按 UTC 日切;接近/超限时 UI 显示警告横幅;成本估算文档写进 README。
- **新增 `operational-resilience` 能力**(非独立 spec,作为既有 LLMError 路径的强化):`llm.py` 区分 `LLMError` 子类型(`AuthError` / `RateLimitError` / `TransientError`);`app.py` 全局 try/except 兜底,所有未捕获异常走 `_handle_unexpected_error`,显示用户友好提示并记录到 `data/error.log`。
- **基础设施**:依赖锁定(`requirements.txt` 加 pin + 新增 `requirements-dev.txt`)、`.env.example` 新增 `LLM_DAILY_TOKEN_CAP` / `STORAGE_RETENTION_DAYS`、README 增补 troubleshooting + 成本估算 + alpha 邀请模板段。
- **新增文档**:`docs/alpha.md`(用户邀请模板、2-4 周时间窗、success criteria)、`docs/privacy.md`(PII 处理原则、ToS 全文)、`docs/llm-cost.md`(单场面试成本估算、模型选型指南)。

无破坏性变更:所有现有 `st.session_state` 字段保留;历史 session 格式不破坏(`storage.py` schema 不变)。

## Capabilities

### New Capabilities
- `user-data-privacy`: 简历 PII 通知、ToS 接受、session 删除、批量清空、自动保留清理
- `llm-cost-control`: 每日 token 预算、UI 警告横幅、成本估算文档

### Modified Capabilities
(无 — 现有 `authenticity-detection` 的需求不变,只是新增独立能力)

## Impact

- **代码**:`app.py`(PII 通知 + ToS checkbox + 删除按钮 + 警告横幅 + 全局兜底)、`storage.py`(新增 `delete_session` / `purge_expired_sessions` / `clear_all_sessions_for_candidate`)、`llm.py`(LLMError 子类)、`config.py`(新增 env var 读取)、`auth.py` 新文件(ToS 接受状态持久化)
- **依赖**:`requirements.txt` 锁版本;`requirements-dev.txt` 分离测试依赖(ppytest-cov / mypy)
- **文档**:`README.md`(troubleshooting + 成本估算 + alpha 邀请段)、`docs/alpha.md` / `docs/privacy.md` / `docs/llm-cost.md`(新)
- **测试**:从 134 增加到 ~150(+16),覆盖删除/ToS/预算/错误分类
- **数据**:`storage.py` 新增 `consent_log` 表(ToS 接受时间戳 + 版本号);不存 ToS 文本本身(版本号已足够)
