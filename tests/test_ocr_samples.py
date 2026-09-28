"""样本清单与派生单测（#109）：登记完整性、隐私红线、转正角、未覆盖类、A/B/C 对照。

**纯元数据部分不 import PIL / pymupdf**（本机不装 bench extra 也要跑得通）；
只有真开图 / 真渲染的用例才 importorskip。
"""

from __future__ import annotations

import pytest
from benchmarks.ocr import samples as sm

REAL_ORIGIN_KEYS = ("peninsula", "zhenfa")


def _spec(key: str) -> sm.SampleSpec:
    specs = sm.spec_by_key()
    assert key in specs, f"清单里没有 {key}"
    return specs[key]


def _base_of(page_key: str) -> sm.SampleSpec:
    """原件页那一份（夹具的原件页 key 与样本 key 不同名，不能直接查）。"""

    matches = [s for s in sm.sample_specs() if s.page_key == page_key and s.variant == "base"]
    assert len(matches) == 1, f"{page_key} 的 base 样本不是唯一：{matches}"
    return matches[0]


class TestCatalogShape:
    def test_keys_are_unique(self):
        keys = sm.sample_keys()
        assert len(keys) == len(set(keys))

    def test_original_pages_cover_both_real_files(self):
        pages = [
            page.key
            for origin in sm.origins()
            if origin.source == "real"
            for page in origin.pages
        ]
        assert pages == [
            "peninsula-p1",
            "peninsula-p2",
            "zhenfa-p1",
            "zhenfa-p2",
            "zhenfa-p3",
            "zhenfa-p4",
            "zhenfa-p5",
            "zhenfa-p6",
        ]

    def test_sample_count_is_pages_times_derivations(self):
        real_pages = sum(
            len(origin.pages) for origin in sm.origins() if origin.source == "real"
        )
        fixture_pages = sum(
            len(origin.pages) for origin in sm.origins() if origin.source == "fixture"
        )
        expected = real_pages * len(sm.REAL_DERIVATIONS)
        expected += fixture_pages * len(sm.FIXTURE_DERIVATIONS)
        assert len(sm.sample_specs()) == expected

    def test_real_base_pages_keep_legacy_key_names(self):
        """#60 / #108 的产物按这套名字落盘（out/results/<引擎>/zhenfa-p1.json），不能改。"""

        assert "zhenfa-p1" in sm.spec_by_key()
        assert "peninsula-p1" in sm.spec_by_key()
        assert "zhenfa-p1-base" not in sm.spec_by_key()

    def test_fixture_base_still_carries_variant_suffix(self):
        assert "a-base" in sm.spec_by_key()

    def test_every_spec_is_fully_registered(self):
        for spec in sm.sample_specs():
            assert spec.key
            assert spec.source in {"fixture", "real"}
            assert spec.kind
            assert spec.page >= 1
            assert spec.reference in sm.REFERENCES
            assert spec.notes
            assert spec.rotation_truth in {0, 90, 180, 270}

    def test_page_key_is_prefix_of_derived_keys(self):
        for spec in sm.sample_specs():
            assert spec.key == spec.page_key or spec.key.startswith(f"{spec.page_key}-")

    def test_unknown_source_raises(self):
        with pytest.raises(ValueError, match="未知来源"):
            sm.derivations_for("云端")


class TestPrivacyRedline:
    """（#108 / #97）客户真实数据不得上传云端，派生件继承原件。"""

    def test_real_originals_are_not_cloud_ok(self):
        for origin in sm.origins():
            if origin.source == "real":
                assert origin.cloud_ok is False

    def test_every_real_sample_including_derived_is_not_cloud_ok(self):
        real = [spec for spec in sm.sample_specs() if spec.source == "real"]
        assert real
        assert all(spec.cloud_ok is False for spec in real)
        derived = [spec for spec in real if spec.is_derived]
        assert derived, "真机派生件必须存在，否则隐私继承没被测到"
        assert all(spec.cloud_ok is False for spec in derived)

    def test_fixture_samples_may_go_to_cloud(self):
        for spec in sm.sample_specs():
            if spec.source == "fixture":
                assert spec.cloud_ok is True

    def test_cloud_ok_is_always_a_bool(self):
        for spec in sm.sample_specs():
            assert isinstance(spec.cloud_ok, bool)

    def test_real_maps_to_gated_target_kind(self):
        assert _spec("zhenfa-p1").target_kind == "real"
        assert _spec("a-base").target_kind == "synthetic"


