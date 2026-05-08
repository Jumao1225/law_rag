from typing import List
from langchain_core.documents import Document
from FlagEmbedding import FlagReranker
from core.logger import logger
from core import config

class RerankerService:
    def __init__(
        self, 
        model_name: str = config.rerank_model_name, 
        use_fp16: bool = True,
        device: str = config.rerank_device
    ):
        """初始化 Reranker。
        
        Args:
            model_name: 模型名称或路径
            use_fp16: 是否使用半精度推理
            device: 运行设备 ('cpu', 'cuda', 'mps')
        """
        self.enabled = config.rerank_enabled
        if not self.enabled:
            self.reranker = None
            logger.info("Reranker is disabled in config")
            return

        logger.info(f"Loading Reranker model: {model_name} on {device}...")
        try:
            self.reranker = FlagReranker(model_name, use_fp16=use_fp16, device=device)
            logger.info("Reranker model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load Reranker model: {e}")
            self.reranker = None
            self.enabled = False

    def rerank(self, query: str, documents: List[Document], top_k: int = config.rerank_top_k) -> List[Document]:
        """对文档进行精排。
        
        Args:
            query: 查询语句
            documents: 候选文档列表
            top_k: 返回的前 K 个文档
        """
        if not self.enabled or not self.reranker or not documents:
            return documents[:top_k]

        logger.info(f"Reranking {len(documents)} documents for query: {query[:50]}...")
        
        # 准备推理输入：[[query, doc1], [query, doc2], ...]
        pairs = [[query, doc.page_content] for doc in documents]
        
        # 计算得分
        try:
            scores = self.reranker.compute_score(pairs)
            
            # 将得分与文档关联
            doc_scores = list(zip(documents, scores))
            
            # 按得分从高到低排序
            doc_scores.sort(key=lambda x: x[1], reverse=True)
            
            # 记录得分最高的几个，方便调试
            for i, (doc, score) in enumerate(doc_scores[:3]):
                logger.debug(f"Top {i+1} rerank score: {score:.4f}")
                
            return [ds[0] for ds in doc_scores[:top_k]]
            
        except Exception as e:
            logger.error(f"Error during reranking: {e}")
            return documents[:top_k]
