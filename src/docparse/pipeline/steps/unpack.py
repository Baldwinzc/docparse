from docparse.adapters.parsers.detect import SourceKind, detect_kind
from docparse.adapters.parsers.unpack import unpack_zip
from docparse.pipeline.context import PipelineContext


def unpack_step(ctx: PipelineContext) -> None:
    data = ctx.files.get(ctx.raw.id)
    kind = detect_kind(ctx.raw.filename, data)
    if kind != SourceKind.ZIP:
        ctx.members = [ctx.raw]
        return
    members = unpack_zip(data, ctx.settings)
    unpacked = []
    for member in members:
        ref = ctx.files.put(
            member.data,
            job_id=ctx.job.id,
            filename=member.archive_path.split("/")[-1],
            kind="derived",
            parent_id=ctx.raw.id,
            archive_path=member.archive_path,
        )
        unpacked.append(ref)
    ctx.members = unpacked or [ctx.raw]
