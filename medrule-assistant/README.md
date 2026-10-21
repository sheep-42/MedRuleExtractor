# MedRuleExtractor Web Assistant

Vue 3 + TypeScript 的规则检查与编辑界面。

```bash
npm ci
npm run dev
```

先在项目根目录启动 `uvicorn extract.web_app:app --host 127.0.0.1 --port 5000`。
Vite 将 `/api` 与 `/ws` 转发到本机 5000 端口。生产构建使用 `npm run build`。
详见根目录 README。
