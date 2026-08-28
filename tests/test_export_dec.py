from __future__ import annotations

from docparse.api.export_dec import public_declaration, to_dec_envelope
from docparse.domain.models import FieldReview, Job, JobStatus, ParseJobResult
from docparse.schema.loader import load_schema


def _job(
    *,
    status: JobStatus,
    declaration: dict | None,
    reviews: list[FieldReview] | None = None,
) -> Job:
    return Job(
        source_filename="x.xlsx",
        status=status,
        result=ParseJobResult(
            status=status,
            declaration=declaration,
            reviews=reviews or [],
        ),
    )


def test_public_declaration_strips_meta_and_writes_codes() -> None:
    schema = load_schema()
    source = {
        "contrNo": "HDX2026-251",
        "supvModeCdde": "一般贸易",
        "wrapType": "其他包装",
        "tdecGoodsitemsVoArr": [
            {
                "gname": "表壳配件/壳体",
                "gunit": "只",
                "_source": {"role": "draft", "sheet": "一般贸易出口"},
            }
        ],
        "_meta": {
            "codes": {
                "supvModeCdde": "0110",
                "wrapType": "99",
                "tdecGoodsitemsVoArr[0].gunit": "008",
            }
        },
    }
    payload = public_declaration(source, schema)
    assert payload["supvModeCdde"] == "0110"
    assert payload["wrapType"] == "99"
    assert payload["packName"] == "99"
    assert payload["packType"] == "99"
    assert payload["dataSource"] == "7"
    assert payload["promiseItem1"] == "0"
    assert "_meta" not in payload
    assert "_source" not in payload["tdecGoodsitemsVoArr"][0]
    assert payload["tdecGoodsitemsVoArr"][0]["gunit"] == "008"
    assert payload["tdecGoodsitemsVoArr"][0]["id"]
    assert source["_meta"]["codes"]["supvModeCdde"] == "0110"
    assert "_source" in source["tdecGoodsitemsVoArr"][0]


def test_needs_review_still_submits() -> None:
    job = _job(
        status=JobStatus.NEEDS_REVIEW,
        declaration={
            "contrNo": "A",
            "iePort": "莲塘口岸",
            "tdecGoodsitemsVoArr": [{"gname": "x", "gmodel": "原文"}],
            "_meta": {"codes": {}},
        },
        reviews=[
            FieldReview(
                path="iePort",
                status="needs_review",
                reasons=["unknown_code:海关口岸代码"],
            ),
            FieldReview(
                path="tdecGoodsitemsVoArr[0].gmodel",
                status="needs_review",
                reasons=["gmodel_raw"],
            ),
        ],
    )
    body = to_dec_envelope(job)
    assert body["code"] == 0
    assert body["result"] is True
    assert body["dec_results"]["contrNo"] == "A"
    assert body["dec_results"]["iePort"] == "莲塘口岸"
    assert "_meta" not in body["dec_results"]


def test_failed_job_does_not_submit() -> None:
    job = Job(source_filename="x.xlsx", status=JobStatus.FAILED, error="boom")
    job.result = ParseJobResult(status=JobStatus.FAILED, error="boom")
    body = to_dec_envelope(job)
    assert body["code"] == 2
    assert body["result"] is False
    assert body["dec_results"] is None
    assert "boom" in body["msg"]
