# 自学 Agent

本项目是一个本地命令行自学 Agent。它可导入 PDF、DOCX 和公开静态网页，提炼知识点，生成练习题，记录作答，并按薄弱知识点安排复习。

## 安装

```powershell
python -m pip install -r requirements.txt
```

## 常用命令

```powershell
python -m study_agent import "C:\\资料\\课程.pdf"
python -m study_agent sources
python -m study_agent generate <source_id>
python -m study_agent quiz start --source-id <source_id> --count 5
python -m study_agent quiz answer <question_id> "我的答案"
python -m study_agent review
```

SQLite 数据库默认保存至 `data/study_agent.sqlite3`。通过 `--learner-id` 可区分本地学习者。

未配置模型时，项目使用离线规则提炼知识卡并生成可自动评分的单选/判断题；简答题会返回待人工对照结果。设置 `STUDY_AGENT_BASE_URL`、`STUDY_AGENT_API_KEY` 和 `STUDY_AGENT_MODEL` 后，可使用 OpenAI-compatible 模型生成题目并评分简答。

## 安全边界

- 资料正文是待分析数据，不会被当作系统指令执行。
- 网站仅支持公开静态 HTML；本机、私网、非 HTTP(S) 地址均被拒绝。
- 所有资料读取、提炼、出题与评分均经过唯一的 `StudyRuntime.invoke()`。
- 审计记录只保存调用关联、字段名、稳定错误码和摘要，不保存密钥、完整资料正文或模型提示词。
