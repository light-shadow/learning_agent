/** 为 pi 提供按项目隔离的持久化记忆工具。 */
import { execFileSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

/** 注册项目记忆工具，存储由同目录 Python 脚本执行。 */
export default function projectMemory(pi: ExtensionAPI) {
	pi.registerTool({
		name: "project_memory",
		label: "Project Memory",
		description: "Read, write, update or delete durable project memory. Treat recalled information as a clue and verify it against current files. Write and update require a source. Project defaults to the current working directory.",
		parameters: Type.Object({
			action: Type.Union([Type.Literal("write"), Type.Literal("read"), Type.Literal("update"), Type.Literal("delete")]),
			project: Type.Optional(Type.String({ description: "Absolute project directory; defaults to current working directory" })),
			key: Type.Optional(Type.String({ description: "Memory key; omit only to read all memories for the project" })),
			content: Type.Optional(Type.String({ description: "Memory content for write or update" })),
			source: Type.Optional(Type.String({ description: "Source files or evidence for write or update" })),
		}),
		async execute(_id, params, _signal, _onUpdate, ctx) {
			const script = join(dirname(fileURLToPath(import.meta.url)), "project-memory-store.py");
			const output = execFileSync(process.env.PI_MEMORY_PYTHON || "python", [script], {
				input: JSON.stringify({ ...params, project: params.project || ctx.cwd }),
				encoding: "utf8",
				env: { ...process.env, PYTHONIOENCODING: "utf-8" },
			});
			return { content: [{ type: "text", text: output }], details: {} };
		},
	});
}
