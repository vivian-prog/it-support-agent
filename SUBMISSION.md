# 提交材料清单 / Submission index

整理日期：2026-10-22。项目：IT Companion 员工 IT 支持助手。

## 建议阅读顺序

1. [README.md](README.md)：范围、启动、架构、工具、状态管理、转人工条件、评估和上线取舍。
2. [用一个 VPN 问题理解项目](docs/用一个VPN问题理解项目.md)：已执行的真实模型对话、工具调用和最终结果。
3. [测试记录](docs/VALIDATION.md)及[真实模型评估报告](docs/新增真实模型测试报告-2026-10-22.md)：验证范围、失败、修复及复测。
4. [AI 使用说明](docs/AI_USAGE.md)：工作来源和人工参与范围。

## 作业要求与材料对应

| 要求 | 提供的材料 |
|---|---|
| 可运行源码及设置说明 | `app/`、`web/`、`requirements*.txt`、README；Python 3.9+，规则演示无需安装依赖 |
| 问题范围、为什么使用 Agent | README 的 Problem and scope、Architecture |
| 多轮诊断、多步工具、记忆 | `app/agent.py`、`app/tools.py`、`app/store.py`；工具记录在界面可展开查看 |
| 至少 2–3 类模拟来源 | `data/fixtures.json`；员工档案、状态、知识库、历史案例、操作规则 |
| 解决与转人工的边界 | README 的 Resolution vs. escalation；本地交接样例 `docs/example-handoff.json` |
| 模糊输入、资料冲突、工具失败等处理 | `tests/`、`evaluation/cases.json`、`evaluation/extended-cases.json` |
| 评估、安全、观测、费用与维护 | README；`evaluation/` 原始报告；`docs/DESIGN_DECISIONS.md` |
| 假设、限制、改进及可选生产化说明 | README 的 Reliability, safety and production thinking |
| 面试演示支持 | 应用支持现场输入新问题；本包未附录像 |

## 启动

解压后在终端进入 `it-support-agent` 目录：

```sh
python3 -m app.server
```

打开 http://127.0.0.1:8765 。Windows 可使用 `py -3 -m app.server`。端口占用时追加 `--port 8766`，并打开对应端口。

默认是界面明确标注的规则演示。真实模型接入有两种：原有 OpenAI API Key 和新增 ChatGPT 授权，步骤见 README。接收方需使用自己的密钥或账号并具备相应权限；压缩包不含已登录账号、API Key、数据库或虚拟环境。ChatGPT 授权需另装可选依赖，运行时会消耗相应账号额度。

## 已验证范围

- 单元与集成测试：44/44；确定性场景：19/19。打包后的干净解压复核见 `docs/PACKAGE_VALIDATION.md`。
- ChatGPT 真实模型：已验证授权、模型目录和工具调用；13 个新增模拟案例首次 11/13，修复及定向复测后逐案例最新结果 13/13。**不是最终版本一次完整跑出的 13/13**，也不是独立测试集或生产准确率。
- API Key 模式保留，协议有模拟测试，尚未用真实 API Key 调用。
- 工具数据全部模拟，状态时钟固定为 2026-04-21。交接只生成本地 JSON，没有发送给 IT 或 ServiceNow。没有公司 SSO 或设备操作能力。

## 提交与面试前的个人准备

本包提供完整源码目录。若招聘方指定 Git 仓库链接，需将干净源码上传到自己的仓库并提供链接；本次未创建远程仓库或代发提交。面试时需由候选人本人解释实际理解和参与的部分，完成自己的启动及演示练习；本包不把助手执行的测试算作候选人独立完成的工作。

`MANIFEST.json` 列出包内文件和 SHA-256，便于核对材料完整性。
