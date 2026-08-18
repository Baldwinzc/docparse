from docparse.pipeline.context import PipelineContext


def ingest_step(ctx: PipelineContext) -> None:
    if ctx.raw.byte_size <= 0:
        raise ValueError("空文件")
