## Context

现状:`app.py` 单文件 1200+ 行,Sidebar 5 个 expander(history / topics / practice / bulk clear / ToS),主区同时承担"配置表单 / chat loop / 报告渲染"3 态。每次 app.py rerun 把全部逻辑执行一遍,任意一个 widget 交互都触发整页重建,认知负担大、新功能塞不下。

约束:
- 保留现有 session_state keys(全部 30+ 个),向后兼容
- storage / prompts / feedback / resume_parser / topic_extraction / authenticity **零改动**(无业务逻辑变化,只重排渲染位置)
- Streamlit ≥ 1.36(已满足)
- 现有 AppTest mock 模式继续可用

## Goals / Non-Goals

**Goals:**
- 4 页线性流程,每页一个核心心智
- 完成时跳下一页;用户可手动 nav 回前一页
- 侧栏只放全局(ToS / 隐私 / 数据删除)
- 历史查看整合到报告页
- 弱 topic 练习从 sidebar 入口迁到训练图谱页

**Non-Goals:**
- 不做权限/角色(单用户)
- 不做并行 tab(单流程即可)
- 不改 storage schema
- 不引入新依赖
- 不做 URL routing(Streamlit 默认按 page 内部 hash)

## Decisions

### Decision 1: 用 `st.navigation` + `st.Page`(`pages/` 目录结构)

**选**:`st.navigation([...])` 顶层声明,各页放 `pages/<name>.py`(Streamlit 自动识别为 Page 模式)。

**理由**:
- Streamlit 1.36+ 原生支持,无新依赖
- 跨 page session_state 共享(MultiPageApp 共用 SessionState)
- `st.switch_page("pages/report.py")` 跨页跳转自然
- 测试可用 `AppTest.from_file("pages/interview.py")` 单独驱动单页

**备选**:
- `st.sidebar.radio` 手工切换:不重启 script,需自己管理 state,易乱
- 旧 `pages/` 自动发现 + `st.set_page_config`:Streamlit 已 deprecated 该隐式模式
- ✅ `st.navigation` + `st.Page` 显式:可控 + 可测

### Decision 2: app.py 退化为 entry point

**选**:app.py 只含 1) ToS 闸门 2) 全局 sidebar(ToS 状态 / 隐私链接 / 数据删除按钮)3) `st.navigation` 声明。

**理由**:
- 单一职责,容易 grep / 单元测试
- page-specific 逻辑放 page 内,sidebar 不再成为"杂货铺"
- ToS 闸门必须在 page 渲染前(全局,无论在哪页都要检查)

**备选**:
- 保留全部逻辑在 app.py,用 `if st.session_state.current_page == "config": ...` 条件分支:不拆文件,本质还是单页
- ✅ entry 模式:清晰分层

### Decision 3: 弱 topic 练习复用现有 `practice_mode` 状态机

**选**:训练图谱页点 candidate → `practice_mode=True` + `practice_topic=<topic>` + `st.switch_page("pages/interview.py")` → interview 页 auto-start 触发(沿用 Feature G 的 trigger)。

**理由**:
- practice 是"另一场 interview",prompt 注入 `focus_context` 而已
- 复用 `_start_interview` / `_handle_user_answer` / `_generate_report` 全部路径
- 现有 practice 测试零回归

**备选**:
- 在 topics 页内嵌 chat:另起炉灶,3 套并行代码
- ✅ 复用 interview 页:DRY 不失守

### Decision 4: 历史只读视图整合到报告页

**选**:报告页顶部加 segmented control("本场报告" / "历史报告"),历史点击 → `loaded_session_id` 设置 + `viewing_history=True` + `st.switch_page("pages/report.py")`。

**理由**:
- "报告"心智统一(本场 + 历史都是报告)
- 不再需要单独 history page

**备选**:
- 独立"历史"页:6 个 widget 复用度低,单列不够厚
- ✅ 整合到报告页:导航路径最短

### Decision 5: ToS 闸门放 entry 仍生效

**选**:app.py 顶部放 ToS 闸门(沿用现有 modal),`st.stop()` 阻断所有 page 渲染。

**理由**:
- ToS 是真·全局,无论用户进哪页都必须先接受
- `st.stop()` 在 `st.navigation` 之前调用安全(还没有 page 被渲染)

**备选**:
- 每个 page 自己检查:易漏(尤其新加 page)
- ✅ entry 级:契约明确

### Decision 6: 报告页不自动跳到训练图谱

**选**:报告渲染完 → 显示"下一场"按钮(回配置) + "查看训练图谱"按钮(跳 topics)。**不自动跳**。

**理由**:
- 用户下载报告、读报告需要时间
- 自动跳会"吞掉"用户注意力
- 显式选择 = 显式意图

**备选**:
- 报告渲染完 3s 后自动跳:反 UX
- ✅ 显式按钮:符合"完成一走一步"心智,用户控制节奏

## Risks / Trade-offs

- **Risk**:Streamlit `st.navigation` 在 AppTest 下的支持可能不全,部分测试需逐 page 跑。**Mitigation**:把现有 `test_app*.py` 拆成 `test_pages_*.py` + `test_app_entry.py`,每个 AppTest from_file 单独驱动对应 page,互不干扰。
- **Risk**:跨 page session_state 共享 OK,但 mock_responses 在 entry 注入后跨 page 是否生效需验证。**Mitigation**:测试套件先跑端到端 happy path,确认 practice / interview 主流程无回归。
- **Risk**:`st.switch_page` 跳转后 state 是否立即可见?Streamlit rerun 重新执行目标 page 脚本,state 在 rerun 之间持久。**Mitigation**:设计 4 个 page 的 init logic 用 `if "key" not in st.session_state: st.session_state[key] = default` 模式,确保新 page 进来时 state 已就绪。
- **Trade-off**:4 页强制线性,但用户可能想"先看历史再开始新一场"。**接受**:在 sidebar 全局放"查看历史"链接即可,不必为此破坏线性心智。

## Migration Plan

1. **Phase 1 — 拆文件**:把 app.py 内容按 4 个 page 拆到 `pages/config.py` / `pages/interview.py` / `pages/report.py` / `pages/topics.py`,helpers(`_system_prompt` / `_start_interview` / `_handle_user_answer` / `_generate_report`)放 `pages/_interview_helpers.py`(跨 page 共享)
2. **Phase 2 — entry 重写**:app.py 缩到 ~50 行,只含 ToS 闸门 + 全局 sidebar + `st.navigation` 声明
3. **Phase 3 — 测试重构**:`tests/test_app.py` → `test_pages_config.py` 等 4 文件 + `test_app_entry.py`;AppTest from_file 改为指向 entry(`app.py`)或各 page
4. **回滚**:git revert 到 commit `a49e350` 即可(单 page 模式仍可用)
5. **部署**:`streamlit run app.py` 不变(Streamlit 自动识别 pages/ 目录)

## Open Questions

- 报告页 segmented control 还是两个 tab?(`st.tabs` 默认全部 mount,多内容会撑高;segmented 更紧凑)
- 训练图谱页的"弱 topic 练习"按钮是否要在话题云里也加 inline?(目前是按钮列表,可考虑"直接点 chip 进入")— 留 Phase 2
