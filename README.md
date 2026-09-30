# Ws-Web-assets

Warframe Speed 站点群共享静态资产与运行时数据库（公开）。

- 用途：统一存放物品图标和经校验的公共运行时数据，经 jsDelivr CDN 引用
  （`https://cdn.jsdelivr.net/gh/AdminRoc/Ws-Web-assets@main/<path>`）
- 源：wiki.warframe.com（warframe.market 图片源已被 hotlink 保护封锁，实测不可用）
- 更新：`.github/workflows/harvest-icons.yml` 每日全量抓取（缺失增量下载），
  由 `.github/scripts/harvest_icons.py` 执行
- 映射：`manifest.json`（物品英文名 → `icons/<文件名>`）

## 目录

- `icons/` 物品缩略图（按 wiki 页面名规范化命名）
- `manifest.json` 物品名映射表

## 公共运行时数据

`runtime-data-contract.json` 独立声明非 item 运行时数据的生产者、输出范围与消费者；它不扩展
`item-artifact-contract.json`。`publish-runtime-data.yml` 使用固定版本的 Ws-Web-core 生成
仲裁基准、共享翻译、国服节点名和 Tenet/Coda 轮换数据，只提交该运行时数据合同列出的 Assets
路径，并在发布后清理 jsDelivr 的可变 `@main` 缓存并校验可变路径与不可变 commit 路径的完整字节。

- 本流程不 checkout 或写入 Ws-Web 非 item 路径，也不接触榜单源文件/bundle。
- `data/item/**` 仍只由 item 合同声明的流程读取、镜像与发布；本流程只读取其中的
  `item-names-zh.json` 作为共享翻译输入，不写 item 数据。
- `Ws-Web-assets` 是数据生产与公共引用仓库，不是 EdgeOne Maker 网站构建目标；Action 中的
  build/publish 指数据处理、Git/CDN 发布，不代表 Maker 部署。
- EELog 使用独立的 `data/eelog-runtime-release.json`，只在依赖产物已验证后更新；World 页面保留
  本地 `wf-translations.js` 回退，并叠加此仓库经过发布验证的共享脚本。

详细边界和运行步骤见 [runtime-data-release.md](docs/runtime-data-release.md)。
- `.github/` 抓取脚本与每日工作流
