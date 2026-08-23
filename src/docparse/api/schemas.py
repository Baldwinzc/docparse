"""OpenAPI 请求体与示例。字段名单来自 YAML，不手写 agent*。"""

from __future__ import annotations

from docparse.api.caller import accepted_caller_keys
from docparse.schema.loader import Schema, load_schema

JOB_EXAMPLE = {
    "id": "ab12cd",
    "status": "needs_review",
    "source_filename": "hengxin.xlsx",
    "result": {
        "status": "needs_review",
        "declaration": {
            "contrNo": "HDX2026-251",
            "grossWt": "296.46",
            "netWt": "218.375",
            "agentCode": "4403180867",
            "agentName": "深圳市泰洲物流有限公司",
            "tdecGoodsitemsVoArr": [
                {"gname": "表壳配件/壳体", "gqty": "150"},
            ],
            "_meta": {
                "has_draft": True,
                "source_roles": ["draft", "packing"],
                "review_reasons": [],
            },
        },
        "reviews": [
            {
                "path": "iePort",
                "status": "needs_review",
                "reasons": ["unknown_code:海关口岸代码"],
                "evidence": [
                    {
                        "sheet": "一般贸易出口",
                        "cell": "E4",
                        "quote": "一般贸易出口!E3:出境关别",
                    }
                ],
            }
        ],
    },
}


def multipart_openapi(schema: Schema | None = None) -> dict:
    schema = schema or load_schema()
    properties: dict = {
        "file": {
            "type": "string",
            "format": "binary",
            "description": "xlsx；以后同一接口接 PDF / zip",
        },
        "run": {
            "type": "boolean",
            "default": True,
            "description": "true 则同步跑完并返回报关单",
        },
    }
    for name in accepted_caller_keys(schema):
        spec = schema.field(name)
        properties[name] = {
            "type": "string",
            "description": spec.display_name if spec else name,
        }
    return {
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": properties,
                    }
                }
            },
        }
    }
