"""容量压测装置（#98）的纯函数单测：本机不装 paddleocr / rapidocr 也能跑。

只测**不碰重依赖**的部分：批次分组 / 分片、档位解析、汇总口径、清单往返、表格、
以及「云引擎一律拒绝」这条红线。worker 里真跑引擎的部分不在这里测（那是服务器上的事）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from benchmarks.ocr import capacity
from benchmarks.ocr import local_engines as local


def _sample(origin: str, key: str) -> SimpleNamespace:
    return SimpleNamespace(spec=SimpleNamespace(origin=origin, key=key))


# ---------------------------------------------------------------------------
# 票分组与批次


class TestGroupTickets:
    def test_groups_by_origin_keeping_page_order(self) -> None:
        samples = [
            _sample("peninsula", "peninsula-p1"),
            _sample("peninsula", "peninsula-p2"),
            _sample("zhenfa", "zhenfa-p1"),
            _sample("zhenfa", "zhenfa-p2"),
        ]
        tickets = capacity.group_tickets(samples)
        assert [ticket.id for ticket in tickets] == ["peninsula", "zhenfa"]
        assert [page.id for page in tickets[0].pages] == ["peninsula-p1", "peninsula-p2"]
        assert [page.id for page in tickets[1].pages] == ["zhenfa-p1", "zhenfa-p2"]

    def test_empty(self) -> None:
        assert capacity.group_tickets([]) == []


class TestExpandBatch:
    def test_repeat_renames_ticket_ids(self) -> None:
        tickets = capacity.group_tickets([_sample("peninsula", "peninsula-p1")])
        batch = capacity.expand_batch(tickets, 3)
        assert [ticket.id for ticket in batch] == [
            "peninsula#r0",
            "peninsula#r1",
            "peninsula#r2",
        ]
        # 复制的是清单项，不是图：页 id 保持不变
        assert all(ticket.pages[0].id == "peninsula-p1" for ticket in batch)

    def test_page_order_preserved_across_origins(self) -> None:
        tickets = capacity.group_tickets(
            [_sample("a", "a-p1"), _sample("b", "b-p1")]
        )
        batch = capacity.expand_batch(tickets, 2)
        assert [ticket.id for ticket in batch] == ["a#r0", "b#r0", "a#r1", "b#r1"]

    def test_rejects_zero_repeat(self) -> None:
        with pytest.raises(ValueError):
            capacity.expand_batch([], 0)


class TestShardTickets:
    def _ticket(self, ticket_id: str, pages: int) -> capacity.TicketRef:
        return capacity.TicketRef(
            id=ticket_id,
            pages=[capacity.PageRef(id=f"{ticket_id}-p{i}", path="") for i in range(pages)],
        )

    def test_single_worker_gets_all(self) -> None:
        tickets = [capacity.TicketRef(id=f"t{i}") for i in range(3)]
        assert capacity.shard_tickets(tickets, 0, 1) == tickets

    def test_shard_covers_every_ticket_exactly_once(self) -> None:
        tickets = [capacity.TicketRef(id=f"t{i}") for i in range(7)]
        seen = [
            ticket.id
            for worker_id in range(4)
            for ticket in capacity.shard_tickets(tickets, worker_id, 4)
        ]
        assert sorted(seen) == [f"t{i}" for i in range(7)]

    def test_balances_page_load_uneven_tickets(self) -> None:
        # 半岛 2 页 / 镇发 6 页各 4 份：贪心配平后 4 个 worker 的页数应相等（各 8 页）
        tickets = []
        for index in range(4):
            tickets.append(self._ticket(f"peninsula#r{index}", 2))
            tickets.append(self._ticket(f"zhenfa#r{index}", 6))
        loads = [
            sum(len(ticket.pages) for ticket in capacity.shard_tickets(tickets, worker_id, 4))
            for worker_id in range(4)
        ]
        assert loads == [8, 8, 8, 8]

    def test_never_splits_a_ticket(self) -> None:
        tickets = [self._ticket(f"t{i}", 3) for i in range(4)]
        for ticket in tickets:
            holders = [
                worker_id
                for worker_id in range(4)
                if any(t.id == ticket.id for t in capacity.shard_tickets(tickets, worker_id, 4))
            ]
            assert len(holders) == 1  # 只落在一个 worker
            held = next(
                t for t in capacity.shard_tickets(tickets, holders[0], 4) if t.id == ticket.id
            )
            assert held.pages == ticket.pages  # 整票，页没被拆走

    def test_rejects_bad_args(self) -> None:
        with pytest.raises(ValueError):
            capacity.shard_tickets([], 0, 0)
        with pytest.raises(ValueError):
            capacity.shard_tickets([], 4, 4)


# ---------------------------------------------------------------------------
# 档位解析


class TestParseConcurrency:
    def test_basic(self) -> None:
        assert capacity.parse_concurrency("1,2,4,8") == [1, 2, 4, 8]

    def test_dedup_and_sort(self) -> None:
        assert capacity.parse_concurrency("4,1,2,1") == [1, 2, 4]

    def test_ignores_blank_pieces(self) -> None:
        assert capacity.parse_concurrency(" 1 , , 2 ") == [1, 2]

    def test_rejects_non_positive(self) -> None:
        with pytest.raises(ValueError):
            capacity.parse_concurrency("0,1")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError):
            capacity.parse_concurrency(" , ")


# ---------------------------------------------------------------------------
# 汇总口径


class TestSummarizeLevel:
    def test_throughput_and_latency(self) -> None:
        summary = capacity.summarize_level(
            device="gpu",
            engine="local:paddle-v6-small",
            concurrency=2,
            makespan_ms=1000.0,
            pages=[100.0, 200.0, 300.0, 400.0],
            tickets=[300.0, 700.0],
            page_count=4,
            ticket_count=2,
        )
        assert summary.pages_per_sec == 4.0
        assert summary.tickets_per_sec == 2.0
        assert summary.page_latency["n"] == 4
        assert summary.page_latency["p50"] == 250.0
        assert summary.ticket_latency["p50"] == 500.0

    def test_zero_makespan_reports_none_not_zero(self) -> None:
        summary = capacity.summarize_level(
            device="cpu",
            engine="local:paddle-v6-small",
            concurrency=1,
            makespan_ms=0.0,
            pages=[],
            tickets=[],
            page_count=0,
            ticket_count=0,
        )
        assert summary.pages_per_sec is None
        assert summary.tickets_per_sec is None
        assert summary.page_latency["p50"] is None

    def test_as_dict_roundtrips(self) -> None:
        summary = capacity.summarize_level(
            device="gpu",
            engine="local:paddle-v6-small",
            concurrency=1,
            makespan_ms=500.0,
            pages=[50.0],
            tickets=[50.0],
            page_count=1,
            ticket_count=1,
        )
        assert capacity.LevelSummary(**summary.as_dict()) == summary


# ---------------------------------------------------------------------------
# 清单往返


class TestManifestRoundTrip:
    def test_roundtrip(self) -> None:
        manifest = capacity.Manifest(
            engine="local:paddle-v6-small",
            device="gpu",
            rotate_mode="auto",
            force_deg=90,
            tickets=[
                capacity.TicketRef(
                    id="peninsula#r0",
                    pages=[capacity.PageRef(id="peninsula-p1", path="pages/peninsula-p1.jpg")],
                )
            ],
            warmup_pages=["pages/peninsula-p1.jpg"],
            page_count=1,
            ticket_count=1,
        )
        restored = capacity.Manifest.from_dict(manifest.as_dict())
        assert restored == manifest
        assert restored.tickets[0].pages[0].path == "pages/peninsula-p1.jpg"


# ---------------------------------------------------------------------------
# 红线：绝不接云引擎


class TestBuildEngineRejectsCloud:
    def test_cloud_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="不得外呼"):
            capacity.build_engine("textin-general", device="gpu", rotate_mode="auto")

    def test_doc_ori_rejected_as_ocr(self) -> None:
        # 不进 build_local_engines 就能判出来（local:doc-ori 本身也是 local:*）
        with pytest.raises(ValueError, match="方向分类"):
            capacity.build_engine("local:doc-ori", device="gpu", rotate_mode="auto")


# ---------------------------------------------------------------------------
# CPU 上的 Paddle 参数（#98 实测的 MKL-DNN 绕法）


class TestPaddleCpuKwargs:
    def test_gpu_gets_nothing(self) -> None:
        assert local.paddle_cpu_kwargs("gpu", 8) == {}

    def test_cpu_disables_mkldnn(self) -> None:
        kwargs = local.paddle_cpu_kwargs("cpu", 8)
        assert kwargs["enable_mkldnn"] is False
        assert kwargs["cpu_threads"] == 8

    def test_cpu_without_threads_omits_thread_arg(self) -> None:
        assert local.paddle_cpu_kwargs("cpu") == {"enable_mkldnn": False}


# ---------------------------------------------------------------------------
# 表格


class TestFormatTable:
    def test_renders_row_per_level(self) -> None:
        summary = capacity.summarize_level(
            device="gpu",
            engine="local:paddle-v6-small",
            concurrency=4,
            makespan_ms=2000.0,
            pages=[10.0, 20.0],
            tickets=[30.0],
            page_count=8,
            ticket_count=2,
            vram_card_peak_mb=900.0,
            vram_process_sum_mb=800.0,
        )
        text = capacity.format_table([summary], "设备 gpu")
        assert "### 设备 gpu" in text
        assert "| 4 |" in text
        assert "900" in text
        assert "-" in text  # 缺的列不编数，落成 -

    def test_none_latency_renders_dash(self) -> None:
        summary = capacity.summarize_level(
            device="cpu",
            engine="local:paddle-v6-small",
            concurrency=1,
            makespan_ms=0.0,
            pages=[],
            tickets=[],
            page_count=0,
            ticket_count=0,
        )
        text = capacity.format_table([summary], "设备 cpu")
        assert "|-|-|" in text.replace(" ", "")
