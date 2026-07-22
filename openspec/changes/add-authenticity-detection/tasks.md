## 1. Setup

- [x] 1.1 创建 `authenticity.py` 骨架:imports + module docstring + 常量占位
- [x] 1.2 加 `STOPWORDS` 集合(虚词/中文标点)+ jieba 初始化检查

## 2. Heuristic detection (per-turn)

- [x] 2.1 实现 `detect_signals(question, answer, resume_text) -> list[str]` 4 条规则
- [x] 2.2 实现 `_mentions_any_entity(answer, resume_text) -> bool` helper(简历项目名/技术栈提取)
- [x] 2.3 加固定词表常量 `SIGNAL_VOCAB = ("过于简短", "模板化", "答非所问", "未引用简历")`
- [x] 2.4 写 `tests/test_authenticity.py` 单元测试:每个信号 1 个正向 + 1 个反向 case
- [x] 2.5 加性能预算测试(200 词 < 1ms)

## 3. LLM aggregation (report-time)

- [x] 3.1 实现 `build_authenticity_judgment_prompt(resume, jd, chat_history, turn_flags)` 强约束 prompt
- [x] 3.2 实现 `AuthenticityReport` dataclass(score: float, findings: list[Finding], summary: str)
- [x] 3.3 实现 `parse_authenticity_response(text) -> AuthenticityReport` 含 sentinel `-1.0` 兜底
- [x] 3.4 加 score 越界截到 [0, 1] + findings > 3 时截断
- [x] 3.5 加 snapshot 测试(prompt 含「只基于 given signals」)
- [x] 3.6 加 parse 容错测试(缺字段 / 坏 JSON / 越界分数)

## 4. App integration

- [x] 4.1 `app.py` `_handle_user_answer` 调 `detect_signals` 写 `st.session_state["turn_authenticity_flags"]`
- [x] 4.2 `DEFAULTS` 加 `"turn_authenticity_flags": []` + `"authenticity_report": None`
- [x] 4.3 `_render_feedback_card` 加 ⚠️ 显示分支(只在 flag 非空时)
- [x] 4.4 `_end_interview` 末尾调一次 LLM 聚合(走现有 `_do_chat`),结果存 `authenticity_report`
- [x] 4.5 报告渲染区加「第 7 段 · 真实性维度」分支(score >= 0 时显示,-1 隐藏)
- [x] 4.6 报告 prompt 末尾追加第 7 段结构(可选,即使 prompt 不改 parse 也兜底)

## 5. Tests

- [x] 5.1 AppTest: 有 flag 时反馈卡渲染 ⚠️
- [x] 5.2 AppTest: 无 flag 时反馈卡不渲染 ⚠️
- [x] 5.3 AppTest: score=0.7 时报告渲染第 7 段
- [x] 5.4 AppTest: score=-1 时报告不渲染第 7 段
- [x] 5.5 回归:既有 v0.3 149 测试零 fail(实际 188 全绿)

## 6. Docs

- [x] 6.1 更新 MEMORY.md 把 feature 加进 project_baozi_streamlit_mvp.md(Feature E: 真实性检测)
- [x] 6.2 commit message 写清 5 条设计决策(启发式 vs LLM / 4 信号 / prompt 强约束 / flag-only / 向后兼容)