class TestRotationTruth:
    """`rotation_truth` = 转正所需的逆时针角 = C 组 `--force-deg`（#97 钉的口径）。"""

    def test_zhenfa_p1_is_90(self):
        assert _spec("zhenfa-p1").rotation_truth == 90

    def test_zhenfa_p6_is_also_90(self):
        """#97 盘点时只记了 p1；实测 p6（规范申报要素）同样内容旋转 90°，如实登记。"""

        assert _spec("zhenfa-p6").rotation_truth == 90

    def test_peninsula_pages_are_not_content_rotation(self):
        """半岛是 PDF /Rotate 元数据，渲染时已转正——与真·内容旋转要分开说（#103）。"""

        for key in ("peninsula-p1", "peninsula-p2"):
            spec = _spec(key)
            assert spec.rotation_truth == 0
            assert not spec.is_rotation
            assert "Rotate" in spec.notes and "元数据" in spec.notes

    def test_zhenfa_flat_pages_are_upright(self):
        for key in ("zhenfa-p2", "zhenfa-p3", "zhenfa-p4", "zhenfa-p5"):
            assert _spec(key).rotation_truth == 0
            assert not _spec(key).is_rotation

    def test_derived_truth_is_complement_of_applied_angle(self):
        # 夹具 a-rot90 施加了 90°，转正就要 270°——名字与角度不是一回事
        assert _spec("a-rot90").rotation_truth == 270
        assert _spec("a-rot270").rotation_truth == 90
        assert _spec("a-rot180").rotation_truth == 180
        assert _spec("a-base").rotation_truth == 0

    def test_deriving_from_a_rotated_page_can_upright_it(self):
        assert _spec("zhenfa-p1-rot90").rotation_truth == 0
        assert not _spec("zhenfa-p1-rot90").is_rotation
        assert _spec("zhenfa-p1-rot180").rotation_truth == 270

    def test_non_rotation_derivations_keep_the_angle(self):
        for key in ("zhenfa-p1-lowres", "peninsula-p1-lowres", "a-lowres"):
            spec = _spec(key)
            assert spec.rotation_truth == _base_of(spec.page_key).rotation_truth

    def test_upright_counterpart_is_a_registered_sample(self):
        for case in sm.rotation_cases():
            assert case.upright_key in sm.spec_by_key()
            assert sm.spec_by_key()[case.upright_key].rotation_truth == 0
            assert sm.spec_by_key()[case.upright_key].page_key == case.page_key

    def test_rotation_cases_cover_every_rotated_page(self):
        rotated = [
            spec.page_key
            for spec in sm.sample_specs()
            if spec.variant == "base" and spec.is_rotation
        ]
        assert rotated == ["zhenfa-p1", "zhenfa-p6"]
        assert [case.page_key for case in sm.rotation_cases()] == rotated

    def test_c_command_carries_truth_as_force_deg(self):
        for case in sm.rotation_cases():
            command = case.c_command("local:paddle-v6-small")
            assert f"--force-deg {case.truth}" in command
            assert "--rotate-mode force" in command

    def test_a_command_feeds_the_upright_sample_with_rotation_off(self):
        case = next(c for c in sm.rotation_cases() if c.page_key == "zhenfa-p1")
        command = case.a_command("local:paddle-v6-small")
        assert "--rotate-mode off" in command
        assert "zhenfa-p1-rot90" in command
        assert "--scope real-derived" in command

    def test_b_command_uses_auto_on_the_original_page(self):
        case = next(c for c in sm.rotation_cases() if c.page_key == "zhenfa-p1")
        command = case.b_command("local:paddle-v6-small")
        assert "--rotate-mode auto" in command
        assert "--scope real" in command


