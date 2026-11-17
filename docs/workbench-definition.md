# 什么是 DSH 工作台

在本目录里，DSH 工作台是 **嵌入受支持的 DeepSeek Harness 宿主、让用户通过可重新打开的界面完成一项具体工作的应用**。面板可占主区域、使用可切换的独立分栏，或放在会话旁。它应把任务所需的操作、对象或状态集中在这个界面里。是否有自己的会话、是否包含模型调用、仓库名称如何命名，都由具体项目决定。

## DeepSeek 官方提供什么

在核对的 DeepSeek Harness 上游版本 `39163dd`，Workspace 是按工作目录组织 Session 的对象。Web 宿主支持全局业务面板与会话级右栏扩展，官方 Electron 桌面壳也运行该 Web 宿主。同一上游还有一个通用插件发现页，使用 format-1 插件索引。本目录把这些作为宿主能力依据，在该版本未发现 DeepSeek 官方专用的工作台注册接口或工作台市场。

- [Workspace 与 Session](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-workspace/README.md#L12-L14)
- [全局业务面板 main slot](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-layout/README.md#L34-L38)
- [会话右栏注册接口](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/packages/client/ui-sidebar-right/README.md#L81-L88)
- [官方 Electron 桌面壳](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/apps/desktop/README.md#L38-L44)
- [通用插件发布协议](https://github.com/deepseek-ai/deepseek-harness/blob/39163dd30f703a79079e2d2446545cff3c453738/docs/user/develop/basic/publish.md#L11-L16)

Dataelem 的 DSH Desktop 提供自己的原生工作台服务。工作台包是 DSH bundle，导出客户端，声明 `dsh-desktop-workbenches` 注入，并通过 `desktopWorkbenches.register()` 或其可核对的别名注册业务界面。[Dataelem 工作台开发规范](https://github.com/dataelement/dsh-desktop/blob/bbc7494aa9ed1cda0b89888264d7ee74a26ec50e/packages/dsh-desktop-workbenches/development-guide.zh.md#L57-L63) · [Dataelem 市场验收规范](https://dshdesktop.com/workbench/docs/market-acceptance/)

## 收录标准

| 目录状态 | 所需依据 |
| --- | --- |
| Dataelem 市场收录 | 市场实时索引含该条目。 |
| Dataelem 注册已核 | 固定版本的 bundle 声明、客户端导出与实际注册位置。 |
| DSH Web 已核 | 可核对的 DSH 插件清单和宿主挂载证据，界面中有可描述的任务流程，例如小说写作、项目分屏或会话侧文件工作。 |
| Dataelem 清单候选 | 有原生工作台声明，注册代码暂未核到。候选与已核条目可分别筛选。 |

一般设置页、独立按钮、通知、主题、单独 Skill、MCP 工具、CLI 或仅演示用的文档不计为已核工作台。如果一个插件还注册了具有完整任务流程的界面，可以按那个工作台收录。仅做主题展示的注册项需要人工标记审查；同一包的镜像和相同内容分支合并，独立维护且具备不同功能的派生包可单列。GitHub monorepo 包路径作为独立证据。

目录描述的是公开证据与宿主适用范围。安装、运行、版本兼容性和数据处理权限各自需要实机检查。
