from offerbench import batching


def test_processes_all_items_in_order():
    seen = []
    n = batching.process_in_batches([1, 2, 3, 4, 5], seen.append, batch_size=2, batch_delay_s=0)
    assert seen == [1, 2, 3, 4, 5]
    assert n == 5


def test_pauses_between_batches_not_within_or_after_last(monkeypatch):
    sleeps = []
    monkeypatch.setattr(batching.time, "sleep", lambda s: sleeps.append(s))

    batching.process_in_batches([1, 2, 3, 4, 5], lambda x: None, batch_size=2, batch_delay_s=3.0)

    # 5 items, batch_size=2 -> batches of [1,2], [3,4], [5] -> 2 pauses (not after the last batch)
    assert sleeps == [3.0, 3.0]


def test_single_batch_never_sleeps(monkeypatch):
    sleeps = []
    monkeypatch.setattr(batching.time, "sleep", lambda s: sleeps.append(s))

    batching.process_in_batches([1, 2, 3], lambda x: None, batch_size=10, batch_delay_s=5.0)

    assert sleeps == []