class TestDerivations:
    def test_every_real_page_has_the_four_derivations(self):
        for origin in sm.origins():
            if origin.source != "real":
                continue
            for page in origin.pages:
                variants = {
                    spec.variant
                    for spec in sm.sample_specs()
                    if spec.page_key == page.key
                }
                assert variants == set(sm.REAL_DERIVATIONS)

    def test_real_derivations_are_implemented_by_the_fixture_renderer(self):
        assert set(sm.REAL_DERIVATIONS) <= set(sm.FIXTURE_DERIVATIONS)

    def test_every_derivation_has_metadata(self):
        for name in (*sm.FIXTURE_DERIVATIONS, *sm.REAL_DERIVATIONS):
            assert name in sm.DERIVATIONS
            assert sm.DERIVATIONS[name].kind

    def test_fixture_names_and_angles_agree_with_fixtures_module(self):
        """两张表（清单 / 夹具）不许漂：名字、类型、施加角都要对上。"""

        fx = pytest.importorskip("benchmarks.ocr.fixtures")
        assert tuple(sm.FIXTURE_DERIVATIONS) == tuple(fx.VARIANTS)
        for variant in fx.FIXTURE_VARIANTS:
            assert sm.DERIVATIONS[variant.name].kind == variant.kind
            assert sm.DERIVATIONS[variant.name].applied_deg == variant.applied_deg

    def test_declared_applied_deg_matches_real_rotation(self):
        """清单说 rot90 施加 90°，`apply_variant` 就得真转 90°（不是名字对就行）。"""

        PIL_Image = pytest.importorskip("PIL.Image")
        fx = pytest.importorskip("benchmarks.ocr.fixtures")
        base = PIL_Image.new("RGB", (40, 20), "white")
        base.putpixel((0, 0), (0, 0, 0))
        for name, deg in fx.ROTATION_VARIANTS.items():
            assert sm.DERIVATIONS[name].applied_deg == deg
            produced = fx.apply_variant(base, name)
            expected = base.rotate(deg, expand=True, fillcolor="white")
            assert produced.tobytes() == expected.tobytes()

    def test_truth_is_the_angle_that_really_uprights_the_derived_image(self):
        """语义锁：把派生件按 `rotation_truth` 转回去，方向标记要回到原位。"""

        PIL_Image = pytest.importorskip("PIL.Image")
        import io

        from benchmarks.ocr import local_engines as local

        base = PIL_Image.new("RGB", (80, 40), "white")
        base.putpixel((2, 2), (0, 0, 0))  # 左上角一块黑，用来认方向
        buffer = io.BytesIO()
        base.save(buffer, format="JPEG", quality=95)
        original = buffer.getvalue()

        for name in ("rot90", "rot180", "rot270"):
            truth = (0 - sm.DERIVATIONS[name].applied_deg) % 360
            derived = sm.derive(original, sm.DERIVATIONS[name])
            fixed = local.rotate_image_ccw(derived, truth)
            with PIL_Image.open(io.BytesIO(fixed)) as handle:
                assert handle.size == (80, 40)
                assert sum(handle.convert("RGB").getpixel((2, 2))) < 200

    def test_derive_base_is_passthrough(self):
        assert sm.derive(b"raw-bytes", sm.DERIVATIONS["base"]) == b"raw-bytes"


