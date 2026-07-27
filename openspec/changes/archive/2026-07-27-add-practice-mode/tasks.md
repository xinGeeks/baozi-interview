# Tasks: 2026-07-27-add-practice-mode

## 1. storage 加 mode 列

- [x] 1.1 `storage.py`:`interview_sessions` 加 `mode TEXT NOT NULL DEFAULT 'interview'`
- [x] 1.2 `init_db` 用 `PRAGMA table_info` 幂等 `ALTER TABLE` 兼容老 DB
- [x] 1.3 `save_session(mode: str = "interview")` 关键字参数
- [x] 1.4 `list_sessions` SELECT 多带 `mode` 列

## 2. prompts 引入 focus_context

- [x] 2.1 `build_interviewer_system_prompt` 加 `focus_context` 关键字
- [x] 2.2 practice 分支:头部 context_block 不出 JD/简历段
- [x] 2.3 practice 分支:核心规则 3/4 改为禁止索要简历/假设岗位
- [x] 2.4 practice 分支:深挖循环链按 `has_resume` 拼装
- [x] 2.5 流程/开场白 block 去掉自带标题,防与外层重复
- [x] 2.6 `build_report_prompt` 加 `focus_context`,六维第 1 维换主题掌握度

## 3. interview_helpers 抽出 _practice_focus

- [x] 3.1 DEFAULTS 加 `practice_mode: False` / `practice_topic: ""`,
      AUTOSAVE_KEYS 也加 2 个
- [x] 3.2 `_system_prompt` / `_generate_report` / 保存落盘 / 真实度
      聚合 4 处都让 practice 不带 JD
- [x] 3.3 `_start_interview` practice 模式免 JD 校验

## 4. 4 个页面变更

- [x] 4.1 新建 `pages/practice.py`:主题输入 + 难度/风格 + 启动
- [x] 4.2 `pages/config.py`:删专项练习小节,加指路 caption
- [x] 4.3 `pages/interview.py`:practice 模式换标题/副标题/结束按钮
      文案/输入框 placeholder
- [x] 4.4 `pages/report.py`:history 列表加 `🎯 练习 ·` 徽标;
      「下一场」复位 practice 状态

## 5. app 导航

- [x] 5.1 `interview_helpers.PAGE_PATHS` 加 `"practice"`
- [x] 5.2 `app.py` `st.navigation` 4 页

## 6. 测试 + 验证

- [x] 6.1 新增 `tests/test_pages_practice.py`(10 测)
- [x] 6.2 `tests/test_prompts.py` 加 11 测(practice 不带 JD/简历
      段、规则改写、report 维度换主题掌握度、legacy 不动)
- [x] 6.3 `tests/test_pages_interview.py` 加 3 测(system_prompt 空
      jd、report_prompt focus_context、normal 模式仍传 jd)
- [x] 6.4 `tests/test_pages_config.py` 改交接护栏(3 测)
- [x] 6.5 `tests/test_app_entry.py` 改 4 页 + 路径存在性校验
- [x] 6.6 `tests/test_storage.py` 加 3 测(mode 默认/practice 落库/老
      DB 迁移)
- [x] 6.7 `pytest -q` 全套 310 通过
- [x] 6.8 `openspec validate 2026-07-27-add-practice-mode --strict`
- [x] 6.9 `openspec archive 2026-07-27-add-practice-mode` 入库
- [x] 6.10 README 加 4 页表格 + Demo 流程拆 A/B + 范围边界
