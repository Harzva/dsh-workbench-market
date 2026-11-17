# DSH 工作台市场

[打开市场](https://harzva.github.io/dsh-workbench-market/) · [定义与收录标准](docs/workbench-definition.md) · [机器可读索引](dist/index.json)

搜名称、任务、包名或 GitHub 仓库，包括名称里没有 `workbench` 的工作台。目录覆盖 **Dataelem DSH Desktop 原生**与 **DeepSeek Harness Web 工作台**，由社区维护。

## 使用

在市场按任务、类型或分类搜索，点击项目打开源仓库。Dataelem 市场条目可以在 DSH Desktop 左侧「工作台」里查找。其他项目按作者提供的宿主、版本和安装方式操作。原生清单候选暂未核到注册代码。

## 维护目录

- `community.json` 保存逐项复核、名称和分类。新条目提供仓库、包名、版本、GitHub 清单及注册代码链接。
- `web-workbenches.json` 保存 DSH Web 工作台。请附固定提交的插件清单与用户任务或挂载的源码证据。
- `discovery.json` 保存最近一次发现扫描的命中、覆盖范围及失败。GitHub 搜索只覆盖可见且已索引的内容，漏收项目可提交 PR。
- `dist/` 是无需构建依赖的站点。也可直接打开 `dist/index.html` 离线使用。

```sh
gh auth status
python3 scripts/discover.py
python3 scripts/update_catalog.py
```

发现流程只读 GitHub 的公开搜索、上游索引与源码，不安装插件。GitHub 搜索有索引延迟、结果上限和速率限制。分类与版本证据可按 [收录标准](docs/workbench-definition.md) 复核。
