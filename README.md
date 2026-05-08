# ⚖️ 法律智能问答助手（RAG + 混合召回 + 记忆压缩）

本项目是一个专门针对法律问答场景设计的 **端到端 RAG (检索增强生成) 系统**。它不仅实现了基础的文档检索，还针对法律文本的特殊结构（编、章、节、条）进行了深度优化，确保法律建议的专业性与准确性。

当前架构：**FastAPI 后端 + Vue 3 (Vite) 前端 + 混合检索 (Vector & BM25) + BGE-Reranker 精排 + MinerU 引擎**。

---

## 项目能力

- 文档入库：支持上传 PDF / 文本，进行法律文本预处理、分条分块、向量化并持久化到 Chroma。
- 混合召回：向量检索 + BM25 并行召回，通过 RRF 融合后由 BGE-Reranker 进行精排，返回高相关证据片段。
- 生成回答：使用 DeepSeek 模型按刑法场景优化的提示词输出结构化 Markdown 回复。
- 会话管理：会话列表、新建、置顶、删除、持久化历史记录。
- 记忆压缩：滑动窗口 + 摘要压缩 + Token 预算裁剪，兼顾长对话与上下文成本。
- 可观测性：结构化日志记录检索与压缩过程，便于排查问题。

当前默认模型（可在 `backend/core/config.py` 中修改）：

- 主回答模型：`deepseek-v4-flash`
- 轻量摘要模型：`deepseek-v4-pro`
- 向量模型：`nomic-embed-text:latest`（通过 Ollama）
- 精排模型：`BAAI/bge-reranker-v2-m3`（本地 CPU 推理）

## 核心特性

### 1. 针对性法律数据处理
*   **智能法律切块 (Legal Chunker)**：不同于常规的字符数切块，系统能自动识别法律条文结构，确保一个“条”及其关联释义在同一个检索块内，避免法律语境断裂。
*   **结构化元数据**：自动提取文档中的“编-章-节-条”信息并存入向量库元数据，检索结果可精确追溯至具体法条。
*   **MinerU 深度解析**：集成 MinerU 引擎，针对复杂布局的法律 PDF 文件进行 Markdown 级的高精度还原，保留表格与列表结构。

### 2. 混合召回与重排序
*   **多路并发检索**：结合 **Chroma 向量检索**（语义匹配）与 **BM25 算法**（关键词精确匹配）。
*   **RRF 融合算法**：采用倒数排名融合 (Reciprocal Rank Fusion) 对多路结果进行初步筛选。
*   **BGE 精排模型**：集成 `bge-reranker-v2-m3`。在融合结果中提取前 15 个候选，进行二次深度评分，有效过滤噪音，确保最终透传给 LLM 的 5 个片段是最具说服力的法条。

### 3. 专业法律 Prompt 驱动
*   **角色增强**：内置深度优化的法学专家 Prompt。
*   **结构化输出**：强制模型按“初步判定、深度分析、风险预警、免责声明”的标准化法律意见书格式回复。

### 4. 极致的前端交互
*   **实时解析进度**：上传文档时，通过后端长轮询机制，实时展示文档解析、法律切块、向量入库的百分比进度。
*   **流式响应**：基于 SSE (Server-Sent Events) 的打字机式回复，并支持完美的 Markdown 渲染。

---

## 项目结构

```text
law_rag/
├── backend/
│   ├── main.py                 # FastAPI / uvicorn 启动入口
│   ├── app/
│   │   └── api.py              # FastAPI 路由（上传 / 聊天 / 会话管理）
│   ├── core/
│   │   ├── config.py           # 全局配置（检索 / 模型 / 记忆压缩）
│   │   └── logger.py           # 日志配置（loguru）
│   ├── generation/
│   │   └── rag_service.py      # RAG 主链路
│   ├── infra/
│   │   └── vector_store.py     # 向量库封装（Chroma）
│   ├── ingestion/
│   │   ├── pdf_parser.py       # PDF -> Markdown 解析（含 MinerU）
│   │   └── ingest_service.py   # 入库服务
│   ├── retrieval/
│   │   ├── hybrid_retriever.py # 向量 + BM25 + RRF
│   │   └── reranker.py         # BGE Reranker 封装（支持 CPU）
│   ├── memory/
│   │   └── history_store.py    # 会话持久化与记忆压缩策略
│   ├── chroma_db/              # 运行后生成：向量库
│   ├── chat_history/           # 运行后生成：会话历史
│   └── requirements.txt
├── frontend/
│   ├── src/App.vue             # Vue 3 单页应用（聊天 + 上传 UI）
│   └── ...                     # 其余前端代码
└── README.md
```

## 环境准备

建议 Python 3.10 或 3.11，以下命令在 `backend` 目录执行。

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3.1 必需环境变量

在 `backend` 目录创建 `.env`：

```env
# DeepSeek（OpenAI 兼容接口）
DEEPSEEK_API_KEY=sk-你的真实密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1

# 可选：关闭匿名遥测
ANONYMIZED_TELEMETRY=False
```

如果你使用其他 OpenAI 兼容服务，只需保证：

- `DEEPSEEK_BASE_URL` 指向兼容的 base_url；
- `backend/core/config.py` 中的 `chat_model_name` / `light_model_name` 与实际模型一致。

