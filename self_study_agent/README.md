# 自学 Agent

## Web 界面（TypeScript）

Web 界面位于 `web/`，首次使用时执行：

```powershell
cd web
npm install
npm run dev
```

浏览器访问命令行显示的本地地址（默认 `http://127.0.0.1:5173`）。界面会调用同目录下的 Python CLI 和 `data/study_agent.sqlite3`，无需另行启动 Python 服务。

本项目是一个面向 AI Agent 架构学习的本地自学 Agent。它仅导入课程 PDF，聚焦提炼 Agent Loop、工具调用、Tool Runtime、Schema、MCP、状态与记忆、安全治理、可观测性和测试验收等设计思想，生成练习题并按薄弱知识点安排复习。

## 安装

```powershell
python -m pip install -r requirements.txt
```

## 常用命令

```powershell
python -m study_agent import "C:\\资料\\课程.pdf"
python -m study_agent sources
python -m study_agent extract <source_id>
python -m study_agent generate <source_id>
python -m study_agent quiz start --source-id <source_id> --count 10
python -m study_agent quiz answer <question_id> "我的答案"
python -m study_agent review
```

SQLite 数据库默认保存至 `data/study_agent.sqlite3`。通过 `--learner-id` 可区分本地学习者。

生成知识点、题目和简答评分必须配置 OpenAI-compatible 模型服务：`STUDY_AGENT_BASE_URL`、`STUDY_AGENT_API_KEY` 与 `STUDY_AGENT_MODEL`。课程范围与系统提示词位于 `config/study_profile.toml`；可通过 `STUDY_AGENT_PROFILE` 指向另一份 TOML 学习画像，不需要修改 Python 代码。

## 日志

Python CLI 默认将阶段日志输出到 `stderr`，JSON 结果仍输出到 `stdout`，因此自动化脚本可以安全解析 JSON。日志覆盖 PDF 导入、模型请求、知识点生成、出题、答题接收、对错判断与掌握度更新；不会记录 PDF 正文、模型提示词、密钥或答案原文。

```powershell
python -m study_agent --log-level INFO import "C:\资料\课程.pdf"
python -m study_agent --log-level DEBUG generate <source_id>
```

通过 Web 界面运行时，Node 服务也会将 Python CLI 的日志转发到启动 `npm run dev` 的终端。

## 安全边界

- 资料正文是待分析数据，不会被当作系统指令执行。
- 当前版本仅支持本地 PDF；DOCX 和网页导入功能已移除。
- 所有资料读取、提炼、出题与评分均经过唯一的 `StudyRuntime.invoke()`。
- 审计记录只保存调用关联、字段名、稳定错误码和摘要，不保存密钥、完整资料正文或模型提示词。