class TestUncovered:
    """#106 口径：没有来源的样本类要显式记账，不许用「样本有限」一句话带过。"""

    def test_three_classes_are_recorded(self):
        assert [item.key for item in sm.UNCOVERED] == [
            "dense-goods-table",
            "photo-capture",
            "real-landscape-more",
        ]

    def test_every_uncovered_entry_says_why_and_how(self):
        for item in sm.UNCOVERED:
            assert item.label and item.why and item.how

    def test_uncovered_keys_are_namespaced(self):
        assert sm.uncovered_keys() == [
            "uncovered:dense-goods-table",
            "uncovered:photo-capture",
            "uncovered:real-landscape-more",
        ]

    def test_photo_capture_is_recorded_as_its_own_failure_mode(self):
        item = next(i for i in sm.UNCOVERED if i.key == "photo-capture")
        assert "独立" in item.why

    def test_landscape_note_names_both_real_rotated_pages(self):
        item = next(i for i in sm.UNCOVERED if i.key == "real-landscape-more")
        assert "p1" in item.why and "p6" in item.why


class TestCoverageMatrix:
    def test_totals_match_the_catalog(self):
        rows = sm.coverage_matrix()
        assert sum(row.total for row in rows) == len(sm.sample_specs())
        assert sum(row.real for row in rows) == sum(
            1 for spec in sm.sample_specs() if spec.source == "real"
        )

    def test_every_kind_appears_once_and_is_sorted(self):
        kinds = [row.kind for row in sm.coverage_matrix()]
        assert kinds == sorted(set(kinds))

    def test_summary_counts_rotation_pages_and_uncovered(self):
        summary = sm.coverage_summary()
        assert summary["rotation_pages"] == len(sm.rotation_cases())
        assert summary["uncovered"] == len(sm.UNCOVERED)
        assert summary["samples"] == summary["real"] + summary["fixture"]


