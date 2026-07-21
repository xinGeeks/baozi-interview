# Tasks: MVP AI 面试官

## 1. 项目骨架
- [ ] 1.1 创建项目目录结构(根目录 + `tests/`)
- [ ] 1.2 写 `requirements.txt`(streamlit / openai / pypdf2 / pytest)
- [ ] 1.3 写 `.env.example`(LLM_API_KEY / LLM_BASE_URL / LLM_MODEL 三个变量)
- [ ] 1.4 写 `README.md`(启动 / 配置 / demo 流程)

## 2. 配置层 (`config.py`)
- [ ] 2.1 实现 `get_llm_config()` 返回 `(api_key, base_url, model)` tuple
- [ ] 2.2 默认值指向 MiniMax-M3(`https://api.MiniMax.chat/v1` + `MiniMax-M3`)
- [ ] 2.3 缺失 API_KEY 时给出友好 stderr 提示(MVP 阶段不强制要求)
- [ ] 2.4 单元测试:有 env / 无 env / 部分 env 三种情况

## 3. 简历解析 (`resume_parser.py`)
- [ ] 3.1 实现 `parse_pdf_resume(file_bytes: bytes) -> str`,用 PyPDF2
- [ ] 3.2 异常处理:非 PDF / 加密 PDF / 空文件 → 返回空字符串 + 警告
- [ ] 3.3 单元测试:fixture PDF(`tests/fixtures/sample_resume.pdf`)+ 三种异常路径

## 4. Prompt 层 (`prompts.py`)
- [ ] 4.1 实现 `build_interviewer_system_prompt(level, style, resume, jd) -> str`
- [ ] 4.2 实现 `build_report_prompt(level, resume, jd, chat_history) -> str`
- [ ] 4.3 6 档 × 2 风格的提问方向表硬编码在模块顶部
- [ ] 4.4 报告 prompt 含"每分附依据"和"不要套话"硬约束
- [ ] 4.5 单元测试:12 组合的 system prompt 快照测试(避免无声漂移)

## 5. 主应用 (`app.py`)
- [ ] 5.1 Streamlit 页面 + 标题
- [ ] 5.2 侧边栏:简历上传 / 6 档 selectbox / 2 档 radio
- [ ] 5.3 JD text_area 在主区
- [ ] 5.4 "开始面试"按钮 → 调 LLM 生成第一题,清空历史
- [ ] 5.5 聊天区:渲染 history(user / assistant 两种气泡)
- [ ] 5.6 `st.chat_input` 接收用户回答 → 调 LLM 生成下一题
- [ ] 5.7 检测用户输入含"结束面试"关键词 → 自动停问
- [ ] 5.8 "生成报告"按钮 → 调 LLM 出报告,Markdown 渲染
- [ ] 5.9 session_state 状态变更流程图正确(开始→对话→结束→报告)

## 6. 错误处理
- [ ] 6.1 LLM 调用失败(网络 / 限流 / 鉴权)→ 友好 Toast,不崩溃
- [ ] 6.2 PDF 解析失败 → 提示用户检查文件
- [ ] 6.3 JD 为空 → 提示必须填,但允许继续(MVP 降级)

## 7. 测试
- [ ] 7.1 `tests/test_config.py` — 配置读取三路径
- [ ] 7.2 `tests/test_resume_parser.py` — PDF 解析 + 异常
- [ ] 7.3 `tests/test_prompts.py` — 12 组合快照 + 报告 prompt 关键约束
- [ ] 7.4 `tests/test_app.py` — Streamlit AppTest 驱动 `start` → `answer × 3` → `report` 流程(monkeypatch LLM)
- [ ] 7.5 总数 ≥ 30 测试,全绿

## 8. Smoke(手动,需用户提供 API key)
- [ ] 8.1 文档化 smoke 步骤:上传 fixture + JD,选"社招中级 + 压力",答 5 轮,生成报告
- [ ] 8.2 验收 checklist:问题有针对性 / 报告六维各有依据 / 不全 7-8
- [ ] 8.3 CI 不跑这条(避免 API key 泄露),放 `tests/manual/smoke.md`

## 9. 交付检查
- [ ] 9.1 `streamlit run app.py` 一行启动成功
- [ ] 9.2 6 档 × 2 风格每个组合都至少 smoke 一次(开发者手动)
- [ ] 9.3 README demo 流程截图(可选,MVP 不强制)
- [ ] 9.4 OpenSpec 归档到 `archive/`
