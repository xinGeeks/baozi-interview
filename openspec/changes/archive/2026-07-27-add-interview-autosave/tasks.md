# Tasks: add-interview-autosave

## Part A — 移除 ToS/隐私系统

- [ ] A1. `storage.py`:`SCHEMA` 删 `consent_log`;删 `record_consent`/`has_accepted_tos`;`init_db` 删 consent_log 迁移行
- [ ] A2. `interview_helpers.py`:删 `TOS_VERSION`/`TOS_SUMMARY`/`PII_NOTICE`/`PII_NOTICE_PLAIN`;storage import 去 `has_accepted_tos`/`record_consent`;`DEFAULTS` 去 `tos_accepted`/`tos_check_done`
- [ ] A3. `app.py`:删 ToS 闸门整段 + sidebar ToS caption / 隐私 expander;删相关 import
- [ ] A4. `pages/config.py`:删 `PII_NOTICE_PLAIN` import + PII caption + uploader `help=` + 「不含简历原文」info
- [ ] A5. 删 `docs/privacy.md`;`README.md` 去 ToS/隐私描述行
- [ ] A6. `openspec/specs/multipage-navigation/spec.md`:sidebar 要求去掉 ToS/隐私,只留数据删除(truth-fix)

## Part B — autosave storage 层

- [ ] B1. `storage.py`:`SCHEMA` 加 `interview_autosave(candidate_id PK, state_json, updated_at)`
- [ ] B2. `save_autosave` / `load_autosave`(json 损坏→None) / `clear_autosave`(幂等)

## Part C — 状态机接入 + 续答 UX

- [ ] C1. `interview_helpers.py`:`AUTOSAVE_KEYS` + `_snapshot_state` + `_restore_state` + `_autosave_interview`(best-effort) + `_clear_autosave`
- [ ] C2. 调用点:`_start_interview` 末尾 / `_handle_user_answer` 末尾 → `_autosave_interview`;`_generate_report` 落盘后 → `_clear_autosave`
- [ ] C3. `_render_resume_prompt(*, target)`:检测草稿 → banner + 继续/放弃按钮
- [ ] C4. `pages/config.py` 标题后接入 banner;`pages/interview.py` 的 not-started 分支接入 banner

## Part D — 测试 + 收口

- [ ] D1. 删 `tests/test_consent.py`;改 `test_app_entry.py`(去 TestTosGate / 隐私 expander / consent_log 断言);删 `test_pages_config.py::test_pii_notice_displayed`;`conftest.py` 简化 fixture
- [ ] D2. 新增 `tests/test_storage_autosave.py`(round-trip / UPSERT / 缺失 / clear / json 损坏)
- [ ] D3. 新增 `tests/test_pages_autosave.py`(答一轮后 DB 有草稿 / 模拟刷新出 banner / 继续恢复 / 放弃清除 / 完成清除)
- [ ] D4. `python -m pytest -q` 全绿
- [ ] D5. `openspec validate add-interview-autosave --strict` 通过
- [ ] D6. 手动 smoke(刷新续答)+ `openspec archive add-interview-autosave` + memory 追加小节
