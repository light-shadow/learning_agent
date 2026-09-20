"""自学 Agent 命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from .errors import StudyError
from .models import ToolCall
from .runtime import StudyRuntime
from .storage import StudyStore


def main(argv: list[str] | None = None) -> int:
    """解析 CLI 参数，调用统一 Runtime，并打印 JSON 结果。"""
    _configure_console_encoding()
    parser = _build_parser()
    args = parser.parse_args(argv)
    store = StudyStore(Path(args.database))
    runtime = StudyRuntime(store)
    try:
        payload = _dispatch(args, runtime, store)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except StudyError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "message": exc.message}, ensure_ascii=False))
        return 2
    finally:
        store.close()


def _configure_console_encoding() -> None:
    """将 Windows 终端输出切换为 UTF-8，避免学习资料字符导致 CLI 中断。"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _build_parser() -> argparse.ArgumentParser:
    """构建稳定的资料导入、测验和复习命令。"""
    parser = argparse.ArgumentParser(prog="study-agent", description="本地自学 Agent")
    parser.add_argument("--database", default="data/study_agent.sqlite3", help="SQLite 数据库路径")
    parser.add_argument("--learner-id", default="default", help="本地学习者标识")
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import", help="导入 PDF、DOCX 或公开静态网页")
    import_parser.add_argument("source")
    subparsers.add_parser("sources", help="查看资料列表")
    concepts = subparsers.add_parser("concepts", help="查看知识点")
    concepts.add_argument("--source-id")
    generate = subparsers.add_parser("generate", help="提炼知识点并生成题目")
    generate.add_argument("source_id")
    quiz = subparsers.add_parser("quiz", help="开始测验或提交答案")
    quiz_sub = quiz.add_subparsers(dest="quiz_command", required=True)
    start = quiz_sub.add_parser("start", help="获取下一轮题目")
    start.add_argument("--source-id")
    start.add_argument("--count", type=int, default=5)
    answer = quiz_sub.add_parser("answer", help="提交一道题目的答案")
    answer.add_argument("question_id")
    answer.add_argument("answer")
    subparsers.add_parser("review", help="查看掌握度与复习优先级")
    subparsers.add_parser("audit", help="查看最小审计摘要")
    return parser


def _dispatch(args: argparse.Namespace, runtime: StudyRuntime, store: StudyStore) -> dict[str, object] | list[dict[str, object]]:
    """将每条 CLI 命令路由到 Runtime 或只读存储查询。"""
    if args.command == "import":
        is_url = urlparse(args.source).scheme in {"http", "https"}
        tool_name = "fetch_webpage" if is_url else ("ingest_pdf" if args.source.lower().endswith(".pdf") else "ingest_docx")
        arguments = {"url": args.source} if is_url else {"path": args.source}
        return runtime.invoke(ToolCall(tool_call_id=_call_id(), name=tool_name, arguments=arguments)).model_dump(mode="json")
    if args.command == "sources":
        return store.list_sources()
    if args.command == "concepts":
        return store.list_concepts(args.source_id)
    if args.command == "generate":
        concepts = runtime.invoke(ToolCall(tool_call_id=_call_id(), name="extract_concepts", arguments={"source_id": args.source_id}))
        if not concepts.ok:
            return concepts.model_dump(mode="json")
        return runtime.invoke(ToolCall(tool_call_id=_call_id(), name="generate_quiz", arguments={"source_id": args.source_id})).model_dump(mode="json")
    if args.command == "quiz" and args.quiz_command == "start":
        if args.count < 1 or args.count > 20:
            raise StudyError("INVALID_ARGUMENT", "题目数量必须在 1 到 20 之间")
        return store.select_questions(args.learner_id, args.source_id, args.count)
    if args.command == "quiz" and args.quiz_command == "answer":
        return runtime.grade(args.learner_id, args.question_id, args.answer).model_dump(mode="json")
    if args.command == "review":
        return store.review(args.learner_id)
    if args.command == "audit":
        return store.list_audit()
    raise StudyError("INVALID_COMMAND", "未知命令")


def _call_id() -> str:
    """为 CLI 触发的每次 Runtime 调用生成关联标识。"""
    return f"call_{uuid4().hex}"
