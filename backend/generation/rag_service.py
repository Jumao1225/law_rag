from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
from langchain_core.runnables.history import RunnableWithMessageHistory
# from langchain_community.chat_models.tongyi import ChatTongyi
# from langchain_openai import ChatOpenAI
# from langchain_community.embeddings import DashScopeEmbeddings
from langchain_ollama import OllamaEmbeddings, ChatOllama
from langchain.chat_models import init_chat_model
import os

from core import config
from core.logger import logger
from infra.vector_store import VectorStoreService
from memory.history_store import get_history
from retrieval.hybrid_retriever import HybridRetrieverService
from retrieval.reranker import RerankerService


def _print_prompt(prompt):
    print("=" * 20)
    print(prompt.to_string())
    print("=" * 20)
    return prompt


class RagService:
    def __init__(self):
        self.vector_service = VectorStoreService(
            # embedding=DashScopeEmbeddings(model=config.embedding_model_name)
            embedding=OllamaEmbeddings(model=config.embedding_model_name, base_url="http://127.0.0.1:11434")
        )
        self.reranker = RerankerService()
        self.prompt_template = ChatPromptTemplate.from_messages(
            [
                (
                   "system",
                    "你是一位拥有深厚法学功底的**全能法律助手**，精通《刑法》、《民法典》及相关司法解释。"
                    "你的任务是根据检索到的参考资料（context），为用户提供专业、客观的法律建议。"

                    "【核心原则】"
                    "1. **精准归类**：根据用户问题和检索到的法律依据，明确判断案件性质。若是民事纠纷（如合同、侵权、婚姻、继承等），适用《民法典》；若是刑事犯罪，适用《刑法》。"
                    "2. **重点突出**：在回复中，使用**加粗**标注关键法律术语、罪名、请求权基础、量刑或民事责任承担方式。"
                    "3. **证据闭环**：所有分析必须严格挂载证据库中的法条编号。格式示例：刑事依据《刑法》第XX条，民事依据《民法典》第XX条。严禁凭空捏造条文。"
                    "4. **民刑交叉处理**：若案件同时涉及民事赔偿与刑事责任（如交通肇事、故意伤害等），应分别论述。"

                    "【输出结构要求】"
                    "---"
                    "### ⚖️ 初步判定"
                    "（结论先行。明确案件性质：**刑事犯罪**、**民事纠纷**或**民刑交叉**。给出定性判断。）"

                    "### 🔍 深度法律分析"
                    "（结合案情与法条进行论证：）"
                    " - **如果是刑事分析**：明确罪名构成要件及法条依据。"
                    " - **如果是民事分析**：明确违约或侵权责任、法律后果及请求权基础。"

                    "### ⚠️ 风险预警与待核实点"
                    "（列出影响判定的变量。刑事关注：**主观故意、自首立功、犯罪金额**；民事关注：**证据留存、诉讼时效、合同条款、违约责任**等。）"

                    "### 📜 免责声明"
                    "（本回复仅供学习参考，不构成正式法律意见。法律事务复杂，请务必咨询专业律师。）"

                    "【语气与格式控制】"
                    "- 严禁幻觉，若检索到的参考资料不足以覆盖问题，请诚实告知并给出通识性方向。"
                    "- 参考资料如下：{context}。\\n对话历史记录：",
                ),
                MessagesPlaceholder("history"),
                (
                    "user",
                    "请回答用户提问：{input}。"
                    "如果问题涉及个案定性或量刑，请强调需由司法机关和律师结合具体事实判断。",
                ),
            ]
        )
        self.hybrid_retriever = HybridRetrieverService(
            get_vector_docs=self.vector_service.get_vector_docs,
            get_all_docs=self.vector_service.get_all_documents,
            get_docs_count=self.vector_service.get_count,
            vector_k=config.hybrid_vector_k,
            bm25_k=config.hybrid_bm25_k,
            final_k=config.hybrid_final_k,
            rrf_k=config.hybrid_rrf_k,
            reranker=self.reranker,
        )
        self.chat_model = _build_chat_model()
        self.chain = self._build_chain()

    def _build_chain(self):
        def format_document(docs: list[Document]):
            if not docs:
                return "无相关参考资料"
            evidence_lines = []
            for i, doc in enumerate(docs, start=1):
                meta = doc.metadata or {}
                source = meta.get("source", "")
                chapter = meta.get("chapter", "")
                article = meta.get("article_no", "")
                evidence_lines.append(
                    f"source={source} chapter={chapter} article={article}\\n"
                    f"原文片段：{doc.page_content}"
                )
            return "\\n\\n".join(evidence_lines)

        def format_for_retriever(value: dict) -> str:
            return value["input"]

        def hybrid_retrieve(query: str) -> list[Document]:
            logger.info(f"Retrieving chunks for query: '{query}'")
            results = self.hybrid_retriever.retrieve(query)
            logger.info(f"Retrieved {len(results)} chunks")
            return results

        def format_for_prompt_template(value: dict):
            return {
                "input": value["input"]["input"],
                "context": value["context"],
                "history": value["input"]["history"],
            }

        chain = (
            {
                "input": RunnablePassthrough(),
                "context": RunnableLambda(format_for_retriever)
                | RunnableLambda(hybrid_retrieve)
                | format_document,
            }
            | RunnableLambda(format_for_prompt_template)
            | self.prompt_template
            | _print_prompt
            | self.chat_model
            | StrOutputParser()
        )

        return RunnableWithMessageHistory(
            chain,
            get_history,
            input_messages_key="input",
            history_messages_key="history",
        )


def _build_chat_model():
    
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    try:
        return init_chat_model(
            model=config.chat_model_name,
            # model_provider="tongyi",
            model_provider="openai",
            api_key=api_key,
            base_url=base_url
        )
    except Exception:
        # 若本地依赖未完成迁移，回退到社区模型实现，保证可运行。
        # return ChatTongyi(model=config.chat_model_name)
        return ChatOpenAI(model=config.chat_model_name, api_key=api_key, base_url=base_url)
    # """使用本地 Ollama 模型"""
    # return ChatOllama(model=config.chat_model_name, base_url="http://127.0.0.1:11434")
