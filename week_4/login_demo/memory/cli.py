"""项目长期记忆的命令行入口。

用法（在项目根目录下执行，`python -m memory`）：
  python -m memory init    [--db 路径]
  python -m memory write   --project P --key K --value '{"a":1}' --source S [--scope S]
  python -m memory read    --project P [--key K] [--all]
  python -m memory update  --project P --key K --value '{...}' --source S [--scope S]
  python -m memory delete  --project P --key K [--purge]
  python -m memory list    [--project P]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

from .store import ProjectMemory, MemoryStoreError, MemoryRecord

def _default_db() -> str:
    # 优先使用环境变量 PI_MEMORY_DB（沙箱内 ~ 可能不可写，需显式指向可写目录）。
    env = os.environ.get("PI_MEMORY_DB")
    if env:
        return env
    return os.path.expanduser("~/.pi-memory/memory.db")


def _parse_value(raw: str) -> dict:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MemoryStoreError(f"--value 不是合法 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise MemoryStoreError("--value 必须是 JSON 对象（{}），例如 '{\"a\":1}'")
    return value


def _parse_value_file(path: str) -> dict:
    # utf-8-sig 兼容 Windows 上带 BOM 的 UTF-8 文件。
    with open(path, encoding="utf-8-sig") as f:
        return _parse_value(f.read())


def _resolve_value(args) -> dict:
    if args.value_file:
        return _parse_value_file(args.value_file)
    return _parse_value(args.value)


def _print_records(records) -> None:
    if not records:
        print("(没有匹配的记忆)")
        return
    for r in records:
        print(f"[{r.project}/{r.key}] v{r.version} status={r.status}")
        print(f"  scope     : {r.scope}")
        print(f"  source    : {r.source}")
        print(f"  updated_at: {r.updated_at}")
        print(f"  value     :")
        for line in r.value_json.splitlines():
            print(f"    {line}")
        print()


def _require_db_path(args) -> str:
    return os.path.abspath(args.db or _default_db())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m memory",
        description="pi 的项目长期记忆：write / read / update / delete",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_db(p):
        p.add_argument("--db", default=None, help="SQLite 数据库路径，默认 .pi-memory/memory.db")

    def add_ident(p):
        p.add_argument("--project", required=True, help="项目名，例如 login_demo")
        p.add_argument("--key", required=True, help="记忆键，例如 session-test")

    # init
    p = sub.add_parser("init", help="建库（幂等）")
    add_db(p)

    # write
    p = sub.add_parser("write", help="写入新记忆")
    add_db(p)
    add_ident(p)
    vg = p.add_mutually_exclusive_group(required=True)
    vg.add_argument("--value", help="记忆内容，JSON 对象字符串")
    vg.add_argument("--value-file", help="记忆内容，从 JSON 文件读取")
    p.add_argument("--source", required=True, help="来源，例如 artifacts/test-guide.md")
    p.add_argument("--scope", default="project", help="适用范围，默认 project")

    # read
    p = sub.add_parser("read", help="按项目查找并读取")
    add_db(p)
    p.add_argument("--project", required=True)
    p.add_argument("--key", default=None)
    p.add_argument("--all", action="store_true", help="含失效记录")

    # update
    p = sub.add_parser("update", help="更新已有记忆")
    add_db(p)
    add_ident(p)
    vg = p.add_mutually_exclusive_group(required=True)
    vg.add_argument("--value", help="记忆内容，JSON 对象字符串")
    vg.add_argument("--value-file", help="记忆内容，从 JSON 文件读取")
    p.add_argument("--source", required=True)
    p.add_argument("--scope", default=None)

    # delete
    p = sub.add_parser("delete", help="删除记忆")
    add_db(p)
    add_ident(p)
    p.add_argument("--purge", action="store_true", help="物理删除（默认软删除）")

    # list
    p = sub.add_parser("list", help="列出项目或全部记忆")
    add_db(p)
    p.add_argument("--project", default=None)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    db_path = _require_db_path(args)
    mem = ProjectMemory(db_path)

    try:
        if args.command == "init":
            path = mem.init()
            print(f"建库完成: {path}")

        elif args.command == "write":
            rec = mem.write(
                args.project, args.key,
                _resolve_value(args), args.source, args.scope,
            )
            print(f"写入成功 -> 实际保存路径: {db_path}")
            print(f"记录: {rec.project}/{rec.key} v{rec.version}")

        elif args.command == "read":
            recs = mem.read(args.project, args.key, include_inactive=args.all)
            print(f"项目 {args.project!r} 的记忆（{len(recs)} 条）:")
            _print_records(recs)

        elif args.command == "update":
            rec = mem.update(
                args.project, args.key,
                _resolve_value(args), args.source, args.scope,
            )
            print(f"更新成功 -> 实际保存路径: {db_path}")
            print(f"记录: {rec.project}/{rec.key} v{rec.version}")

        elif args.command == "delete":
            ok = mem.delete(args.project, args.key, purge=args.purge)
            print(f"删除{'（物理）' if args.purge else '（软删除）'}: "
                  f"{'成功' if ok else '不存在'}")

        elif args.command == "list":
            if args.project:
                recs = mem.read(args.project, include_inactive=True)
                print(f"项目 {args.project!r} 的记忆（含失效，{len(recs)} 条）:")
                _print_records(recs)
            else:
                projects = mem.list_projects()
                print(f"已建库，项目列表: {projects}")

        else:
            print("未知命令", file=sys.stderr)
            return 2

    except MemoryStoreError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
