## Why

v0.3 Feature A-G 把配置、面试、报告、训练图谱、设置全塞进单页 `app.py`,侧栏堆了 5 个 expander + 1 个历史区,主区同时承担"配置 / 对话 / 报告"三态,新用户首次打开会"一眼看不到重点"。

本 change 把单页拆成 **4 页线性流程**:配置 → 面试 → 报告 → 训练图谱,完成一步跳到下一步;**侧栏常驻**只放 ToS / 隐私 / 数据删除(全局)。每页一个核心心智,降低认知负担,且为 alpha 用户走"配置 → 面试 → 看报告 → 看自己反复弱"主路径提供清晰导航。

## What Changes

- **新 capability `multipage-navigation`**:用 Streamlit `st.navigation` + `st.Page` 拆 4 页,`pages/` 目录放各页模块,`app.py` 退化为 entry point(只含 `st.navigation(...)` + ToS 闸门 + 全局 sidebar)。
- **`st.switch_page` 完成自动跳转**:配置完成点"开始面试"→ 切到面试页;END_SIGNAL → 切到报告页;报告渲染完 → 用户主动点"下一场"回到配置(不再自动跳),"查看训练图谱"跳到训练图谱页。
- **训练图谱页集成弱 topic 练习入口**:用户点 candidate → 直接复用现有 `practice_mode` + auto-start 触发器,进入"焦点训练"在**当前面试页**展开(practice 仍走 chat loop,只是 prompt 注入 `focus_context`)。
- **新增 `current_page` session_state 标记**:`"config" | "interview" | "report" | "topics"`,供 sidebar 全局组件判断上下文(例如只在 topics 页隐藏"返回面试"按钮)。
- **侧栏常驻 ToS / 隐私 / 数据删除**:不再在主区渲染 ToS modal(首次仍弹一次);历史区、跨会话图谱从侧栏迁到对应页。
- **保留 history_viewing 模式**:点历史记录 → 跳到报告页 + `loaded_session_id` 设置,只读渲染历史报告。
- **无 breaking change**:现有 session_state keys 全部保留;`save_session` / `extract_and_store_for_session` 等 storage API 不变;mock LLM 路径不变。

## Capabilities

### New Capabilities

- `multipage-navigation`: 4 页线性流程 + 侧栏常驻 + 完成跳转 + history viewing 整合。

### Modified Capabilities

- (无 — 现有 `weak-topic-practice` / `cross-session-topic-memory` / `data-deletion` / `consent-tos` 等 capability 的 requirement 不变,只把渲染位置从 sidebar 移到对应页)

## Impact

- `app.py`:从 1200+ 行缩到 ~50 行(只含 navigation + ToS + 全局 sidebar)
- 新增 `pages/` 目录:`config.py` / `interview.py` / `report.py` / `topics.py`
- `storage.py` / `prompts.py` / `feedback.py` / `resume_parser.py` / `topic_extraction.py` / `authenticity.py`:**无改动**
- 测试:`tests/test_app.py` 拆成 `tests/test_pages_config.py` / `test_pages_interview.py` / `test_pages_report.py` / `test_pages_topics.py` / `test_app_entry.py`(ToS + sidebar)
- 历史 AppTest mock 模式(`mock_responses` / `mock_feedback_responses`)沿用,但需适配新 entry point + DEFAULTS
- Streamlit 版本要求:`st.navigation` + `st.Page` 需要 ≥ 1.36(项目当前 1.59.2 满足)