### 3.2 启动后端服务

在 `backend` 目录：

```powershell
.\.venv\Scripts\Activate.ps1
python main.py
```

默认会启动在 `http://0.0.0.0:8000`，核心接口前缀为 `/api`。

## 4. 向量模型（Ollama）准备

后端默认使用本地 Ollama 提供的 `nomic-embed-text:latest` 向量模型（`http://127.0.0.1:11434`），请提前安装并拉取模型，例如：

```powershell
ollama pull nomic-embed-text
```

如需改用其他 embedding 服务，可在 `backend/core/config.py` 中调整。

## 5. 前端环境与启动（Vue 3）

在 `frontend` 目录（假设已安装 Node.js 18+）：

```powershell
cd frontend
npm install
npm run dev
```

开发环境下，默认访问地址类似：

- 前端：`http://localhost:5173`
- 后端 API：`http://localhost:8000/api`

前端中 `API_BASE` 配置见：`frontend/src/App.vue`。

## 6. 关键配置说明

配置文件：`backend/core/config.py`

### 6.1 检索相关

- `hybrid_vector_k`: 向量召回候选数
- `hybrid_bm25_k`: BM25 召回候选数
- `hybrid_final_k`: 融合后最终证据数
- `hybrid_rrf_k`: RRF 融合参数

### 6.2 精排相关 (Rerank)

- `rerank_enabled`: 是否开启精排
- `rerank_model_name`: 模型名称或本地路径
- `rerank_top_k`: 精排后最终保留的证据数
- `rerank_device`: 运行设备（默认 `cpu`，对小显存友好）

#### 💡 模型离线部署 (推荐)
为了在弱网或无网环境下运行，建议将模型下载到本地 `backend/models` 目录：

1. **国内用户推荐 (ModelScope)**:
   ```powershell
   pip install modelscope
   python -c "from modelscope import snapshot_download; snapshot_download('BAAI/bge-reranker-v2-m3', local_dir='backend/models/bge-reranker-v2-m3')"
   python -c "from modelscope import snapshot_download; snapshot_download('opendatalab/PDF-Extract-Kit-1.0/models', local_dir='backend/models/')"
   ```
2. **配置文件修改**:
   在 `backend/core/config.py` 中，将 `rerank_model_name` 指向该本地路径即可。

### 6.3 记忆压缩相关

- `memory_keep_recent_rounds`: 保留最近轮次（当前 3）
- `memory_summary_trigger_rounds`: 摘要触发轮次（当前 5）
- `memory_history_max_tokens`: 历史 token 预算（当前 4000）
- `memory_summary_max_chars`: 摘要最大字符（当前 1500）
- `memory_summary_enabled`: 是否启用摘要
- `memory_summary_tag`: 内部摘要标识
- `memory_compression_debug`: 是否打印压缩日志（当前开启）

### 6.4 MinerU 配置 (PDF 高精度解析)
项目通过 `backend/ingestion/pdf_parser.py` 深度集成了 MinerU，用于将 PDF 转换为高质量的 Markdown。
- **配置文件**：`backend/mineru.json`
  - `models-dir`: 定义了模型权重的加载路径。
  - `llm-aided-config`: 配置是否开启 LLM 辅助识别（如公式、表格纠错），默认建议关闭以提升本地解析速度。
- **环境变量控制**：
  - `MINERU_TOOLS_CONFIG_JSON`: 启动时自动指向项目内的 `mineru.json`，实现配置隔离。
  - `MINERU_MODEL_SOURCE`: 默认为 `local`，强制从本地路径加载权重，避免联网下载。
- **进度拦截逻辑**：
  - 系统通过“猴子补丁”拦截了 MinerU 内部的 `tqdm` 进度条和批次处理函数，将底层解析页码实时映射为前端看到的 10%-50% 进度条。

## 7. 记忆压缩策略（当前实现）

在 `backend/memory/history_store.py` 中执行：

1.  **消息分类**：自动识别持久化文件中的内部摘要消息（System）与普通用户/助手消息。
2.  **轮次切分**：以“用户发言”为边界将普通消息组合为完整的会话轮次（Round）。
3.  **滑动窗口**：永远保留最近 $N$ 轮（由 `memory_keep_recent_rounds` 定义）的原始对话，确保短期记忆的精准性。
4.  **增量摘要**：当总轮次超过阈值时，将超出窗口的旧轮次发送给**轻量推理模型**（`light_model_name`）进行要点提炼，并与旧摘要合并。
5.  **重建上下文**：将“最新摘要消息”与“最近 $N$ 轮原始消息”重新组合。
6.  **Token 预算裁剪**：若重建后的总长度仍超过 `memory_history_max_tokens`，则从最近窗口中按时间顺序由旧到新删除，直到满足预算，保底留 1 轮。
> **提示**：生成的内部摘要带有特殊 Tag。该 Tag 对 LLM 可见以提供背景，但在前端接口返回消息列表时会被自动过滤，确保用户界面简洁，不展示内部处理逻辑。

## 8. 免责声明

本项目输出仅用于学习与技术验证，不构成正式法律意见。涉及真实法律事务请咨询持证律师。
