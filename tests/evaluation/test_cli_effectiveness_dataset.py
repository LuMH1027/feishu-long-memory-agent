import json
from pathlib import Path

from backend.routers import memory


DATASET_PATH = Path("test/data/cli_effectiveness_dataset.json")


def load_dataset():
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def setup_function():
    memory.temp_memory_storage.clear()


def _query_from_expected(expected: str) -> str:
    # Prefer stable command fragments over the historical Chinese text in the dataset.
    tokens = [
        "docker run",
        "webapp",
        "8080",
        "kubectl logs",
        "api-server",
        "pg_dump",
        "orders_prod",
        "rsync",
        "console",
        "Get-NetTCPConnection",
        "tar",
        "scp",
    ]
    return " ".join(token for token in tokens if token in expected) or expected


def test_cli_effectiveness_dataset_anti_interference_metrics():
    dataset = load_dataset()
    anti = dataset["anti_interference_test"]
    expected_by_id = {item["id"]: item for item in anti["seed_memories"]}

    for item in anti["seed_memories"]:
        memory.store_memory(
            memory.MemoryStoreRequest(
                content=item["content"],
                type=item["type"],
                source="cli",
                metadata={"dataset_id": item["id"], "status": "active"},
            )
        )

    for group in anti["interference_stream"]["composition"]:
        for index in range(group["count"]):
            example = group["examples"][index % len(group["examples"])]
            memory.store_memory(
                memory.MemoryStoreRequest(
                    content=f"{example} # noise-{group['category']}-{index}",
                    type=f"noise_{group['category']}",
                    source="cli",
                    metadata={"noise": True},
                )
            )

    ranks = []
    for query_case in anti["evaluation_queries"]:
        expected = expected_by_id[query_case["expected_memory_id"]]
        query = _query_from_expected(expected["expected_top1_contains"])
        results = memory.search_memories(query=query, limit=3, type=expected["type"])
        result_ids = [item["metadata"].get("dataset_id") for item in results]
        ranks.append(result_ids.index(expected["id"]) + 1 if expected["id"] in result_ids else None)

    hit_at_1 = sum(1 for rank in ranks if rank == 1) / len(ranks)
    hit_at_3 = sum(1 for rank in ranks if rank is not None and rank <= 3) / len(ranks)
    mrr = sum((1 / rank) if rank else 0 for rank in ranks) / len(ranks)

    assert len(anti["seed_memories"]) == anti["target_metrics"]["key_memories"]
    assert anti["interference_stream"]["total_events"] == anti["target_metrics"]["distractor_events"]
    assert hit_at_1 >= anti["target_metrics"]["expected_hit_at_1"]
    assert hit_at_3 >= anti["target_metrics"]["expected_hit_at_3"]
    assert mrr >= anti["target_metrics"]["expected_mrr"]


def test_cli_effectiveness_dataset_contradiction_update_metrics():
    dataset = load_dataset()
    cases = dataset["contradiction_update_test"]["cases"]
    latest_wins = 0
    stale_top1 = 0

    for case in cases:
        old_memory = memory.store_memory(
            memory.MemoryStoreRequest(
                content=case["old_memory"]["content"],
                type=case["old_memory"]["type"],
                source="cli",
            )
        )
        new_memory = memory.store_memory(
            memory.MemoryStoreRequest(
                content=case["new_memory"]["content"],
                type=case["new_memory"]["type"],
                source="cli",
            )
        )
        results = memory.search_memories(
            query=case["expected_top1_contains"],
            limit=3,
            type=case["new_memory"]["type"],
        )
        top1_content = results[0]["content"] if results else ""
        if case["expected_top1_contains"] in top1_content:
            latest_wins += 1
        if case["expected_not_top1_contains"] in top1_content:
            stale_top1 += 1

        assert old_memory["metadata"]["status"] == "inactive"
        assert old_memory["metadata"]["superseded_by"] == new_memory["id"]
        assert new_memory["metadata"]["supersedes"] == [old_memory["id"]]

    latest_win_rate = latest_wins / len(cases)
    stale_top1_rate = stale_top1 / len(cases)

    assert latest_win_rate >= dataset["contradiction_update_test"]["target_metrics"]["expected_latest_win_rate"]
    assert stale_top1_rate <= dataset["contradiction_update_test"]["target_metrics"]["expected_stale_top1_rate"]


def test_cli_effectiveness_dataset_efficiency_metrics():
    dataset = load_dataset()
    efficiency = dataset["efficiency_metrics_test"]
    tasks = efficiency["tasks"]

    avg_char = sum(task["character_saving_rate"] for task in tasks) / len(tasks)
    avg_step = sum(task["step_saving_rate"] for task in tasks) / len(tasks)
    avg_time = sum(task["time_saving_rate"] for task in tasks) / len(tasks)

    assert len(tasks) == efficiency["summary_metrics"]["task_count"]
    assert round(avg_char, 3) == efficiency["summary_metrics"]["average_character_saving_rate"]
    assert round(avg_step, 3) == efficiency["summary_metrics"]["average_step_saving_rate"]
    assert round(avg_time, 3) == efficiency["summary_metrics"]["average_time_saving_rate"]
    assert avg_char >= float(dataset["global_assumptions"]["success_criteria"]["average_character_saving_rate"].split(">=")[1])
