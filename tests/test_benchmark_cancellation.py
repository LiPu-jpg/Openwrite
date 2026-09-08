import threading
from concurrent.futures import ThreadPoolExecutor

from tools.benchmark_scheduler import run_bounded
from tools.llm.cancellation import check_model_cancellation, model_cancellation


def test_cancel_stops_backlog_and_retains_inflight_results():
    started = threading.Event()
    stop = threading.Event()
    release = threading.Event()
    draining = threading.Event()
    calls = []
    results = []

    def execute(index):
        calls.append(index)
        started.set()
        assert release.wait(5)
        return {"usage": {"total_tokens": 42}, "index": index}

    with ThreadPoolExecutor(max_workers=1) as owner:
        future = owner.submit(run_bounded, [(i,) for i in range(10)], execute,
                              concurrency=1, cancelled=stop.is_set,
                              completed=lambda value, count: results.append(value), draining=lambda count: draining.set())
        assert started.wait(5)
        stop.set()
        assert draining.wait(2), "Cancellation must be observed before the provider returns"
        assert not future.done(), "In-flight billing is still unknown"
        release.set()
        future.result(timeout=5)
    assert calls == [0]
    assert results == [{"usage": {"total_tokens": 42}, "index": 0}]


def test_model_boundary_refuses_followup_calls_after_cancel():
    import pytest
    with model_cancellation(lambda: True), pytest.raises(RuntimeError, match="MODEL_CANCELLED"):
        check_model_cancellation()


def test_benchmark_persists_partial_result_and_billing_while_cancel_drains(tmp_path):
    from tools.model_benchmark import ModelBenchmarkService
    from tools.model_profiles import ModelProfileStore
    store = ModelProfileStore(tmp_path / 'profiles')
    for name in ['writer', 'critic']:
        store.save_profile({'id': name, 'label': name, 'provider': 'openai',
                            'base_url': 'https://example.invalid/v1', 'model': name,
                            'api_format': 'chat', 'max_output_tokens': 1000}, api_key='test-only')
    cancel = threading.Event()
    started = threading.Event()
    release = threading.Event()
    observed = threading.Event()
    calls = []
    partials = []

    def generate(*_args):
        calls.append('generate')
        started.set()
        assert release.wait(5)
        return {'title': '测试', 'content': '已完成的候选', 'word_count': 6,
                'usage': {'prompt_tokens': 12, 'completion_tokens': 8, 'total_tokens': 20, 'cost_usd': 0.004},
                'cost_usd': 0.004, 'finish_reason': 'stop'}

    def partial(value):
        partials.append(value)
        if value['status'] == 'cancelling' and value['in_flight'] > 0:
            observed.set()

    service = ModelBenchmarkService(tmp_path, 'book', store, generation_executor=generate,
                                   review_executor=lambda *_args: calls.append('review'), readiness_gate=False)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(service.run, {
            'writer_profile_ids': ['writer'], 'reviewer_profile_id': 'critic', 'repeats': 3,
            'target_words': 1000, 'concurrency': 1, 'execution_mode': 'creative',
        }, {'chapter_id': 'ch_001', 'packet': {'outline': '测试大纲'}}, cancelled=cancel.is_set,
            partial=partial, task_id='test-cancel')
        assert started.wait(5)
        cancel.set()
        assert observed.wait(2)
        saved = service.store.load(partials[-1]['run_id'])
        assert saved['status'] == 'cancelling'
        assert saved['in_flight'] == 1
        assert not future.done()
        release.set()
        result = future.result(timeout=5)
    assert result['status'] == 'cancelled'
    assert calls == ['generate']
    saved = service.store.load(result['run_id'])
    assert len(saved['candidates']) == 1
    assert saved['evaluations'] == []
    assert saved['summary']['total_tokens'] == 20
    assert saved['summary']['total_cost_usd'] == 0.004
    assert saved['in_flight'] == 0
