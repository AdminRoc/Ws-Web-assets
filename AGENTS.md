# Ws-Web-assets — AI 协作指引

公开资产仓库，供 Warframe Speed 站点群（Ws-Web 主站及各独立站：eelog/map/item 等）经 jsDelivr 引用图片资产。

## 引用方法（其他页面/项目）

所有引用一律通过 **manifest.json** 查表，禁止手拼文件名：

```js
// 浏览器端（item.html 同款逻辑）
fetch('https://cdn.jsdelivr.net/gh/AdminRoc/Ws-Web-assets@main/manifest.json')
  .then(r => r.json())
  .then(manifest => {
    const path = manifest['Soma Prime Set'];        // -> "icons/Soma_Prime_Set.png"
    if (path) img.src = 'https://cdn.jsdelivr.net/gh/AdminRoc/Ws-Web-assets@main/' + path;
  });
```

- 直接图片 URL 模式：`https://cdn.jsdelivr.net/gh/AdminRoc/Ws-Web-assets@main/<manifest值>`
- manifest 键 = 物品**英文原名**（含数量前缀与变体后缀，如 `750X Alloy Plate`、`Axi V14 Relic (Radiant)`）
- 键缺失 = 仓库无此图，调用方自行降级（占位图/不显示）
- jsDelivr 对 `@main` 有约 12h 缓存延迟；急用可临时换 commit SHA：`@<sha>`

## 目录与命名规范

- `icons/<Normalized_en>.<ext>`：文件名 = 英文名规范化（非 `[A-Za-z0-9_.-]` 字符转 `_`）
  - 例：`Soma Prime Set` → `Soma_Prime_Set.png`；`albrecht's archive` → `albrecht_s_archive.png`
- 扩展名跟随所选源（WM 源多为 `.webp`，wiki 源多为 `.png`）
- `manifest.json`：`{ "英文原名": "icons/<文件名>" }`，**唯一引用入口**（文件名为存储键，引用必走 manifest）
- 文件名冲突（两 en 归一化后相同）：以 manifest 键区分，文件按首个出现保留

## 来源与质量优先级

多源智能比对规则（upgrade_icons.py 已执行，新增条目照此执行）：

1. **wiki.warframe.com 600px 缩略图**（API `prop=pageimages&pithumbsize=600&redirects=1`）——默认首选
2. **Warframe.market 官方图标**——仅当 WM 原图面积 ≥ wiki 版时保留（WM 源已被 hotlink 保护封锁，无法服务器端抓取；本地过验证的 Playwright 会话可爬，流程见历史）
3. 比对标准 = **像素面积（宽×高）**，取大者
4. 部件名归一化：`Soma Prime Set/Blueprint/Barrel/...` 查询 wiki 时逐层剥离部件后缀（Set/Blueprint/Barrel/Receiver/Stock/Grip/Blade/Handle/Link/Neuroptics/Chassis/Systems/Head/Ornament/Guard/String/Scabbard/Pouch/Limb/Lower/Upper/Main/Weapon/Skin/Helmet/Sigil）回退到主页面（如 `Soma Prime`）

## 增量更新（每日）

`.github/workflows/harvest-icons.yml`（UTC 02:37）+ 手动 Run：

- `.github/scripts/harvest_icons.py`：读 Ws-Web 公库 `wm-items.json`/`drops-index.json`（公开 raw 直拉）→ 只补 **WM 无图标（unknown.png）** 与 **掉落专属** 物品的 wiki 图标 → 与现有 manifest 合并 → 增量下载缺失文件 → 有变化才提交
- 幂等：文件存在即跳过；不 churn git 历史
- 新物品命名：wiki 页名 `safe_file()` 规则（同"命名规范"，空格转 `_`）——与 manifest 键（原 en）分离

## 质量升级（一次性/按需）

`.github/scripts/upgrade_icons.py`：全量 wiki 600px 查询 → 面积比对选优 → 统一命名 → 孤儿清理。
注意：升级后必须跑 manifest 缺失校验（见下），个别条目（如 Arcane 系列）wiki 匹配异常时需从 git 历史恢复。

## 完整性校验（改动后必跑）

```python
import json, os
m = json.load(open('manifest.json', encoding='utf-8'))
missing = [k for k, v in m.items() if not os.path.exists(v)]
assert not missing, missing
```

## 注意事项

- **不要**把 jsDelivr URL 硬编码进各站源码（版本管理依赖 manifest）；item 独立站已实现 manifest 优先 + 旧兜底链路
- **不要**在 .gitignore 忽略 `manifest.json` 或 `icons/`（部署/引用依赖）
- 本库是**公开**仓库：不含任何密钥/敏感数据；抓取 UA 标注 `wfspeed-assets/1.0` 非商业用途
- warframe.market 图片：服务器端（GitHub Actions/本地脚本）**必然 403**（Bot 防护按 TLS 指纹/IP），唯一可行通道是浏览器验证会话（cf_clearance 等 cookies，时效约 30min）；需要批量补 WM 图时复用"Playwright 过验证 → 导出 cookies → 本地带 cookies 并发下载"流程
