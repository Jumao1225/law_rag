import os

# 在导入 MinerU 之前设置环境变量，让它读取项目本地的配置和模型
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MINERU_TOOLS_CONFIG_JSON", os.path.join(_PROJECT_ROOT, "mineru.json"))
os.environ.setdefault("MINERU_MODEL_SOURCE", "local")

from core.logger import logger
from mineru.cli.common import do_parse, prepare_env
from mineru.utils.enum_class import MakeMode

# 固定输出目录
OUTPUT_DIR = os.path.join(_PROJECT_ROOT, "output")


def parse_pdf_to_md(pdf_bytes: bytes, filename: str, progress_callback=None) -> str:
    """
    使用 MinerU Python API 将 PDF 转换为 Markdown。

    直接调用 mineru.cli.common.do_parse()，绕过 CLI 和 magic-pdf.json 配置。

    参数:
        pdf_bytes (bytes): PDF 文件的二进制内容
        filename (str): 上传的原始文件名
        progress_callback (callable): 进度回调函数，签名 func(progress: int, status: str)

    返回:
        str: 提取出的 Markdown 文本
    """
    # 去掉扩展名作为文件标识
    pdf_name = os.path.splitext(filename)[0]

    # 确保输出目录存在
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    logger.info(f"开始解析 PDF: {filename}，输出目录: {OUTPUT_DIR}")

    # 狸猫换太子：拦截 MinerU 内部的 tqdm 进度条以获取精确页码进度
    import mineru.backend.pipeline.pipeline_analyze
    original_tqdm = mineru.backend.pipeline.pipeline_analyze.tqdm
    original_batch_image_analyze = mineru.backend.pipeline.pipeline_analyze.batch_image_analyze

    class TqdmInterceptor(original_tqdm):
        def update(self, n=1):
            super().update(n)
            # 添加调试日志看看有没有被调用
            logger.info(f"[TqdmInterceptor] update called! n={self.n}/{getattr(self, 'total', 'unknown')}")
            if progress_callback and hasattr(self, 'total') and self.total:
                # 假设 PDF 解析阶段占用整体进度的 10% 到 50%
                percent = 10 + int((self.n / self.total) * 40)
                progress_callback(percent, f"正在解析 PDF (第 {self.n}/{self.total} 页，每批次由于显存限制可能需要数分钟)...")

    batch_state = {"current": 0}
    def batch_analyze_interceptor(*args, **kwargs):
        batch_state["current"] += 1
        if progress_callback:
            # 每进入一个批次，进度条象征性走一点，并且改变文字状态
            progress_callback(10 + min(batch_state["current"], 20), f"正在执行深度视觉与排版识别 (第 {batch_state['current']} 批次，这需要一些时间，请耐心等待)...")
        return original_batch_image_analyze(*args, **kwargs)

    mineru.backend.pipeline.pipeline_analyze.tqdm = TqdmInterceptor
    mineru.backend.pipeline.pipeline_analyze.batch_image_analyze = batch_analyze_interceptor

    try:
        if progress_callback:
            progress_callback(10, "准备启动底层解析模型...")
            
        do_parse(
            output_dir=OUTPUT_DIR,
            pdf_file_names=[pdf_name],
            pdf_bytes_list=[pdf_bytes],
            p_lang_list=["ch"],
            backend="pipeline",
            parse_method="auto",
            # 只生成 markdown，关闭其他不必要的输出以提升速度
            f_dump_md=True,
            f_dump_middle_json=False,
            f_dump_model_output=False,
            f_dump_orig_pdf=False,
            f_dump_content_list=False,
            f_draw_layout_bbox=False,
            f_draw_span_bbox=False,
            f_make_md_mode=MakeMode.MM_MD,
        )
    except Exception as e:
        logger.exception(f"MinerU 解析 PDF 失败: {filename}")
        raise RuntimeError(f"MinerU 解析失败: {e}")
    finally:
        # 恢复原版的 tqdm 和 batch_image_analyze
        mineru.backend.pipeline.pipeline_analyze.tqdm = original_tqdm
        mineru.backend.pipeline.pipeline_analyze.batch_image_analyze = original_batch_image_analyze

    # 递归查找生成的 .md 文件
    md_files = []
    for root, dirs, files in os.walk(OUTPUT_DIR):
        for file in files:
            if file.lower().endswith(".md"):
                md_files.append(os.path.join(root, file))

    if not md_files:
        raise RuntimeError("MinerU 解析完成但未生成 Markdown 文件。")

    # 选取体积最大的 .md 文件作为主文本
    main_md_file = max(md_files, key=os.path.getsize)
    logger.info(f"PDF 解析成功: {filename} -> {main_md_file}")

    if progress_callback:
        progress_callback(50, "PDF 文本提取完成...")

    with open(main_md_file, "r", encoding="utf-8") as f:
        return f.read()
