import hashlib
import os

from langchain_chroma import Chroma
# from langchain_community.embeddings import DashScopeEmbeddings
from langchain_ollama import OllamaEmbeddings

from core import config
from core.logger import logger
from ingestion.legal_chunker import build_chunks_from_article_units, parse_legal_article_units
from ingestion.legal_preprocess import preprocess_legal_text


def add_texts_in_batches(chroma, texts, metadatas, batch_size: int = 10, progress_callback=None):
	"""按 DashScope/Ollama 允许的上限分批写入 Chroma。"""
	if len(texts) != len(metadatas):
		raise ValueError("texts 和 metadatas 数量必须一致")

	total = len(texts)
	logger.info(f"Adding {total} chunks to Chroma in batches of {batch_size}")
	for start in range(0, total, batch_size):
		end = min(start + batch_size, total)
		logger.debug(f"Adding batch {start} to {end}")
		if progress_callback:
			# 进度从 60% 到 99%
			percent = 60 + int((start / total) * 39)
			progress_callback(percent, f"正在向量化入库 ({start}/{total} 块)...")
			
		chroma.add_texts(
			texts[start:end],
			metadatas=metadatas[start:end],
		)
	logger.info("Batch ingestion complete")


def check_md5(md5_str: str):
	if not os.path.exists(config.md5_path):
		with open(config.md5_path, "w", encoding="utf-8") as f:
			pass
		return False

	with open(config.md5_path, "r", encoding="utf-8") as f:
		for line in f:
			if line.strip() == md5_str:
				return True
	return False


def save_md5(md5_str: str):
	with open(config.md5_path, "a", encoding="utf-8") as f:
		f.write(md5_str + "\n")


def get_string_md5(input_str: str, encoding="utf-8"):
	str_bytes = input_str.encode(encoding=encoding)
	md5_obj = hashlib.md5()
	md5_obj.update(str_bytes)
	return md5_obj.hexdigest()


class KnowledgeBaseService:
	"""知识库入库服务。"""

	def __init__(self):
		os.makedirs(config.persist_directory, exist_ok=True)

		self.chroma = Chroma(
			collection_name=config.collection_name,
			# embedding_function=DashScopeEmbeddings(model=config.embedding_model_name),
			embedding_function=OllamaEmbeddings(model=config.embedding_model_name, base_url="http://127.0.0.1:11434"),
			persist_directory=config.persist_directory,
		)
		self.chunk_size = config.chunk_size
		self.chunk_overlap_articles = config.chunk_overlap_articles

	def get_all_sources(self) -> list[str]:
		"""获取当前知识库中所有文档的来源（文件名）"""
		try:
			data = self.chroma._collection.get(include=["metadatas"])
			sources = set()
			for meta in data.get("metadatas", []):
				if meta and "source" in meta and meta["source"]:
					sources.add(meta["source"])
			return sorted(list(sources))
		except Exception:
			return []

	def delete_source(self, source: str) -> int:
		"""删除知识库中指定来源（文件名）的所有文档块。

		参数:
			source (str): 要删除的文档来源（文件名）

		返回:
			int: 被删除的文档块数量
		"""
		try:
			# 查找所有匹配 source 的文档 ID
			data = self.chroma._collection.get(
				where={"source": source},
				include=["metadatas"],
			)
			ids_to_delete = data.get("ids", [])
			if not ids_to_delete:
				logger.warning(f"未找到来源为 '{source}' 的文档块")
				return 0

			self.chroma._collection.delete(ids=ids_to_delete)
			logger.info(f"已删除来源为 '{source}' 的 {len(ids_to_delete)} 个文档块")
			return len(ids_to_delete)
		except Exception as e:
			logger.exception(f"删除文档 '{source}' 时出错")
			raise

	def upload_by_str(self, data: str, filename: str, progress_callback=None):
		if progress_callback:
			progress_callback(50, "文本提取完成，正在清洗数据...")
			
		data = preprocess_legal_text(data)

		logger.info(f"Checking if file {filename} exists in knowledge base...")
		if filename in self.get_all_sources():
			logger.warning(f"File {filename} already exists in Chroma. Skipping.")
			if progress_callback:
				progress_callback(100, "文件已存在，跳过入库")
			return "[Repeat] 内容已存在知识库"

		if progress_callback:
			progress_callback(55, "正在进行智能法律切块...")
			
		logger.info(f"Parsing article units for {filename}...")
		article_units = parse_legal_article_units(data)
		logger.info(f"Building chunks from {len(article_units)} article units...")
		knowledge_chunks, metadata_list = build_chunks_from_article_units(
			article_units=article_units,
			max_chars=self.chunk_size,
			overlap_articles=self.chunk_overlap_articles,
		)

		# 强制安全限制：如果某一条法条及其释义过长（比如好几万字），会撑爆 embedding 模型
		# 我们需要对超长的 chunk 进行二次切分
		final_chunks = []
		final_metadatas = []
		if knowledge_chunks:
			from langchain_text_splitters import RecursiveCharacterTextSplitter
			text_splitter = RecursiveCharacterTextSplitter(
				chunk_size=self.chunk_size,
				chunk_overlap=150,
				length_function=len,
			)
			for chunk, meta in zip(knowledge_chunks, metadata_list):
				if len(chunk) > self.chunk_size * 2:
					sub_chunks = text_splitter.split_text(chunk)
					for sc in sub_chunks:
						final_chunks.append(sc)
						final_metadatas.append(meta.copy())
				else:
					final_chunks.append(chunk)
					final_metadatas.append(meta)
			
			knowledge_chunks = final_chunks
			metadata_list = final_metadatas

		if not knowledge_chunks:
			logger.warning(f"No valid legal chunks generated for {filename}. Falling back to generic text splitter.")
			from langchain_text_splitters import RecursiveCharacterTextSplitter
			from datetime import datetime
			
			text_splitter = RecursiveCharacterTextSplitter(
				chunk_size=self.chunk_size,
				chunk_overlap=200,
				length_function=len,
			)
			knowledge_chunks = text_splitter.split_text(data)
			if not knowledge_chunks:
				logger.warning(f"Failed to generate generic chunks for {filename}.")
				return "[Warn] 未解析到可入库的内容"
			
			now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
			metadata_list = [
				{
					"source": filename,
					"create_time": now,
					"operator": "",
					"part": "",
					"chapter": "",
					"section": "",
					"article_no": "",
					"article_end": "",
					"chunk_article_end": "",
				}
				for _ in knowledge_chunks
			]

		logger.info(f"Generated {len(knowledge_chunks)} chunks for {filename}. Attaching metadata...")
		for metadata in metadata_list:
			metadata["source"] = filename

		if progress_callback:
			progress_callback(60, "开始向量化入库...")
			
		add_texts_in_batches(
			self.chroma,
			knowledge_chunks,
			metadata_list,
			batch_size=10,
			progress_callback=progress_callback
		)
		
		if progress_callback:
			progress_callback(100, "入库完成")
			
		logger.success(f"Successfully ingested {filename} ({len(knowledge_chunks)} chunks).")
		return "[Success]内容已经成功载入向量库"


__all__ = [
	"KnowledgeBaseService",
	"add_texts_in_batches",
	"check_md5",
	"save_md5",
	"get_string_md5",
]
