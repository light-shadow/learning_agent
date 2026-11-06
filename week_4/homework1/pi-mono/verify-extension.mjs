/** 使用 pi 相同的 jiti 加载方式检查扩展注册及实际工具调用。 */
import { createJiti } from "jiti/static";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const jiti = createJiti(import.meta.url, { interopDefault: true, tryNative: false, moduleCache: false });
const extension = await jiti.import(join(root, ".pi/extensions/project-memory.ts"), { default: true });
let tool;
extension({ registerTool(value) { tool = value; } });
if (!tool || tool.name !== "project_memory") throw new Error("未注册记忆工具");
process.env.PI_MEMORY_DB = join(root, "project-memory.sqlite3");
const result = await tool.execute("check", { action: "read", key: "session-test" }, undefined, undefined, {
	cwd: join(root, "../../login_demo"),
});
const response = JSON.parse(result.content[0].text);
if (!response.records.some((record) => record.key === "session-test")) throw new Error("未读取到项目记忆");
console.log(JSON.stringify(response, null, 2));
