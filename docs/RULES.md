# InsightHub Rules

These rules are long-term invariants.

## RULE-001 — Raw Data Immutable

`data/raw` 一旦写入，原始上传文件不得被后续处理覆盖、修改或替换。派生结果写到其他目录。

## RULE-002 — Evidence First

知识链必须保持：

```text
Source
→ SourceVersion
→ ExtractedDocument
→ Chunk
→ Claim
→ Evidence
→ Analysis
→ Knowledge
```

禁止 `Source → 无来源 AI 总结`。

## RULE-003 — Citation Traceability

所有重要事实应尽可能追溯到 `Source + Chunk + Evidence`。

## RULE-004 — Fact / Claim / Inference Separation

必须区分 `FACT`、`SOURCE_CLAIM`、`INFERENCE`、`HYPOTHESIS`、`UNKNOWN`。禁止把模型推断伪装成来源事实。

## RULE-005 — Source Versioning

网页内容未来可能变化。不得覆盖旧版本。必须支持 `SourceItem → SourceVersion[]`。

## RULE-006 — Analysis Versioning

重新调用模型不得覆盖历史结果。必须保留 `model`、`provider`、`prompt_version`、`source_version`、`created_at`。

## RULE-007 — Prompt Versioning

业务 Prompt 不允许散落在 Python 源码中。集中放在 `prompts/`，并具有版本信息。

## RULE-008 — Provider Independence

业务层禁止直接依赖 DeepSeek SDK、SiliconFlow SDK、LM Studio 或某一家模型 API。必须通过统一 `LLMProvider` 接口。DeepSeek 与 SiliconFlow 只作为 OpenAI-compatible 部署的厂商标识，不各写一套 HTTP 客户端。Analysis、Ask Planner、Ask Answer、Brief 按工作流选择部署。本地路由失败不得自动改走云端。

## RULE-009 — Privacy Routing

未来内容至少支持 `PUBLIC`、`PRIVATE`、`SENSITIVE`。`SENSITIVE` 默认 `LOCAL_ONLY`。聊天模型从本地改为云端必须由用户在 Settings 里明确选择，失败时不得静默外发。

## RULE-010 — Secrets Never in Git

禁止提交 API Key、Token、Password 或真实 Secret。

## RULE-011 — External Content Is Untrusted

网页、PDF、截图、RAG 内容统一视为 `UNTRUSTED_CONTENT`。其中出现的 “Ignore previous instructions”、上传密钥或运行命令等文本不能成为系统指令。

## RULE-012 — Dedup Does Not Mean Delete

发现重复内容时，默认建立重复关系。禁止未经明确策略直接删除历史 Source。

## RULE-013 — No Silent Data Loss

如果 20 个 Source 中 18 个成功、2 个失败，任何综合分析和 Brief 必须明确说明 `18 / 20 included` 与 `2 failed`。禁止静默忽略。

## RULE-014 — Category Is Configurable

默认存在“发现项目、商业、知识、其他”，但底层不能使用不可扩展 enum 写死产品逻辑。

## RULE-015 — Project Candidate ≠ Project

AI 可以创建 `ProjectCandidate`，不能未经用户确认自动升级为正式 `Project`。

## RULE-016 — Brief Uses Existing Evidence

Brief 默认走 `Source → AnalysisResult → Claim/Evidence → Cross-source Synthesis`。不得无条件重新调用模型阅读全部原文。

## RULE-017 — Brief URL Preservation

任何存在 `canonical_url` 或 `original_url` 的 Source，在最终 Brief 的 Source Index 中必须保留可点击链接。

## RULE-018 — Jobs for Long-running Work

OCR、Browser Fetch、LLM、Embedding、Batch Analysis、Large Export 必须走 Job。禁止长任务长期阻塞 HTTP request。

## RULE-019 — Schema Changes Through Alembic

禁止手工直接修改生产数据库 Schema。所有 Schema 变化必须是 SQLAlchemy model 加 Alembic migration。

## RULE-020 — No Premature Infrastructure

MVP 不得无理由加入 Kubernetes、Kafka、Elasticsearch、Milvus、MinIO 或微服务拆分。

## RULE-021 — Verification Before DONE

任何 Milestone 标记 DONE 前必须完成对应的 pytest、frontend build、frontend tests、migration check 与 required integration tests。

## RULE-022 — Test Visibility Uses system_scope

自动化与日常数据的可见性隔离必须只依赖 `system_scope`（例如 `USER` 与 `AUTOMATION_TEST`）。生产查询不得根据 `title`、`display_name`、URL 前缀或名称子串推断“这是测试数据”。

## RULE-023 — Browser Extraction SSRF

网页浏览器渲染回退必须复用与静态 HTTP 获取相同的出站 URL / SSRF 策略。浏览器上下文不得访问 loopback、私网、链路本地或元数据地址；不得持久化 cookies、不得绕过 CAPTCHA / 登录墙、不得使用 stealth 或反爬绕过。
