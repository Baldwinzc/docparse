from docparse.pipeline.context import PipelineContext


def route_review_step(ctx: PipelineContext) -> None:
    # 分流逻辑集中在 runner._status_from_package，这里只去重原因。
    ctx.package.review_reasons = list(dict.fromkeys(ctx.package.review_reasons))
