## 1. Storage: mode 列 + 幂等迁移

- [x] 1.1 在 SCHEMA 的 `interview_sessions` CREATE TABLE 加 `mode TEXT NOT NULL DEFAULT 'interview'`
- [x] 1.2 `init_db` 加幂等迁移块(PRAGMA table_info + ALTER TABLE ADD COLUMN)
- [x] 1.3 `save_session` 加 `mode: str = "interview"` keyword-only 参数,INSERT 包含 mode
- [x] 1.4 `list_sessions` 加 `mode: str | None = None` keyword-only 参数,SELECT 加 WHERE 过滤
- [x] 1.5 `extract_and_store_for_session` 入口加 `SELECT mode` gate,mode='practice' → return 0

## 2. Prompts: focus_context 扩展

- [x] 2.1 `build_interviewer_system_prompt` 加 `focus_context: str | None = None` keyword-only 参数
- [x] 2.2 非 None 时在 prompt 末尾(开场白前)注入 `[专项训练模式] 当前焦点主题:「{topic}」` 块
- [x] 2.3 跑 tests/test_prompts.py 61 个测试零回归

## 3. App: UI 集成

- [x] 3.1 DEFAULTS 加 `practice_mode: False` + `practice_topic: ""`
- [x] 3.2 `_system_prompt()` 检查 `practice_mode`,传 `focus_context=practice_topic`
- [x] 3.3 `_start_interview()` 在 practice_mode=True 时跳过 JD 非空校验
- [x] 3.4 `_generate_report()` 传 `mode="practice" if practice_mode else "interview"` 到 save_session
- [x] 3.5 sidebar 新增 `🎯 弱 topic 专项练习` expander,内含 top-8 candidate buttons + 空态 caption
- [x] 3.6 主体区加 `🚪 退出专项训练` 按钮(仅在 practice 模式渲染)
- [x] 3.7 chat_input 接受"退出专项训练"作为 END_SIGNAL 的别名
- [x] 3.8 sidebar 历史区加 `🎯 练习记录 (N)` 子 expander(仅 ≥1 practice 行时渲染)
- [x] 3.9 history `list_sessions` 调用加 `mode='interview'` 过滤
- [x] 3.10 主体加 auto-start trigger(practice_mode=True + 未开始 → 调 _start_interview)

## 4. Tests: 单元 + AppTest

- [x] 4.1 `tests/test_storage_practice.py` 新文件 7 个测试:幂等迁移 + save 持久化 mode + extract gate + list filter
- [x] 4.2 `tests/test_app_practice.py` 新文件 7 个 AppTest:expander 存在 + entry/exit 流程 + 模式隔离 + history split

## 5. 验证

- [x] 5.1 `pytest` 全套 321 测试全绿(307 已有 + 14 新)
- [x] 5.2 openspec validate --changes add-weak-topic-practice-mode 通过
- [x] 5.3 memory 更新到 `project_baozi_streamlit_mvp.md`
- [x] 5.4 `openspec archive add-weak-topic-practice-mode` 入库
