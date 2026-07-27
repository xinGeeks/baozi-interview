## 1. 拆文件 — `pages/` 目录结构

- [x] 1.1 新建 `pages/_interview_helpers.py` 存放跨页共享:`_system_prompt` / `_start_interview` / `_handle_user_answer` / `_render_feedback_card` / `_render_history_view` / `_generate_report` / `_aggregate_authenticity` / `_render_authenticity_section`
- [x] 1.2 新建 `pages/config.py` 包含:file_uploader / JD text_area / level selectbox / style radio / "开始面试" button(完成后 `st.switch_page("pages/interview.py")`)
- [x] 1.3 新建 `pages/interview.py` 包含:chat_message 渲染循环 + chat_input(检测 END_SIGNAL 切页)+ practice exit 按钮 + auto-start trigger
- [x] 1.4 新建 `pages/report.py` 包含:segmented control(本场报告 / 历史报告)+ 报告渲染 / 历史只读 + 下一场 / 查看训练图谱 按钮
- [x] 1.5 新建 `pages/topics.py` 包含:跨会话训练图谱 expander + 弱 topic 专项练习 expander(candidate buttons + 空态 caption)+ "查看历史" 子区

## 2. 入口重构 — `app.py` 退化

- [x] 2.1 `app.py` 顶部 ToS 闸门(沿用 `st.session_state.tos_check_done` / `tos_accepted`)
- [x] 2.2 移除 app.py 内全部 page-specific 渲染代码(配置 / 面试 / 报告 / topic expander)
- [x] 2.3 全局 sidebar 只保留:ToS 状态 / 隐私链接 / "🗑️ 清空我的全部历史" expander
- [x] 2.4 `st.navigation([...])` 声明 4 页,`st.set_page_config` 设标题
- [x] 2.5 DEFAULTS 加 `current_page: "config"`(可选,辅助 sidebar / debug 标记)

## 3. 跨页跳转逻辑

- [x] 3.1 配置页"开始面试"成功 → `st.switch_page("pages/interview.py")`
- [x] 3.2 面试页 END_SIGNAL / 退出专项训练 → 报告页(`st.switch_page("pages/report.py")`)
- [x] 3.3 报告页"下一场"按钮 → 重置 `chat_history` / `interview_started` / `loaded_session_id` 等 → 配置页
- [x] 3.4 报告页"查看训练图谱"按钮 → 训练图谱页
- [x] 3.5 训练图谱页 candidate button → `practice_mode=True` + `st.switch_page("pages/interview.py")`
- [x] 3.6 任意页点历史记录(配置页 / 训练图谱页 / sidebar)→ `loaded_session_id` + `viewing_history=True` + `st.switch_page("pages/report.py")`

## 4. 测试重构

- [x] 4.1 新建 `tests/test_app_entry.py`:ToS 闸门 + 全局 sidebar + navigation 声明
- [x] 4.2 新建 `tests/test_pages_config.py`:file_uploader / JD 填入 / 等级 / 风格 / 开始按钮触发 `_start_interview` + 跳页
- [x] 4.3 新建 `tests/test_pages_interview.py`:chat 渲染 / chat_input 处理 / END_SIGNAL 跳页 / practice exit
- [x] 4.4 新建 `tests/test_pages_report.py`:本场报告 / 历史报告 切换 / 报告渲染 / 下一场 / 训练图谱按钮
- [x] 4.5 新建 `tests/test_pages_topics.py`:topic cloud / candidate buttons / practice 跳页
- [x] 4.6 删除或精简旧 `tests/test_app.py` / `test_app_topics.py` / `test_app_practice.py`(迁到对应 page 测试)
- [x] 4.7 跑全套 ≥ 321 测试零回归(实测 332 全绿)

## 5. 验证

- [x] 5.1 `pytest` 全套测试全绿(332/332)
- [x] 5.2 `openspec validate --changes add-multipage-navigation` 通过
- [x] 5.3 手动 smoke:`streamlit run app.py` → 走 4 页主路径 + practice 旁路,确认无报错
- [x] 5.4 memory 更新到 `project_baozi_streamlit_mvp.md`
- [x] 5.5 `openspec archive add-multipage-navigation` 入库
