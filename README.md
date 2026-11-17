# DSH 工作台市场

[打开市场](https://harzva.github.io/dsh-workbench-market/) · [定义与收录标准](docs/workbench-definition.md) · [机器可读索引](dist/index.json)

搜名称、任务、包名或 GitHub 仓库，包括名称里没有 `workbench` 的工作台。目录覆盖 **Dataelem DSH Desktop 原生**与 **DeepSeek Harness Web 工作台**，并标出依赖 DeepSeek 官方桌面版的项目。目录由社区维护。

## 使用

在市场按任务、类型或分类搜索，点击项目打开源仓库。Dataelem 市场条目可以在 DSH Desktop 左侧「工作台」里查找。其他项目按作者提供的宿主、版本和安装方式操作。原生清单候选暂未核到注册代码。

勾选「只看有截图」可浏览带界面截图的条目。点击缩略图在新标签页打开原图。Dataelem 市场截图来自官方索引。

## 维护目录

- `community.json` 保存逐项复核、名称和分类。新条目提供仓库、包名、版本、GitHub 清单及注册代码链接。
- `web-workbenches.json` 保存使用客户端插槽或面板接口的工作台，包括 Dataelem 会话扩展。请附固定提交的插件清单、任务流程和源码挂载证据。由另一 bundle 装载的子包可在 `assembly` 填入同提交的装载配置链接。
- `catalog-exclusions.json` 记录已核实的占位、演示和官方索引重复项，以及对应版本或工作台身份的证据。
- `discovery.json` 保存发现扫描的命中及各轮覆盖范围与失败。GitHub 搜索只覆盖可见且已索引的内容，漏收项目可提交 PR。
- `dist/` 是无需构建依赖的站点。也可直接打开 `dist/index.html` 离线使用。

有上游公开界面截图时，可在核对过的条目中提供 `screenshots`，按顺序填写同一 GitHub 仓库的原图 `url`、像素 `width`、`height` 和描述 `alt`。站点取第一张符合格式的截图。没有截图的工作台仍可正常收录。

```sh
gh auth status
python3 scripts/discover.py
python3 scripts/update_catalog.py
```

扩展扫描会检查通用插件索引链接的公开仓库，以及上一轮发现多个工作台的维护者的其他项目。补扫可以单独检查 npm 包索引声明的 GitHub 子目录。使用 `--plugin-index-only` 可以在跳过 GitHub 搜索时检查通用插件索引的根目录及子包。合并报告会保留已定位的注册证据和逐轮覆盖范围。报告里的 `webCandidates` 需要人工核对任务界面。 `review_web_candidates.py` 可将候选的客户端入口和 README 片段收集到可续跑的 JSONL，收录时仍需回到固定提交核对。

```sh
python3 scripts/discover.py --all-plugin-index --expand-from discovery.json --output .scan/expanded.json
python3 scripts/discover.py --index-subpackages --output .scan/subpackages.json
python3 scripts/merge_discoveries.py discovery.json .scan/expanded.json .scan/subpackages.json --output discovery.json
python3 scripts/update_catalog.py
python3 scripts/review_web_candidates.py --output .scan/web-dossiers.jsonl
```

加 `--client-evidence` 可复用已有的 README 记录，并扫描客户端导出与常见源码入口，记录宿主插槽和页签注册线索。源码片段仅用于缩小人工复核范围，最终仍按固定提交核实任务界面。

用 `python3 scripts/workbench_review_queue.py --dossiers .scan/web-dossiers.jsonl --output .scan/review-queue.jsonl` 可按界面和任务线索排列待复核条目。命令同时统计已收录、已人工排除、尚未读取和读取失败的候选。人工排除记录需要固定提交的证据，并对应候选的版本和观察时间。再次发现该候选的新版本或新观察时，会重新进入队列。

也可以扫描 [DeepSeek Harness 插件展示区](https://github.com/deepseek-ai/deepseek-harness/discussions/categories/show-your-plugins)。使用 GitHub GraphQL 导出该分类讨论的 `number` 和 `body`，每行一个 JSON 对象，再执行：

```sh
python3 scripts/discover.py --discussion-export .scan/plugin-discussions.jsonl --output .scan/discussions.json
python3 scripts/merge_discoveries.py discovery.json .scan/discussions.json --output discovery.json
```

外部索引列出的 GitHub 仓库也可以交给 `discover.py --repository-export` 核查。JSON 的 `indexes` 记录各索引源和条数，`repositories` 把 `owner/repo` 映射到来源列表。默认读取仓库根目录的 `package.json`。有 `packagePaths` 记录的仓库只读取列表里的路径。要同时核对根清单和子包，可填写 `["package.json", "plugins/editor/package.json"]`。索引条目只提供发现线索，仍按同一套源码标准核查。

公开 npm registry 的 `dsh-plugin`、`deepseek-harness` 和 `dsh-desktop` 关键词搜索也用于反查 GitHub 源仓库。搜索页出现重复时，按实际返回的唯一包统计。根清单扫描之外，可从 npm 版本元数据的 `repository.directory` 取出子包路径，再到 GitHub 核实对应清单、界面挂载和任务流程。[npm Registry 搜索接口](https://github.com/npm/registry/blob/main/docs/REGISTRY-API.md) · [npm repository 字段](https://docs.npmjs.com/cli/v11/configuring-npm/package-json#repository)

DSH Desk、DSH Open、DPHarness、DSHPlugin 与 DSHarness 的公开目录也参与发现。获取目录后，按 GitHub 仓库与包清单路径去重，再补扫此前未覆盖的路径。[DSH Desk 索引](https://plugin.dshdesk.com/data/plugin-index.json) · [DSH Open 索引](https://dshopen.org/index.json) · [DPHarness 索引](https://dpharness.com/market/index.json) · [DSHPlugin 数据](https://github.com/tjsdyy/dshplugin/blob/027ea85e0c717a1256c9d9412bce7667a9aa70c3/app/plugins.json) · [DSHarness 目录](https://dsharness.org/plugins)

如果要从客户端接口反查名称中看不出用途的项目，可单独执行 `python3 scripts/discover.py --code-query 'sidebarRightTabs.register in:file language:TypeScript' --output .scan/right-sidebar.json`。扫描会从命中的源码路径向上查找插件清单。新报告用 `returned` 记录 API 返回总条数，用 `read` 记录同一查询去重后的命中数。若分页期间总数变化、API 标为不完整或读取数与报告总数不符，保留 `incomplete` 状态。

发现流程只读 GitHub 的公开搜索、上游索引与源码，不安装插件。GitHub 搜索有索引延迟、结果上限和速率限制。REST 代码搜索主要覆盖默认分支和小于 384 KB 的文件，公开 fork 也有额外限制。同一仓库可在多轮出现，因此报告保留各轮的计数。[GitHub 代码搜索说明](https://docs.github.com/en/search-github/searching-on-github/searching-code#considerations-for-code-search)分类与版本证据可按 [收录标准](docs/workbench-definition.md) 复核。
