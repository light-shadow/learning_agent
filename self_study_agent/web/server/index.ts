import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import express, { type NextFunction, type Request, type Response } from "express";
import multer from "multer";

const currentDirectory = dirname(fileURLToPath(import.meta.url));
const projectDirectory = resolve(currentDirectory, "../..");
const databasePath = join(projectDirectory, "data", "study_agent.sqlite3");
const uploadDirectory = join(projectDirectory, "data", "uploads");
const pythonPath = process.env.STUDY_AGENT_PYTHON ?? join(projectDirectory, ".venv", "Scripts", "python.exe");
const allowedExtensions = new Set([".pdf"]);

/** 确保上传资料目录存在，避免将临时文件散落到系统目录。 */
function ensureUploadDirectory(): void {
  mkdirSync(uploadDirectory, { recursive: true });
}

/** 校验学习者标识，防止其作为非受控 CLI 参数传递。 */
function learnerId(value: unknown): string {
  const candidate = typeof value === "string" ? value.trim() : "default";
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(candidate)) {
    throw new Error("学习者标识仅支持字母、数字、下划线和短横线，长度不超过 64。");
  }
  return candidate || "default";
}

/** 将 Express 路由参数收敛为单个受控字符串。 */
function routeParameter(value: string | string[] | undefined): string {
  return Array.isArray(value) ? value[0] ?? "" : value ?? "";
}

/** 修复 multipart 将 UTF-8 中文文件名误按 Latin-1 解码后的常见乱码。 */
function normalizeUploadFileName(fileName: string): string {
  const looksLikeUtf8Mojibake = /[\u00c2-\u00f4][\u0080-\u00bf]/.test(fileName);
  if (!looksLikeUtf8Mojibake) return fileName;
  const decoded = Buffer.from(fileName, "latin1").toString("utf8");
  return decoded.includes("\ufffd") ? fileName : decoded;
}

/** 调用既有 Python CLI，并将其受控 JSON 结果转换为 API 响应。 */
function runCli(argumentsList: string[]): Promise<unknown> {
  return new Promise((resolveResult, rejectResult) => {
    const child = spawn(pythonPath, ["-m", "study_agent", "--database", databasePath, ...argumentsList], {
      cwd: projectDirectory,
      windowsHide: true,
    });
    let standardOutput = "";
    let standardError = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      standardOutput += chunk;
    });
    child.stderr.on("data", (chunk: string) => {
      standardError += chunk;
      process.stderr.write(`[study-agent] ${chunk}`);
    });
    child.on("error", (error) => rejectResult(new Error(`无法启动 Python CLI：${error.message}`)));
    child.on("close", (code) => {
      try {
        const parsed = JSON.parse(standardOutput) as unknown;
        if (code !== 0) {
          rejectResult(new Error(JSON.stringify(parsed)));
          return;
        }
        resolveResult(parsed);
      } catch {
        rejectResult(new Error(standardError || standardOutput || `CLI 退出码：${code}`));
      }
    });
  });
}

/** 将异步路由中的异常统一转交给 Express 错误处理中间件。 */
function route(handler: (request: Request, response: Response) => Promise<void>) {
  return (request: Request, response: Response, next: NextFunction): void => {
    handler(request, response).catch(next);
  };
}

ensureUploadDirectory();
const upload = multer({
  storage: multer.diskStorage({
    destination: (_request, _file, callback) => callback(null, uploadDirectory),
    filename: (_request, file, callback) => callback(null, `${randomUUID()}${extname(file.originalname).toLowerCase()}`),
  }),
  limits: { fileSize: 20 * 1024 * 1024 },
  fileFilter: (_request, file, callback) => {
    callback(null, allowedExtensions.has(extname(file.originalname).toLowerCase()));
  },
});

const app = express();
app.use(express.json({ limit: "128kb" }));

app.get("/api/health", (_request, response) => {
  response.json({ ok: existsSync(pythonPath), pythonPath });
});

app.post("/api/sources/file", upload.single("file"), route(async (request, response) => {
  if (!request.file) {
    response.status(400).json({ message: "请选择 AI Agent 学习 PDF 文件。" });
    return;
  }
  response.json(await runCli([
    "import", request.file.path, "--title", normalizeUploadFileName(request.file.originalname),
  ]));
}));

app.get("/api/sources", route(async (_request, response) => {
  response.json(await runCli(["sources"]));
}));

app.get("/api/sources/:sourceId/concepts", route(async (request, response) => {
  response.json(await runCli(["concepts", "--source-id", routeParameter(request.params.sourceId)]));
}));

app.post("/api/sources/:sourceId/concepts/extract", route(async (request, response) => {
  response.json(await runCli(["extract", routeParameter(request.params.sourceId)]));
}));

app.post("/api/sources/:sourceId/generate", route(async (request, response) => {
  response.json(await runCli(["generate", routeParameter(request.params.sourceId)]));
}));

app.get("/api/sources/:sourceId/history", route(async (request, response) => {
  const limit = Math.max(1, Math.min(100, Number(request.query.limit) || 50));
  response.json(await runCli([
    "--learner-id", learnerId(request.query.learnerId),
    "history", "--source-id", routeParameter(request.params.sourceId), "--limit", String(limit),
  ]));
}));

app.get("/api/quiz", route(async (request, response) => {
  const count = Math.max(1, Math.min(20, Number(request.query.count) || 10));
  const argumentsList = ["--learner-id", learnerId(request.query.learnerId), "quiz", "start", "--count", String(count)];
  if (typeof request.query.sourceId === "string" && request.query.sourceId) {
    argumentsList.push("--source-id", request.query.sourceId);
  }
  response.json(await runCli(argumentsList));
}));

app.post("/api/quiz/answer", route(async (request, response) => {
  const questionId = typeof request.body.questionId === "string" ? request.body.questionId : "";
  const answer = typeof request.body.answer === "string" ? request.body.answer : "";
  if (!questionId || !answer.trim()) {
    response.status(400).json({ message: "题目和答案不能为空。" });
    return;
  }
  response.json(await runCli(["--learner-id", learnerId(request.body.learnerId), "quiz", "answer", questionId, answer]));
}));

app.get("/api/review", route(async (request, response) => {
  response.json(await runCli(["--learner-id", learnerId(request.query.learnerId), "review"]));
}));

app.get("/api/audit", route(async (_request, response) => {
  response.json(await runCli(["audit"]));
}));

const distDirectory = join(projectDirectory, "web", "dist");
if (existsSync(distDirectory)) {
  app.use(express.static(distDirectory));
  app.get("/{*path}", (_request, response) => response.sendFile(join(distDirectory, "index.html")));
}

/** 输出受控错误信息，避免将 Python 堆栈或密钥暴露给浏览器。 */
app.use((error: Error, _request: Request, response: Response, _next: NextFunction) => {
  const message = error.message.length > 1200 ? "服务执行失败，请查看本地服务日志。" : error.message;
  response.status(500).json({ message });
});

app.listen(3001, "127.0.0.1", () => {
  console.log("自学 Agent API 已启动：http://127.0.0.1:3001");
});
