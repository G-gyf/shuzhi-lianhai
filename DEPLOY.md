# 线上部署指南（GitHub Pages + Railway）

目标：前端网页托管在 GitHub Pages，后端 API 跑在 Railway，
任何人通过网址访问。以下步骤一半在浏览器操作（需要你的 GitHub 账号），
一半在命令行。

## 第 1 步：本地 git 初始化并推送 GitHub

```bash
cd 数智链海
git init -b main
git add .
git commit -m "shuzhi-lianhai demo: api + web + kb snapshot"
```

浏览器：github.com → New repository（公开）→ 名称如 `shuzhi-lianhai`
→ **不要**勾选初始化 README（本地已有）→ Create。

```bash
git remote add origin https://github.com/<你的用户名>/shuzhi-lianhai.git
git push -u origin main
```

> 注：仓库含 47MB 的 kb-2023.sqlite，首次推送需要几分钟，属正常。

## 第 2 步：Railway 部署后端

1. 打开 railway.com → New Project → Deploy from GitHub repo → 选 `shuzhi-lianhai`
   （Railway 自动识别 Dockerfile 构建，约 3-6 分钟）；
2. 部署完成后在 Settings → Networking → Generate Domain，得到形如
   `https://shuzhi-lianhai-production.up.railway.app` 的网址；
3. 验证：浏览器打开 `https://<你的域名>/api/health`，看到
   `{"status":"ok","kb":"kb-2023"}` 即成功；
4. （可选）在项目 Settings 里把"Sleep"关掉或改为较长空闲时间，避免冷启动。

## 第 3 步：开启 GitHub Pages（前端）

1. 修改 `web/config.js` 第一行：

   ```js
   window.DSH_API_BASE = "https://<你的 Railway 域名>";   // 不要带末尾 /
   ```

2. 提交并推送：

   ```bash
   git add web/config.js
   git commit -m "point frontend to railway api"
   git push
   ```

3. GitHub 仓库 → Settings → Pages → Source 选 **GitHub Actions**
   （workflow 已写好，push 后自动部署，约 1 分钟）；
4. 访问 `https://<用户名>.github.io/shuzhi-lianhai/` ——这就是对外网址。

## 第 4 步：验证线上闭环

打开 Pages 网址 → 顶部应显示"● 知识库 kb-2023 在线" → 选省份 → 点企业 →
看证据高亮 → 生成简报。全部可用即部署完成。

## 常见问题

- **Pages 页面显示"服务连接失败"**：config.js 的 Railway 域名没改或多了斜杠；
  浏览器 F12 → Network 看 /api/meta 请求的地址是否正确。
- **Railway 首次构建失败**：打开 Deploy Logs，把日志发我；
  常见原因是推送时漏了文件（确认 kb/kb-2023.sqlite 已在仓库）。
- **数据更新**：重新生成 kb 快照后 `git add kb/ && git commit && git push`，
  Railway 自动重建（数据是只读快照，内置在镜像中，无需数据库服务）。
- **本地开发不受影响**：本地 `start.bat` 依然可用（config.js 留空即同源）。
