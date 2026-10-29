# InsightHub

InsightHub 是自托管的研究与学习工作台，用于收集资料、提取内容、基于证据进行 AI 分析，并构建可搜索的个人知识库。

## 快速开始

容器化安装请阅读[简体中文安装指南](docs/INSTALL.zh-CN.md)或[English installation guide](docs/INSTALL.en.md)。Windows 本机安装请阅读[本机安装说明](docs/INSTALL-LOCAL.zh-CN.md)或[English local guide](docs/INSTALL-LOCAL.en.md)。贡献者环境请阅读[开发环境说明](docs/DEVELOPMENT.md)。

默认容器部署会将 PostgreSQL、Redis、上传文件、导出文件和加密凭据保存在持久化卷中。首次启动后，请在应用内配置 Provider 凭据。本仓库不包含模型 API Key。

## 功能

- 收集网址、文本和常见文档。
- 提取并保留带来源信息的资料内容。
- 通过已配置的 Provider 执行证据导向的 AI 分析。
- 浏览、搜索并询问已保存的研究资料。
- 生成学习笔记和可选封面图片。
- 将原始上传文件与生成资产保存在本地持久化存储。

## 环境要求

- 推荐使用 Docker Engine 和 Docker Compose v2。
- Windows 本机安装需要 CPython 3.11.16 和 Node.js 22。
- 可选：独立托管的 BGE-M3 兼容 Embedding 服务。请查看[官方模型卡](https://huggingface.co/BAAI/bge-m3)和部署说明；本仓库不分发模型权重或 Embedding 服务。

## 许可证

InsightHub 自有代码采用 **GNU AGPL-3.0-only**，详见 [LICENSE](LICENSE)。用户可以使用、修改、分发并将其用于商业场景，但必须遵守许可证义务，包括分发时保留许可证与声明；修改版本若通过网络向用户提供交互，还必须免费提供对应源代码访问方式。第三方组件仍适用各自许可证，请查看[第三方许可证说明](docs/THIRD-PARTY-LICENSES.md)。

## 发布记录

见 [CHANGELOG.md](CHANGELOG.md) 和 [v1.0.0 发布说明](docs/RELEASE-v1.0.0.md)。
