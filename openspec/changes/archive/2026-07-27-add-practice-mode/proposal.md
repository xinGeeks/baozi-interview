## Why

v0.3.1 先撤掉了 F(跨会话训练图谱) + G(弱 topic 专项练习)的整套实现
(`a0a383c`),留下一份干净的 config / interview / report 三页 MVP。
用户实测反馈:**单独主题深挖**仍然是高频需求,只是想先做轻量版
(入口直接输入主题,不需要训练图谱、不需要 topic 抽取、不需要 mastery)。

本 change 加『主题专项练习』:菜单栏新页 + focus_context 提问分支 +
历史用 `mode='practice'` 标记 + 历史列表徽标区分。**显式不做**:训练
图谱、topic 抽取、mastery 评分、弱 topic 推荐排序(轻量边界)。

## What Changes

- **新 capability `lightweight-practice-mode`**:菜单栏第 2 页
  `🎯 专项练习`(`pages/practice.py`),只接受一个主题文本 + 难度/
  风格(从全局 session_state 复用),不要求 JD / 简历。
- **新 storage 列 `interview_sessions.mode`**:`TEXT NOT NULL DEFAULT
  'interview'`,区分 `interview` vs `practice`。幂等 ALTER TABLE
  迁移,老行 backfill。
- **`prompts.build_interviewer_system_prompt` 加 `focus_context` 关
  键字参数 + `build_report_prompt` 加同参**:practice 下 prompt 头部
  去掉 JD 段(没有就不出),核心规则 3/4 改为禁止索要简历/假设岗位;
  report 六维第 1 维换成『主题掌握度』,基础信息段改写『练习主题』。
- **`interview_helpers._system_prompt` / `_generate_report` / 保存落
  盘 / 真实度聚合** 4 处都让 practice 不带 JD(空串或 `[专项练习]
  <主题>` 占位),防 session 残留串味。
- **页面 UX**:`pages/config.py` 移除内嵌入口,改一句指路 caption;
  `pages/interview.py` 切到 practice 模式时换标题/副标题/结束按钮
  文案/输入框 placeholder;`pages/report.py` 历史列表 practice 行
  带 `🎯 练习 ·` 徽标。
- **App nav**:`st.navigation` 从 3 页扩到 4 页,`PAGE_PATHS` 加
  `"practice"`。

## Capabilities

### New Capabilities

- `lightweight-practice-mode`: 菜单栏『专项练习』独立页 + 主题输入
  + 不带 JD/简历 的 focus prompt + 报告维度换成主题掌握度 + 历史
  列表徽标。

### Modified Capabilities

- `multipage-navigation`: PAGE_PATHS 4 页;config 不再内嵌 practice
  入口(改指路 caption)。
- `interview-autosave`:**不受影响**(草稿继续覆盖 practice 状态
  键,刷新后能续答)。

## Impact

- `storage.py`:SCHEMA 加 mode 列 + init_db 幂等 ALTER TABLE +
  save_session mode 关键字 + list_sessions SELECT 多一列
- `prompts.py`:build_interviewer_system_prompt + build_report_prompt
  各加 focus_context 关键字参数,内部分支
- `interview_helpers.py`:抽 `_practice_focus()`,4 处调用改;
  DEFAULTS 加 `practice_mode: False` / `practice_topic: ""`,
  AUTOSAVE_KEYS 也加这 2 个
- `app.py`:st.navigation 4 页
- `pages/config.py`:删专项练习小节,加指路 caption
- `pages/interview.py`:practice 模式 title/caption/end-button/placeholder
- `pages/report.py`:history 列表加 mode_badge + 下一场复位 practice
- 新增 `pages/practice.py`:独立页
- 测试:新增 `tests/test_pages_practice.py`(10 测) +
  `test_prompts.py` 加 11 测 +
  `test_pages_interview.py` 加 3 测 +
  `test_pages_config.py` 加 3 测交接护栏 +
  `test_app_entry.py` 改 4 页断言 + 路径存在性校验 +
  `test_storage.py` 加 3 测(mode 默认 / practice 落库 / 老 DB 迁移)
- 兼容性:无破坏性变化 —— `save_session` mode 默认 `'interview'`,
  老 DB ALTER TABLE 幂等迁移,focus_context 默认 None 走 legacy 路径
