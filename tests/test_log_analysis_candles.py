"""Historical candle download and cache used by the log analysis."""

import pandas as pd
import pytest

from tools.log_analysis.candles import CandleStore, fetch_candles

FIVE_MINUTES_MS = 5 * 60 * 1000
START_MS = 1_780_000_000_000


class FakeExchange:
    """Serves candles the way Bitvavo does: newest first, start inclusive,
    end exclusive, and `limit` bounds the time slots looked back from `end`
    (empty slots included), so a page of sparse data can be short while
    older candles still exist."""

    def __init__(self, candles):
        self.candles = candles
        self.calls = 0

    def __call__(self, market, params):
        self.calls += 1
        if market == 'GONE-EUR':
            return {'errorCode': 219, 'error': 'This market has been delisted.'}
        oldest = max(params['start'], params['end'] - params['limit'] * FIVE_MINUTES_MS)
        inside = [c for c in self.candles if oldest <= c[0] < params['end']]
        return sorted(inside, key=lambda c: -c[0])


def synthetic(n):
    return [[START_MS + i * FIVE_MINUTES_MS, '1', '1', '1', str(1 + i), '10'] for i in range(n)]


def test_fetch_pages_back_through_the_range_and_returns_oldest_first():
    exchange = FakeExchange(synthetic(25))

    candles = fetch_candles('ABC-EUR', START_MS, START_MS + 24 * FIVE_MINUTES_MS, get=exchange, limit=10, pause=0)

    assert [c[0] for c in candles] == [START_MS + i * FIVE_MINUTES_MS for i in range(25)]
    assert exchange.calls == 3


def test_fetch_keeps_paging_through_sparse_data():
    # Bitvavo omits intervals without trades, so a page can be short even
    # though older candles exist; a short page is not the end of the data
    sparse = [c for i, c in enumerate(synthetic(30)) if i % 2 == 0]
    exchange = FakeExchange(sparse)

    candles = fetch_candles('ABC-EUR', START_MS, START_MS + 29 * FIVE_MINUTES_MS, get=exchange, limit=10, pause=0)

    assert len(candles) == 15


def test_fetch_stops_at_the_start_of_the_range():
    exchange = FakeExchange(synthetic(25))

    candles = fetch_candles('ABC-EUR', START_MS + 20 * FIVE_MINUTES_MS, START_MS + 24 * FIVE_MINUTES_MS,
                            get=exchange, limit=10, pause=0)

    assert len(candles) == 5


def test_fetch_returns_nothing_for_an_unavailable_market():
    assert fetch_candles('GONE-EUR', START_MS, START_MS + FIVE_MINUTES_MS, get=FakeExchange([]), pause=0) == []


class TestCandleStore:
    def test_round_trip_as_dataframe(self, tmp_path):
        store = CandleStore(tmp_path / 'candles.db')
        store.save('ABC-EUR', synthetic(3))

        df = store.load('ABC-EUR')

        assert list(df.columns) == ['open', 'high', 'low', 'close', 'volume']
        assert df.index[0] == pd.Timestamp(START_MS, unit='ms')
        assert df['close'].tolist() == [1.0, 2.0, 3.0]

    def test_saving_twice_does_not_duplicate(self, tmp_path):
        store = CandleStore(tmp_path / 'candles.db')
        store.save('ABC-EUR', synthetic(3))
        store.save('ABC-EUR', synthetic(3))

        assert len(store.load('ABC-EUR')) == 3

    def test_markets_lists_what_was_fetched_including_empty(self, tmp_path):
        store = CandleStore(tmp_path / 'candles.db')
        store.save('ABC-EUR', synthetic(3))
        store.save('GONE-EUR', [])

        assert store.fetched_markets() == {'ABC-EUR', 'GONE-EUR'}

    def test_unknown_market_loads_empty(self, tmp_path):
        assert CandleStore(tmp_path / 'candles.db').load('NOPE-EUR').empty


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    import tools.log_analysis.candles as module
    monkeypatch.setattr(module, 'bitvavo_get', lambda *a, **k: pytest.fail('network access in a unit test'))
