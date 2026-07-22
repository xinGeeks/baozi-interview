## 1. 依赖锁定与配置

- [x] 1.1 用 `pip freeze` 锁定 `requirements.txt` 全部依赖(streamlit / openai / pypdf / pytest)
- [x] 1.2 创建 `requirements-dev.txt` 分离测试依赖(pytest-cov / mypy)
- [x] 1.3 `.env.example` 新增 `LLM_DAILY_TOKEN_CAP` / `STORAGE_RETENTION_DAYS` 及默认值说明
- [x] 1.4 `config.py` 新增 `_get_int_env(name, default)` + 暴露 daily_token_cap / retention_days
- [x] 1.5 README 增补「troubleshooting」段(API key 无效 / 网络断开 / 超预算)+ 「依赖安装」步骤

## 2. 隐私通知前置与 ToS

- [x] 2.1 创建 `docs/privacy.md` — PII 处理原则 + ToS 全文(v1,2026-07-22)
- [x] 2.2 `storage.py` 新增 `consent_log` 表 SCHEMA(CREATE TABLE IF NOT EXISTS + UNIQUE 约束)
- [x] 2.3 `storage.py` 新增 `record_consent(db_path, candidate_id, tos_version)` 与 `has_accepted_tos(db_path, candidate_id, tos_version)`
- [x] 2.4 `app.py` 加 `TOS_VERSION = "2026-07-22-v1"` 常量
- [x] 2.5 `app.py` sidebar 顶部加 PII 通知 caption(未上传简历时显示)
- [x] 2.6 `app.py` `file_uploader` 加 `help=` 参数含 PII 提示
- [x] 2.7 `app.py` ToS modal:未接受时主区显示完整 ToS + checkbox + "确认接受" 按钮
- [x] 2.8 `app.py` ToS 接受 → 调 `record_consent` → 关闭 modal + 解锁开始面试
- [x] 2.9 `tests/test_consent.py` 覆盖 `record_consent` / `has_accepted_tos` / ToS modal 渲染(~5 测试)

## 3. 数据删除与保留

- [x] 3.1 `storage.py` 新增 `delete_session(db_path, session_id)` — DELETE 3 表 + 返回是否成功
- [x] 3.2 `storage.py` 新增 `clear_all_sessions_for_candidate(db_path, candidate_id)` — 返回删除条数
- [x] 3.3 `storage.py` 新增 `purge_expired_sessions(db_path, retention_days)` — 按 `ended_at` 删,返回条数
- [x] 3.4 `app.py` `init_db` 后立即调 `purge_expired_sessions` 走 lazy 清理
- [x] 3.5 `app.py` sidebar 每条历史加 🗑️ 按钮 + `st.dialog`/`st.popover` 二次确认(显示日期+轮数)
- [x] 3.6 `app.py` sidebar 底部加「清空我的全部历史」按钮 + 强制输入"确认删除"才能点
- [x] 3.7 `tests/test_storage_deletion.py` 覆盖三个删除函数 + 副作用(turns/feedback 级联清)~6 测试

## 4. LLM 成本控制

- [x] 4.1 新建 `cost.py` — `estimate_tokens(text) -> int` (char // 4) + 模块常量
- [x] 4.2 `cost.py` 新增 `DailyTokenCounter` 类 — `add(usage) / current / is_warning / is_blocked / percent`
- [x] 4.3 `cost.py` UTC 日切:`last_reset_utc_date` 字段 + `add()` 时检查;新一天则重置为 0
- [x] 4.4 `app.py` 在 `DEFAULTS` 加 `token_usage_today`(int) + `token_cap`(int)
- [x] 4.5 `app.py` `_do_chat` 内 token 估算(messages 拼成 string) + 累加;stream 模式分块累加
- [x] 4.6 `app.py` sidebar 加预算条 + 80% 黄色警告 / 100% 红色熔断 + chat_input 禁用
- [x] 4.7 `app.py` 熔断时 `st.chat_input` 的 `disabled=True` 生效
- [x] 4.8 创建 `docs/llm-cost.md` — 5 轮单场成本估算表(MiniMax-M3 / 其他模型) + 模型选型指南 + ±25% 误差声明
- [x] 4.9 `tests/test_cost.py` 覆盖 estimate_tokens / DailyTokenCounter / UTC 日切 / 边界(80/100%)~8 测试

## 5. 操作韧性(异常分类 + 全局兜底)

- [x] 5.1 `llm.py` 新增 `AuthError(LLMError)` / `RateLimitError(LLMError)` / `TransientError(LLMError)` / `UnknownError(LLMError)`
- [x] 5.2 `llm.py` `chat` / `chat_stream` 内映射 openai SDK exception → 对应子类
- [x] 5.3 `app.py` 新增 `_install_global_error_handler()` 注册 `sys.excepthook` + 写 `data/error.log`(只记 type + str(e)[:200])
- [x] 5.4 `app.py` `_start_interview` / `_handle_user_answer` / `_generate_report` / `_aggregate_authenticity` 补 try/except Exception 兜底
- [x] 5.5 异常类型对应用户友好提示(AuthError → "API key 无效" / RateLimitError → "请求过快,稍后重试" / TransientError → "网络不稳定,自动重试" / UnknownError → "未知错误,详见错误日志")
- [x] 5.6 `tests/test_resilience.py` 覆盖 4 个 LLMError 子类 + sys.excepthook + error.log(~5 测试)

## 6. Alpha 邀请与时间窗

- [x] 6.1 创建 `docs/alpha.md` — 邀请模板(微信/邮件)+ 目标用户画像(产品/工程朋友 + 1-2 位陌生求职者)
- [x] 6.2 `docs/alpha.md` 时间窗 — 2-4 周(2026-07-29 ~ 2026-08-25)
- [x] 6.3 `docs/alpha.md` success criteria — 至少 N 场完整面试 / 完成率 / 用户反馈数 / 崩溃率 < 1%
- [x] 6.4 README 增补「Alpha 计划」段链接到 `docs/alpha.md`

## 7. 集成测试与全量回归

- [x] 7.1 `tests/test_app_e2e.py` 端到端 AppTest 跑完整路径(模拟 ToS 接受 → 简历上传 → 5 轮 → 出报告 → 删除 session)
- [x] 7.2 `tests/test_app_budget.py` 覆盖 sidebar 警告 / 硬熔断 / chat_input 禁用状态(~3 测试)
- [x] 7.3 `pytest` 全量回归,目标 150+ 测试全绿
- [ ] 7.4 手动 smoke:启动 `streamlit run app.py`,走一遍 ToS → 面试 → 报告 → 删除流程(用真实 API key + 至少 1 场完整 5 轮)
- [x] 7.5 更新 `MEMORY.md` 与 `project_baozi_streamlit_mvp.md` 记录 alpha-kickoff 落地(commit / 文档链接)
