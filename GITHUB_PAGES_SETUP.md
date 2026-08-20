# GitHub Pages 部署问题排查指南

## ❗ 问题确认

**当前状态**：
- ✅ `docs/` 目录已生成 HTML
- ✅ 代码已推送到 GitHub
- ✅ GitHub Actions 工作流配置正确
- ⚠️ **GitHub Pages 可能未启用或未自动部署**

## 🔧 解决步骤

### 步骤 1: 启用 GitHub Pages

1. 访问 GitHub 仓库：https://github.com/LeisureLinux/on-stock
2. 点击 **Settings** (设置)
3. 点击左侧 **Pages**
4. 在 "Build and deployment" 部分：
   - **Source**: 选择 `Deploy from a branch`
   - **Branch**: 选择 `main`
   - **Folder**: 选择 `/ (root)` 或 `/docs`
5. 点击 **Save**

### 步骤 2: 等待自动部署

- GitHub Pages 通常会在 **3-5 分钟**内自动部署
- 访问：https://leisurelinux.github.io/on-stock/
- 访问自定义域名：https://stock.freelamp.com/

### 步骤 3: 如果仍然失败，手动触发

1. 访问：https://github.com/LeisureLinux/on-stock/actions
2. 点击左侧 **Manual Deploy** 工作流
3. 点击 **Run workflow** 按钮
4. 等待构建完成（约 2-3 分钟）

## 📊 验证清单

- [ ] GitHub仓库 Settings → Pages 已启用
- [ ] Source 设置为 `main` branch
- [ ] Folder 设置为 `/docs`
- [ ] Custom Domain 设置为 `stock.freelamp.com`
- [ ] 提交后等待 3-5 分钟

## 🚨 常见问题

### 问题 1: GitHub Pages 没有自动部署
**解决**: 手动触发 Workflow 或使用上面的步骤 3

### 问题 2: 自定义域名无法访问
**解决**:
1. 确保已添加 CNAME 文件（已有）
2. 在域名提供商处添加 CNAME 记录：
   - **Type**: CNAME
   - **Host**: @ 或 stock.freelamp.com
   - **Value**: leisurelinux.github.io

### 问题 3: 部署失败
**解决**:
1. 检查 GitHub Actions 构建日志
2. 确保 Python 版本兼容
3. 检查 build.py 是否运行成功

## 🎯 当前配置

- **仓库**: https://github.com/LeisureLinux/on-stock
- **域名**: stock.freelamp.com
- **源分支**: main
- **源目录**: /docs
- **构建脚本**: build.py
- **CNAME**: stock.freelamp.com ✅

请按照上述步骤操作，通常 **步骤 1** 就能解决问题！
