# Ws-Web-assets

Warframe Speed 站点群共享静态资产库（公开）。

- 用途：item 独立站等子项目的物品图标统一存放，经 jsDelivr CDN 直连引用
  （`https://cdn.jsdelivr.net/gh/AdminRoc/Ws-Web-assets@main/<path>`）
- 源：wiki.warframe.com（warframe.market 图片源已被 hotlink 保护封锁，实测不可用）
- 更新：`.github/workflows/harvest-icons.yml` 每日全量抓取（缺失增量下载），
  由 `.github/scripts/harvest_icons.py` 执行
- 映射：`manifest.json`（物品英文名 → `icons/<文件名>`）

## 目录

- `icons/` 物品缩略图（按 wiki 页面名规范化命名）
- `manifest.json` 物品名映射表
- `.github/` 抓取脚本与每日工作流
