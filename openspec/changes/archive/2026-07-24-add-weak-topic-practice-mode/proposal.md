## Why

Feature F(跨会话训练图谱)让用户**看到**自己的反复弱 topic,但缺一个"行动"路径 — 看到 "kafka 提了 8 次" 后没有"立刻深挖一次"的入口。本 change 加"弱 topic 专项练习"模式:从 cache top-N 自动选候选,点击后进入**焦点训练**,LLM 围绕该主题深挖,练习记录独立保存且**不污染**训练图谱。

## What Changes

- **新 capability `weak-topic-practice`**:sidebar 新增 `🎯 弱 topic 专项练习` expander(默认折叠),展开后显示 top-8 候选主题;每个一个 button,点击进入专项训练。
- **新 storage 列 `interview_sessions.mode`**:`TEXT NOT NULL DEFAULT 'interview'`,区分 `interview` vs `practice` session。幂等 ALTER TABLE 迁移;老行 backfill。
- **`extract_and_store_for_session` 加 mode gate**:practice session 跳过抽取,防练习 transcript 反向污染 `candidate_topic_cache`。
- **`prompts.build_interviewer_system_prompt` 加 `focus_context` 关键字参数**:非 None 时在 prompt 末尾注入 `[专项训练模式]` 块,强制 LLM 围绕该主题深挖。
- **App UI**:practice_mode + practice_topic session_state;`🚪 退出专项训练` 按钮 + chat_input 输入"退出专项训练"也可结束;practice 模式跳过 JD 非空校验;history 区新增 `🎯 练习记录` 子区(只显示 mode='practice' 的行)。

## Capabilities

### New Capabilities

- `weak-topic-practice`: 弱 topic 专项练习模式 — 入口、焦点 prompt 注入、退出、模式隔离、history split。

### Modified Capabilities

- (无 — `cross-session-topic-memory` 的 storage 行为加 mode gate 是**内部实现**变化,不修改 spec requirement)

## Impact

- `storage.py`:SCHEMA 加列 + init_db 幂等迁移 + save_session/list_sessions/extract 签名扩展
- `prompts.py`:build_interviewer_system_prompt 加 keyword-only 参数
- `app.py`:DEFAULTS 加 2 keys + sidebar 新 expander + practice 历史子区 + main 区退出按钮 + chat_input 信号处理
- 测试:`test_storage_practice.py`(7 测) + `test_app_practice.py`(7 测),共 +14
- 兼容性:无破坏性变化 — `save_session` mode 默认 `'interview'`,`list_sessions` 不传 mode 时返回全集
