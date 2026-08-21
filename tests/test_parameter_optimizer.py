import unittest

from ssquant.backtest.parameter_optimizer import ParameterOptimizer


def _strategy(_api):
    pass


class _Backtester:
    def __init__(self, outcomes):
        self.outcomes = outcomes

    def set_optimization_mode(self, _enabled):
        pass

    def run(self, *, strategy_params, **_kwargs):
        outcome = self.outcomes[strategy_params["trial"]]
        if isinstance(outcome, Exception):
            raise outcome
        return {"performance": outcome}


class ParameterOptimizerFailedTrialTests(unittest.TestCase):
    def _search(self, outcomes, higher_is_better):
        optimizer = ParameterOptimizer(
            _Backtester(outcomes),
            strategy=_strategy,
            logger=lambda _message: None,
        ).set_optimization_metric("score", higher_is_better=higher_is_better)
        return optimizer, optimizer.grid_search(
            {"trial": list(outcomes)}, skip_final_report=True
        )

    def test_grid_search_excludes_all_failed_trials_from_results_and_best(self):
        outcomes = {
            "none": {"score": None},
            "text": {"score": "not-a-number"},
            "error": RuntimeError("backtest failed"),
            "invalid": {"score": 999, "invalid_params": True},
            "negative": {"score": -2},
            "positive": {"score": 3},
        }
        optimizer, (best_params, _results) = self._search(outcomes, higher_is_better=True)

        self.assertEqual({entry["params"]["trial"] for entry in optimizer.results.values()}, {"negative", "positive"})
        self.assertEqual(best_params, {"trial": "positive"})
        self.assertEqual(optimizer.best_result, 3.0)

    def test_grid_search_preserves_negative_value_for_minimization(self):
        outcomes = {
            "invalid": {"score": -999, "invalid_params": True},
            "negative": {"score": -2},
            "positive": {"score": 3},
        }
        optimizer, (best_params, _results) = self._search(outcomes, higher_is_better=False)

        self.assertEqual({entry["params"]["trial"] for entry in optimizer.results.values()}, {"negative", "positive"})
        self.assertEqual(best_params, {"trial": "negative"})
        self.assertEqual(optimizer.best_result, -2.0)
