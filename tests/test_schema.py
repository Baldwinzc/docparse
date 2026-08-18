from docparse.schema.loader import load_schema


def test_placeholder_schema_loads() -> None:
    schema = load_schema()
    assert schema.field("customs_declaration_no") is not None
    assert "rule" in schema.field("customs_declaration_no").extractors
