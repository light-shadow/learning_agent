import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/** 配置前端开发服务器，并将 API 请求转发给本地 TypeScript 服务。 */
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:3001",
    },
  },
});
