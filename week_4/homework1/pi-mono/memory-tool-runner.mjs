/** 在独立 Node 进程中加载 pi 扩展并调用记忆工具。 */
import { createJiti } from "jiti/static";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const jiti = createJiti(import.meta.url, { interopDefault: true, tryNative: false, moduleCache: false });
const extension = await jiti.import(join(root, ".pi/extensions/project-memory.ts"), { default: true });
let tool;
extension({ registerTool(value) { tool = value; } });
const input = JSON.parse(process.argv[2]);
const result = await tool.execute("verify", input, undefined, undefined, { cwd: join(root, "../../login_demo") });
console.log(result.content[0].text);
