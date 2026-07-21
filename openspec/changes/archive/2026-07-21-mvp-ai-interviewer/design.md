# Design: MVP AI 面试官

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│ Streamlit 浏览器页                                           │
│ ┌──────────────────────┐  ┌──────────────────────────────┐   │
│ │ Sidebar              │  │ Main                         │   │
│ │ · PDF 简历上传         │  │ · JD text_area               │   │
│ │ · 6 档 selectbox      │  │ · "开始面试" 按钮             │   │
│ │ · 2 风格 radio        │  │ · chat_message 流(AI/用户)   │   │
│ │                       │  │ · chat_input 输入框           │   │
│ │                       │  │ · "结束面试" 按钮              │   │
│ └──────────────────────┘  └──────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                │                          │
                │ config.py                │ app.py
                ▼                          ▼
        ┌──────────────┐          ┌──────────────────┐
        │ 环境变量配置   │          │ OpenAI SDK client │
        │ BASE_URL     │          │ chat.completions  │
        │ API_KEY      │          └────────┬──────────┘
        │ MODEL        │                   │
        └──────────────┘                   ▼
                                  ┌──────────────────┐
                                  │ MiniMax-M3 (LLM) │
                                  └──────────────────┘
```

## 关键设计决策

### 1. 技术栈保持最简

| 选型 | 理由 |
|---|---|
| Streamlit | 单文件可跑、Python 生态、热重载,MVP 阶段不引入前后端分离 |
| OpenAI SDK | MiniMax-M3 兼容 OpenAI 接口格式,SDK 直接用 base_url 切换 |
| PyPDF2 | 仅 PDF 文本抽取,轻量;Word 推后 |
| SQLite / DB | **不引入**;MVP 数据全在 `st.session_state`,接受刷新即失 |

### 2. 模型配置走环境变量,不写死在代码

```python
# config.py
import os
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.MiniMax.chat/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "MiniMax-M3")
```

默认值指向 MiniMax-M3 平台;用户通过 `.env` 或 shell export 覆盖。代码里不出现任何具体 endpoint / key。

### 3. 状态管理:仅 `st.session_state`

```python
st.session_state.chat_history: list[dict]   # [{"role": "user|assistant", "content": "..."}]
st.session_state.resume_content: str         # PDF 抽出的纯文本
st.session_state.interview_level: str        # 6 档之一
st.session_state.interview_style: str        # 温和 / 压力
st.session_state.jd_content: str             # 粘贴的 JD
st.session_state.interview_started: bool
```

**不**做 `st.session_state.report`(报告每次按需生成,避免持久化膨胀)。

### 4. Prompt 结构

`prompts.py` 暴露两个拼接函数,所有 prompt 文本集中在这一处,方便后续调优:

```python
def build_interviewer_system_prompt(level, style, resume, jd) -> str:
    """对话主循环用的 system prompt,每轮都带。"""

def build_report_prompt(level, resume, jd, chat_history) -> str:
    """结束面试时生成报告的 user prompt(不带 system,直接 LLM 调用)。"""
```

**面试官 system prompt 关键约束**:
- 人设:"面试教练"(不是招聘官)
- 单题约束:"一次只问一个问题,禁止一次性输出多题"
- 分级约束:针对 6 档各自的提问方向(校招偏基础 / 社招资深偏架构)
- 风格约束:温和 = 引导补充;压力 = 适度质疑深挖
- 简历约束:优先追问简历中出现的项目 / 技术栈
- 结束信号:用户说"结束面试"时,停止追问并回复"已记录,稍后生成报告"

**报告 prompt 关键约束**:
- 六维固定(岗位匹配 / 专业技术 / 项目实战 / 逻辑思维 / 沟通表达 / 职级适配)
- 0-10 分制,每分附"打分依据",避免空话
- 输出结构固定为 6 段(基础信息 / 六维打分 / 优势 / 短板 / 改进建议 / **适配岗位建议**)
- **去掉"录用建议"**,改为"下一阶段练习重点"

### 5. 单题循环的代码骨架

```python
# app.py 简化
def start_interview():
    st.session_state.chat_history = []
    first_q = call_llm([system, {"role": "user", "content": "请开始面试,输出第一个开场问题"}])
    st.session_state.chat_history.append({"role": "assistant", "content": first_q})

def handle_user_answer(answer):
    st.session_state.chat_history.append({"role": "user", "content": answer})
    next_q = call_llm([system] + st.session_state.chat_history)
    st.session_state.chat_history.append({"role": "assistant", "content": next_q})

def generate_report():
    report = call_llm([{"role": "user", "content": build_report_prompt(...)}])
    return report
```

每次 LLM 调用都把**完整 chat_history + system prompt** 重发,简单可靠。代价是 token 消耗随轮次线性增长,MVP 阶段 5-10 轮完全可接受。

## 风险与已知弱点

| 风险 | 严重度 | MVP 处理 |
|---|---|---|
| LLM 虚高打分(全 7-8) | 中 | 接受;不抗"不真实",但要求"每分有依据" |
| 越级提问(校招被问架构) | 中 | 仅靠 prompt,接受一定漂移 |
| 简历识别(瞎编) | 高 | 明确不在 MVP 范围 |
| Streamlit 刷新丢会话 | 低 | 接受;MVP 不做持久化 |
| LLM 一次性输出多题 | 中 | prompt 明文"一次只问一题",可手动重跑 |
| Token 成本(长对话) | 低 | MVP 单场 < 5k tokens,1 毛钱级别 |

## 与上一轮产品方案的差异

| 维度 | 原方案 | MVP 实施 |
|---|---|---|
| 报告口径 | 资深招聘专家 + 录用建议 | **面试教练 + 改进建议** |
| 模型 | gpt-4o-mini + 自填 base_url | **MiniMax-M3 默认 + 环境变量可覆盖** |
| 简历解析 | PyPDF2 | **保持 PyPDF2(只 PDF)** |
| Word 简历 | 可选进阶 | **明确推后** |
| 语音 / 英文 | 可选进阶 | **明确推后** |
| 持久化 | 报告生成完即失 | **保持 session_state** |
| 启动 | 单文件 `streamlit run app.py` | **保持** |

## 后续路标(非 MVP 范围,但设计预留)

- **P1(校准)**:六维打分改"每轮先打分、结束汇总"双轨,加校准 prompt 防虚高
- **P2(分级硬约束)**:把 6 档出题方向做成 router 表格 + 关键词白名单,LLM 必须从候选集里选
- **P3(结构化简历)**:接 `evals/resume_parser.py`(记忆里 Phase D 已有)做技术栈 / 项目年限抽取
- **P4(语音 + 持久化)**:TTS/ASR + SQLite/Postgres 历史记录
