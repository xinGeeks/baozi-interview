## Why

进行中的面试只活在 `st.session_state` 里。浏览器刷新会开一个全新的 Streamlit session,`session_state` 被清空 —— 而代码只在 `_generate_report()`(结束出报告)时才 `save_session` 落盘,所以刷新即丢,无法继续面试。(页面间导航不丢状态,已实测确认;问题只在刷新。)

本 change 让进行中的面试**自动存草稿**、刷新/重进后能**续答**。因为这是个人项目,决定同时**彻底移除 ToS/隐私系统** —— 原 `user-data-privacy` capability 承诺「简历原文不持久化」,与"草稿保存简历原文以全保真续答"直接冲突。

## What Changes

- **新 capability `interview-autosave`**:进行中面试每答一轮自动写入 `interview_autosave` 草稿槽(每 candidate 一行,`state_json` 含 chat_history / feedback / 配置 / **简历原文**);刷新后 config / interview 页检测到草稿 → 显示「继续未完成的面试」banner → 恢复 `session_state` 续答;面试完成(出报告)或用户放弃 → 清草稿。
- **移除 `user-data-privacy` 的 ToS/PII 部分**:删 ToS 接受闸门、consent_log 表 + `record_consent`/`has_accepted_tos`、PII 通知(sidebar caption / uploader help / 「不含简历原文」)、`docs/privacy.md`。**保留**单条删除 / 批量清空 / 30 天自动清理(属数据管理,非隐私承诺)。
- **`multipage-navigation` sidebar 要求收窄**:sidebar 不再显示 ToS 状态 / 隐私政策,只保留「清空我的全部历史」;入口不再有 ToS 闸门。

## Capabilities

### New Capabilities

- `interview-autosave`: 进行中面试自动存草稿 + 刷新后续答 + 完成/放弃清草稿。

### Removed Capabilities

- `user-data-privacy` 的 3 条 requirement:PII Notice Before Resume Upload / ToS Versioned Acceptance / Consent Log Persistence(其余数据删除/保留 requirement 保留)。

## Impact

- `storage.py`:+ `interview_autosave` 表 + `save_autosave`/`load_autosave`/`clear_autosave`;- `consent_log` 表 + `record_consent`/`has_accepted_tos`。
- `interview_helpers.py`:+ autosave 快照/恢复/续答 helper;- TOS/PII 常量、DEFAULTS 的 tos 键。
- `app.py`:- ToS 闸门 + sidebar 隐私。
- `pages/config.py` + `pages/interview.py`:+ 续答 banner;config - PII 通知。
- `docs/privacy.md` 删除;`README.md` 去 ToS/隐私描述。
- 测试:删 `test_consent.py`;改 `test_app_entry.py` / `test_pages_config.py` / `conftest.py`;新增 `test_storage_autosave.py` / `test_pages_autosave.py`。
- 无新依赖(`json` 为 stdlib)。
