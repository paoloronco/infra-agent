from memory.manager import MemoryRecord, _extract_local_memories, format_records


def test_extracts_explicit_memory_from_user_message():
    records = _extract_local_memories(
        chat_id=7,
        user_message="Ricorda che preferisco risposte operative e sintetiche",
        assistant_message="Va bene.",
        target_host=None,
        metadata={"run_id": "run-1"},
    )

    assert len(records) == 2
    assert any(r.source == "user_explicit" for r in records)
    assert any(r.category == "preference" for r in records)


def test_extracts_operational_host_memory_from_agent_result():
    records = _extract_local_memories(
        chat_id=8,
        user_message="Controlla nginx",
        assistant_message="Host: web-prod\nExit code: 1\nActive: failed (Result: exit-code)",
        target_host="web-prod",
        metadata={"run_id": "run-2"},
    )

    assert len(records) == 1
    assert records[0].category == "system"
    assert records[0].target_host == "web-prod"
    assert "Exit code" in records[0].value


def test_format_records_groups_by_category():
    block = format_records([
        MemoryRecord(
            key="preference:abc",
            value="User prefers Italian.",
            category="preference",
            importance=0.9,
            confidence=0.8,
        ),
        MemoryRecord(
            key="system:web",
            value="nginx failed once with exit code 1.",
            category="system",
            target_host="web-prod",
        ),
    ])

    assert "[preference]" in block
    assert "[system]" in block
    assert "host=web-prod" in block
