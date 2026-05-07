from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
import hashlib

from langchain_core.documents import Document
from langchain_community.retrievers import BM25Retriever

from core.logger import logger


def _char_tokenize(text: str) -> list[str]:
    """使用字符级分词，避免额外依赖。"""
    return [c for c in text if not c.isspace()]


def _doc_key(doc: Document) -> str:
    md = doc.metadata or {}
    content_hash = hashlib.md5(doc.page_content[:120].encode('utf-8')).hexdigest()
    return "|".join(
        [
            str(md.get("source", "")),
            str(md.get("chapter", "")),
            str(md.get("article_no", "")),
            str(md.get("chunk_article_end", "")),
            content_hash,
        ]
    )


def rrf_fuse(
    ranked_lists: list[list[Document]],
    top_k: int,
    rrf_k: int = 60,
) -> list[Document]:
    """Reciprocal Rank Fusion。

    score(d) = Σ 1 / (rrf_k + rank_i(d))
    """
    score_map: dict[str, float] = {}
    doc_map: dict[str, Document] = {}

    for docs in ranked_lists:
        for idx, doc in enumerate(docs, start=1):
            key = _doc_key(doc)
            doc_map[key] = doc
            score_map[key] = score_map.get(key, 0.0) + 1.0 / (rrf_k + idx)

    ranked_keys = sorted(score_map.keys(), key=lambda k: score_map[k], reverse=True)
    return [doc_map[k] for k in ranked_keys[:top_k]]


@dataclass
class HybridRetrieverService:
    """混合召回：向量并行 BM25，最终 RRF 融合。"""

    get_vector_docs: Callable[[str, int], list[Document]]
    get_all_docs: Callable[[], list[Document]]
    get_docs_count: Callable[[], int] | None = None
    vector_k: int = 20
    bm25_k: int = 20
    final_k: int = 6
    rrf_k: int = 60

    _bm25_retriever: BM25Retriever | None = None
    _bm25_built_on_count: int = -1

    def _ensure_bm25(self):
        if self.get_docs_count:
            count = self.get_docs_count()
            if count == 0:
                self._bm25_retriever = None
                self._bm25_built_on_count = 0
                return
            if self._bm25_built_on_count == count:
                return
            all_docs = self.get_all_docs()
            count = len(all_docs)
        else:
            all_docs = self.get_all_docs()
            count = len(all_docs)
            if count == 0:
                self._bm25_retriever = None
                self._bm25_built_on_count = 0
                return
            if self._bm25_built_on_count == count:
                return

        logger.info(f"Rebuilding BM25 index with {count} documents")
        retriever = BM25Retriever.from_documents(all_docs, preprocess_func=_char_tokenize)
        retriever.k = self.bm25_k
        self._bm25_retriever = retriever
        self._bm25_built_on_count = count
        logger.info("BM25 index rebuild complete")

    def retrieve(self, query: str) -> list[Document]:
        vector_docs = self.get_vector_docs(query, self.vector_k)
        logger.debug(f"Vector retrieval returned {len(vector_docs)} docs")

        self._ensure_bm25()
        bm25_docs = []
        if self._bm25_retriever is not None:
            bm25_docs = self._bm25_retriever.invoke(query)
        logger.debug(f"BM25 retrieval returned {len(bm25_docs)} docs")

        if not vector_docs and not bm25_docs:
            logger.warning("Both vector and BM25 returned empty results")
            return []

        fused = rrf_fuse([vector_docs, bm25_docs], top_k=self.final_k, rrf_k=self.rrf_k)
        logger.debug(f"RRF fusion produced {len(fused)} final docs")
        return fused