class TestListing:
    def test_prints_every_sample_key(self):
        listing = sm.format_listing()
        for spec in sm.sample_specs():
            assert spec.key in listing

    def test_carries_the_required_columns(self):
        listing = sm.format_listing()
        for column in ("key", "来源", "外呼", "类型", "参照", "真实角度"):
            assert column in listing

    def test_states_the_truth_convention(self):
        assert "C 组 --force-deg" in sm.format_listing()

    def test_marks_real_samples_as_not_callable(self):
        listing = sm.format_listing()
        line = next(line for line in listing.splitlines() if line.startswith("zhenfa-p1 "))
        assert "×" in line

    def test_prints_uncovered_classes(self):
        listing = sm.format_listing()
        for item in sm.UNCOVERED:
            assert item.key in listing

    def test_prints_rotation_plan_with_all_three_commands(self):
        listing = sm.format_listing()
        for case in sm.rotation_cases():
            assert case.upright_key in listing
            assert case.c_command() in listing
            assert case.a_command() in listing

    def test_no_markdown_bold_leaks_into_plain_text(self):
        assert "**" not in sm.format_listing()

    def test_mentions_missing_originals_when_present(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DOCPARSE_OCR_DEMO_DIR", str(tmp_path / "空目录"))
        listing = sm.format_listing()
        assert "本机缺原件" in listing
        assert "zhenfa" in listing


class TestScopeAndFilter:
    def test_scopes_cover_real_and_derived(self):
        assert set(sm.SCOPES) == {"fixtures", "real", "real-derived", "all"}

    def test_in_scope_splits_real_base_from_derived(self):
        base = _spec("zhenfa-p1")
        derived = _spec("zhenfa-p1-rot90")
        assert sm._in_scope(base, "real")
        assert not sm._in_scope(base, "real-derived")
        assert sm._in_scope(derived, "real-derived")
        assert not sm._in_scope(derived, "real")
        assert not sm._in_scope(derived, "fixtures")

    def test_unknown_scope_raises(self):
        with pytest.raises(ValueError, match="未知 scope"):
            sm._in_scope(_spec("a-base"), "云端")

    def test_sample_filter_without_wildcard_is_exact(self):
        assert sm._matches("zhenfa-p1", ("zhenfa-p1",))
        assert not sm._matches("zhenfa-p1-rot90", ("zhenfa-p1",))

    def test_sample_filter_supports_wildcards(self):
        assert sm._matches("zhenfa-p1-rot90", ("zhenfa-*",))
        assert not sm._matches("peninsula-p1", ("zhenfa-*",))

    def test_empty_filter_matches_everything(self):
        assert sm._matches("任意 key", ())


class TestMissingOriginals:
    def test_available_specs_drop_missing_originals(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DOCPARSE_OCR_DEMO_DIR", str(tmp_path / "空目录"))
        assert sm.missing_origin_keys() == REAL_ORIGIN_KEYS
        available = sm.available_sample_specs()
        assert available
        assert all(spec.source == "fixture" for spec in available)

    def test_missing_reference_is_not_the_same_as_missing_original(self):
        # 参照 JSON 缺了不影响这页能不能跑，只有原件缺了才整份跳过
        for origin in sm.origins():
            if origin.source == "real":
                assert origin.path
                assert origin.reference in sm.REFERENCES


def _run_module():
    """run.py 会连带 import fixtures / real（要 PIL、pymupdf），没装就整类跳过。"""

    return pytest.importorskip("benchmarks.ocr.run", reason="需要 bench extra（pillow / pymupdf）")


def _fixture_targets(run_mod) -> dict:
    args = run_mod.build_parser().parse_args(["call", "--scope", "fixtures"])
    try:
        return {target.key: target for target in run_mod._targets(args)}
    except RuntimeError as exc:  # 本机没有中文字体，夹具渲染不出来
        pytest.skip(str(exc))


class TestRunIntegration:
    def test_samples_subcommand_prints_the_listing(self, capsys):
        run_mod = _run_module()
        args = run_mod.build_parser().parse_args(["samples"])
        args.func(args)
        out = capsys.readouterr().out
        assert "样本清单（#109）" in out
        assert "zhenfa-p1-rot90" in out

    def test_scope_choices_come_from_the_catalog(self):
        run_mod = _run_module()
        parser = run_mod.build_parser()
        for scope in sm.SCOPES:
            assert parser.parse_args(["call", "--scope", scope]).scope == scope
        with pytest.raises(SystemExit):
            parser.parse_args(["call", "--scope", "云端"])

    def test_rotation_flag_follows_the_catalog_not_the_key_name(self):
        """夹具 a-rot90 名字里有 rot90 才被判成旋转页；真机 zhenfa-p1 靠 truth 判。"""

        run_mod = _run_module()
        targets = _fixture_targets(run_mod)
        assert targets["a-rot90"].rotation is True
        assert targets["a-rot90"].rotation_truth == 270
        assert targets["a-rot90"].sample_kind == "rot90"
        assert targets["a-base"].rotation is False
        assert targets["a-base"].kind == "synthetic"

    def test_real_page_rotation_comes_from_truth(self):
        pytest.importorskip("PIL")
        run_mod = _run_module()
        if sm.missing_origin_keys():
            pytest.skip("本机没有真机原件")
        args = run_mod.build_parser().parse_args(["call", "--scope", "real"])
        targets = {target.key: target for target in run_mod._targets(args)}
        assert targets["zhenfa-p1"].rotation is True
        assert targets["zhenfa-p1"].rotation_truth == 90
        assert targets["zhenfa-p2"].rotation is False
        assert targets["peninsula-p1"].kind == "real"

    def test_real_derived_scope_feeds_the_a_group_image(self):
        pytest.importorskip("PIL")
        run_mod = _run_module()
        if sm.missing_origin_keys():
            pytest.skip("本机没有真机原件")
        args = run_mod.build_parser().parse_args(
            ["call", "--scope", "real-derived", "--sample", "zhenfa-p1-rot90"]
        )
        targets = run_mod._targets(args)
        assert [target.key for target in targets] == ["zhenfa-p1-rot90"]
        assert targets[0].rotation is False  # 转正件是正立的
        assert targets[0].rotation_truth == 0

    def test_empty_targets_exit_with_hint(self, capsys):
        run_mod = _run_module()
        args = run_mod.build_parser().parse_args(
            ["call", "--engine", "local", "--sample", "不存在的 key"]
        )
        with pytest.raises(SystemExit):
            run_mod.cmd_call(args)
        assert "没有匹配的样本" in capsys.readouterr().out
