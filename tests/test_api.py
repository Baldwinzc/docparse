from __future__ import annotations

import io

import pytest

pytest.importorskip("openpyxl")

from fastapi.testclient import TestClient

from docparse.adapters.files.factory import _file_store
from docparse.adapters.files.memory import MemoryFileStore
from docparse.adapters.jobs.factory import _job_store
from docparse.adapters.jobs.memory import MemoryJobStore
from docparse.api.app import create_app
from docparse.api.routes import get_pipeline
from docparse.config import Settings
from docparse.pipeline.runner import Pipeline
from xlsx_fixtures import _coded_draft, _draft, _net_only_packing, _workbook


def _client() -> TestClient:
    settings = Settings(job_store="memory", file_store="memory", llm_api_key="")
    pipeline = Pipeline(settings=settings, jobs=MemoryJobStore(), files=MemoryFileStore())
    app = create_app()
    app.dependency_overrides[get_pipeline] = lambda: pipeline
    return TestClient(app)


def _xlsx(builders: dict, filename: str) -> tuple[str, io.BytesIO, str]:
    return filename, io.BytesIO(_workbook(builders)), (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def test_health() -> None:
    response = _client().get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers.get("X-Request-Id")


def test_upload_hengxin_fixture_returns_declaration() -> None:
    client = _client()
    response = client.post(
        "/v1/jobs",
        files={"file": _xlsx({"一般贸易出口": _draft}, "hengxin.xlsx")},
        data={
            "agentCode": "4403180867",
            "agentName": "深圳市泰洲物流有限公司",
            "ignoredExtra": "should-be-ignored",
        },
        headers={"X-Request-Id": "req-21"},
    )
    assert response.status_code == 200
    assert response.headers.get("X-Request-Id") == "req-21"
    body = response.json()
    assert body["request_id"] == "req-21"
    declaration = body["result"]["declaration"]
    assert declaration["contrNo"] == "HDX2026-251"
    assert declaration["grossWt"] == "296.46"
    assert declaration["tdecGoodsitemsVoArr"]
    assert declaration["tdecGoodsitemsVoArr"][0]["gname"] == "表壳配件/壳体"
    assert declaration["agentCode"] == "4403180867"
    assert declaration["agentName"] == "深圳市泰洲物流有限公司"
    assert declaration["_meta"]["has_draft"] is True
    assert "ignoredExtra" not in body["caller"]


def test_missing_gross_is_needs_review_not_500() -> None:
    response = _client().post(
        "/v1/jobs",
        files={"file": _xlsx({"总箱单": _net_only_packing}, "net-only.xlsx")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_review"
    declaration = body["result"]["declaration"]
    assert declaration["grossWt"] == ""
    assert declaration["netWt"] == "2825.47"
    assert declaration["agentCode"] == "4403180867"
    assert declaration["agentName"] == "深圳市泰洲物流有限公司"
    assert declaration["agentScc"] == "914403000539716870"
    assert declaration["agentCiqCode"] == "4700910159"
    paths = {item["path"]: item for item in body["result"]["reviews"]}
    assert "grossWt" in paths
    assert "net_is_not_gross" in paths["grossWt"]["reasons"]


def test_explicit_empty_agent_skips_yaml_default() -> None:
    response = _client().post(
        "/v1/jobs",
        files={"file": _xlsx({"一般贸易出口": _draft}, "hengxin.xlsx")},
        data={"agentCode": "", "agentName": "", "agentScc": "", "agentCiqCode": ""},
    )
    assert response.status_code == 200
    declaration = response.json()["result"]["declaration"]
    assert declaration["agentCode"] == ""
    assert declaration["agentName"] == ""


def test_default_pipeline_upload_does_not_500() -> None:
    """Swagger / uvicorn 走 get_pipeline()，不能把 Settings 丢进 lru_cache。"""
    get_pipeline.cache_clear()
    _job_store.cache_clear()
    _file_store.cache_clear()
    app = create_app()
    response = TestClient(app).post(
        "/v1/jobs",
        files={"file": _xlsx({"一般贸易出口": _draft}, "hengxin.xlsx")},
        data={"agentCode": "4403180867"},
    )
    assert response.status_code == 200
    assert response.json()["result"]["declaration"]["contrNo"] == "HDX2026-251"
    get_pipeline.cache_clear()


def test_missing_file_is_400() -> None:
    response = _client().post("/v1/jobs", data={"agentCode": "4403180867"})
    assert response.status_code == 400


def test_declare_coded_draft_returns_dec_results() -> None:
    response = _client().post(
        "/v1/declare",
        files={"file": _xlsx({"一般贸易出口": _coded_draft}, "coded.xlsx")},
        data={"agentCode": "4403180867", "agentName": "深圳市泰洲物流有限公司"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["result"] is True
    assert body["msg"] == "操作成功"
    dec = body["dec_results"]
    assert dec["contrNo"] == "HDX2026-251"
    assert dec["grossWt"] == "296.46"
    assert dec["supvModeCdde"] == "0110"
    assert dec["cusTrafMode"] == "4"
    assert dec["transMode"] == "3"
    assert dec["wrapType"] == "99"
    assert dec["packName"] == "99"
    assert dec["packType"] == "99"
    assert dec["iePort"] == "5304"
    assert dec["dataSource"] == "7"
    assert dec["promiseItem1"] == "0"
    assert "_meta" not in dec
    goods = dec["tdecGoodsitemsVoArr"]
    assert goods
    assert goods[0]["gname"] == "表壳配件/壳体"
    assert goods[0]["gunit"] == "008"
    assert goods[0]["cusOriginCountry"] == "CHN"
    assert goods[0]["destinationCountry"] == "HKG"
    assert goods[0]["districtCode"] == "44139"
    assert "_source" not in goods[0]
    assert goods[0]["id"]
    assert "一般贸易" not in str(dec)


def test_declare_unknown_code_does_not_submit() -> None:
    response = _client().post(
        "/v1/declare",
        files={"file": _xlsx({"一般贸易出口": _draft}, "hengxin.xlsx")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["code"] != 0
    assert body["result"] is False
    assert body["dec_results"] is None


def test_declare_missing_gross_does_not_submit() -> None:
    response = _client().post(
        "/v1/declare",
        files={"file": _xlsx({"总箱单": _net_only_packing}, "net-only.xlsx")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["code"] != 0
    assert body["result"] is False
    assert body["dec_results"] is None


def test_jobs_still_returns_meta_when_declare_holds() -> None:
    response = _client().post(
        "/v1/jobs",
        files={"file": _xlsx({"一般贸易出口": _draft}, "hengxin.xlsx")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_review"
    assert body["result"]["declaration"]["_meta"]
    assert body["result"]["declaration"]["supvModeCdde"] == "一般贸易"
    assert body["result"]["reviews"]


def test_declare_missing_file_is_400() -> None:
    response = _client().post("/v1/declare", data={"agentCode": "4403180867"})
    assert response.status_code == 400


def test_openapi_shows_caller_and_goods_array() -> None:
    spec = _client().get("/openapi.json").json()
    text = str(spec)
    assert "agentCode" in text
    assert "4403180867" in text
    assert "tdecGoodsitemsVoArr" in text
    assert "/v1/jobs" in spec["paths"]
    assert "/v1/declare" in spec["paths"]
    assert "/health" in spec["paths"]


def test_schema_catalog_follows_yaml() -> None:
    body = _client().get("/v1/schema").json()
    names = {item["name"] for item in body["head"]}
    assert "contrNo" in names
    assert "grossWt" in names
    assert body["goods_array"] == "tdecGoodsitemsVoArr"
    caller = {item["name"]: item for item in body["caller"]}
    assert caller["agentCode"]["default"] == "4403180867"
    assert caller["agentName"]["display_name"]
    goods = {item["name"] for item in body["goods"]}
    assert "gname" in goods
    assert "package" not in body


def test_review_page_has_no_ir_and_no_hardcoded_field_list() -> None:
    page = _client().get("/review")
    root = _client().get("/")
    assert page.status_code == 200
    assert root.status_code == 200
    html = page.text
    assert "报关单对眼" in html
    assert "/v1/schema" in html
    assert "/v1/jobs" in html
    assert "_meta.codes" in html
    assert "package.documents" not in html
    assert "contrNo" not in html
    assert "境内发货人" not in html
