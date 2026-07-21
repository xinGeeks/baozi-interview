# AI 面试官 (MVP)

一个给求职者用的面试实战模拟工具,基于个人简历 + 目标岗位 JD + 6 档职级,定制一场一对一模拟面试,并在结束后生成六维评估报告。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API key
cp .env.example .env
# 编辑 .env,填入 LLM_API_KEY

# 3. 启动
streamlit run app.py
```

浏览器打开 http://localhost:8501,按左侧配置 → 粘贴 JD → 点"开始面试"即可。

## 配置项

通过环境变量或 `.env` 文件配置(`.env` 在 `config.py` 启动时自动加载):

| 变量 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `LLM_API_KEY` | 是 | (空) | MiniMax 平台 API key |
| `LLM_BASE_URL` | 否 | `https://api.MiniMax.chat/v1` | OpenAI 兼容接口 |
| `LLM_MODEL` | 否 | `MiniMax-M3` | 模型名 |

## 6 档职级

校招 / 实习 / 社招(初级 1-2年) / 社招(中级 3-5年) / 社招(高级 5-8年) / 社招(资深 8年+)

## 2 档面试风格

温和引导 / 压力深挖

## Demo 流程(社招中级 + 压力)

1. 上传一份 PDF 简历(自己的或 `tests/fixtures/sample_resume.pdf`)
2. 侧边栏选 **社招(中级)** + **压力深挖**
3. 主区粘贴一段 JD(可用 `tests/fixtures/sample_jd.txt`)
4. 点"开始面试" → AI 出第一题
5. 在输入框回答 5 轮(可用"结束面试"关键词提前结束)
6. 点"生成报告" → 查看六维评估

## 报告维度

1. 岗位匹配度
2. 专业技术能力
3. 项目实战能力
4. 逻辑思维能力
5. 沟通表达能力
6. 职级适配度

每项 0-10 分,附打分依据。报告主体是**给求职者的改进建议**(不是"录用判定")。

## 开发

```bash
# 跑测试
pytest

# 手动 smoke(需 API key)
# 见 tests/manual/smoke.md
```

## 范围边界(MVP)

**做**:PDF 简历 + JD + 6 档 + 2 风格 + 一问一答 + 六维报告
**不做**:Word 简历 / 语音 / 英文 / 历史存档 / 报告导出 / 打分校准 / 真实度检测

详见 `openspec/changes/archive/2026-07-21-mvp-ai-interviewer/`。
