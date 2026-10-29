"""Frozen benchmark contract for V1.0-PILOT-03B-R1."""

from __future__ import annotations

BENCHMARK_NAME = "pilot_03b_r1"
PROMPT_ANALYSIS = "source_analysis 1.1.0"

PROVIDER_DEEPSEEK = "DEEPSEEK"
PROVIDER_GLM = "SILICONFLOW"
MODEL_DEEPSEEK = "deepseek-v4-pro"
MODEL_GLM = "zai-org/GLM-5.3-Flash"

ANALYSIS_RUNS_PER_SOURCE = 3
PLANNER_RUNS_PER_QUERY = 2
ASK_RUNS_PER_QUERY = 3
BRIEF_RUNS_PER_CASE = 3

# USER source ids (read-only corpus); benchmark writes only on AUTOMATION_TEST clones.
CORPUS_CASES: list[dict] = [
    {"case_id": "openkb", "user_source_id": "b0ef2dac-661b-44f4-8c78-c631f7c6a91f"},
    {"case_id": "gpt_live", "user_source_id": "94bab2e9-814e-448e-a9c2-de95fce32859"},
    {"case_id": "videolingo", "user_source_id": "9c048eb7-67eb-400d-ab62-5286aa7f1abd"},
    {"case_id": "ml_marimo", "user_source_id": "e5c51883-6e83-4185-824b-4b06e9389d14"},
    {"case_id": "long_text", "user_source_id": "366d9615-de78-420e-930a-18475a6f582c"},
    {"case_id": "mixed_karpathy", "user_source_id": "a092cb3d-333f-423c-8770-def3ebb7911e"},
]

PLANNER_QUERIES: list[dict] = [
    {"id": "q1", "text": "总结我收藏的 OpenKB 资料的核心内容。", "expected": "FOCUSED"},
    {"id": "q2", "text": "最近收藏的资料中有哪些值得进一步关注的 AI 工具或项目？", "expected": "FOCUSED"},
    {"id": "q3", "text": "这几篇资料分别讲了什么？", "expected": "COVERAGE"},
    {"id": "q4", "text": "哪些资料与知识管理有关？", "expected": "FOCUSED"},
    {"id": "q5", "text": "OpenKB 和传统 RAG 的区别是什么？", "expected": "FOCUSED"},
    {"id": "q6", "text": "哪些内容只是作者观点，不是已验证事实？", "expected": "COVERAGE"},
    {"id": "q7", "text": "给我总结最近收藏的机器学习可视化相关资料。", "expected": "FOCUSED"},
    {"id": "q8", "text": "What are the main AI tools in my recent collection?", "expected": "FOCUSED"},
    {"id": "q9", "text": "VideoLingo 这类工具主要解决什么问题？", "expected": "FOCUSED"},
    {"id": "q10", "text": "我收藏的资料里有哪些提到 Karpathy？", "expected": "FOCUSED"},
    {"id": "q11", "text": "分别列出每篇资料提到的 GitHub 项目。", "expected": "COVERAGE"},
    {"id": "q12", "text": "哪些资料适合进一步做深入阅读？", "expected": "FOCUSED"},
]

ASK_QUERIES: list[dict] = [
    {"id": "aq1", "text": "总结我收藏的 OpenKB 资料的核心内容。"},
    {"id": "aq2", "text": "最近收藏的资料中有哪些值得进一步关注的 AI 工具或项目？"},
    {"id": "aq3", "text": "这几篇资料分别讲了什么？"},
    {"id": "aq4", "text": "哪些内容只是作者观点，不是已验证事实？"},
    {"id": "aq5", "text": "给我总结最近收藏的机器学习可视化相关资料。"},
    {"id": "aq6", "text": "What are the main AI tools in my recent collection?"},
    {"id": "aq7", "text": "VideoLingo 这类工具主要解决什么问题？"},
    {"id": "aq8", "text": "OpenKB 和传统 RAG 的区别是什么？"},
]

BRIEF_CASES: list[dict] = [
    {
        "case_id": "brief_x_trio",
        "filters": {
            "start_date": "2026-10-01",
            "end_date": "2026-10-15",
            "date_basis": "COLLECTED_AT",
            "detail_level": "STANDARD",
            "benchmark_source_ids": [
                "b0ef2dac-661b-44f4-8c78-c631f7c6a91f",
                "94bab2e9-814e-448e-a9c2-de95fce32859",
                "9c048eb7-67eb-400d-ab62-5286aa7f1abd",
            ],
        },
    },
    {
        "case_id": "brief_oct_window",
        "filters": {
            "start_date": "2026-10-01",
            "end_date": "2026-10-15",
            "date_basis": "COLLECTED_AT",
            "detail_level": "STANDARD",
        },
    },
    {
        "case_id": "brief_knowledge",
        "filters": {
            "start_date": "2026-09-01",
            "end_date": "2026-10-15",
            "date_basis": "COLLECTED_AT",
            "detail_level": "STANDARD",
            "category_slugs": ["knowledge"],
        },
    },
]
