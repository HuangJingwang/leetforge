"""Tests for config.py: plan config, AI config, round keys."""

import json
import pytest


@pytest.fixture(autouse=True)
def _patch_config(monkeypatch, tmp_path):
    monkeypatch.setattr("leetcode_auto.config.DATA_DIR", tmp_path)
    monkeypatch.setattr("leetcode_auto.config.PLAN_CONFIG_FILE", tmp_path / "plan_config.json")


class TestPlanConfig:
    def test_default_config(self):
        from leetcode_auto.config import load_plan_config
        cfg = load_plan_config()
        assert cfg["rounds"] == 5
        assert cfg["intervals"] == [1, 3, 7, 14]
        assert cfg["problem_list"] == "hot100"

    def test_save_and_load(self, tmp_path):
        from leetcode_auto.config import save_plan_config, load_plan_config
        save_plan_config({"rounds": 3, "intervals": [1, 3], "daily_new": 10,
                          "daily_review": 5, "deadline": "2025-06-01", "problem_list": "top150"})
        cfg = load_plan_config()
        assert cfg["rounds"] == 3
        assert cfg["problem_list"] == "top150"
        assert cfg["deadline"] == "2025-06-01"

    def test_intervals_auto_extend(self):
        from leetcode_auto.config import load_plan_config, save_plan_config
        save_plan_config({"rounds": 7, "intervals": [1, 3]})
        cfg = load_plan_config()
        # intervals should be extended to 6 entries (rounds-1)
        assert len(cfg["intervals"]) == 6


class TestRoundKeys:
    def test_default_round_keys(self):
        from leetcode_auto.config import get_round_keys
        keys = get_round_keys({"rounds": 5, "intervals": [1, 3, 7, 14]})
        assert keys == ("r1", "r2", "r3", "r4", "r5")

    def test_custom_round_keys(self):
        from leetcode_auto.config import get_round_keys
        keys = get_round_keys({"rounds": 3, "intervals": [1, 3]})
        assert keys == ("r1", "r2", "r3")

    def test_review_intervals(self):
        from leetcode_auto.config import get_review_intervals
        intervals = get_review_intervals({"rounds": 5, "intervals": [1, 3, 7, 14]})
        assert intervals == {"r2": 1, "r3": 3, "r4": 7, "r5": 14}


class TestAIConfig:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.setattr("leetcode_auto.config.AI_PROVIDER", "")
        monkeypatch.setattr("leetcode_auto.config.AI_API_KEY", "")
        from leetcode_auto.config import get_ai_config
        cfg = get_ai_config()
        assert cfg["enabled"] is False

    def test_enabled_with_key(self, monkeypatch):
        monkeypatch.setattr("leetcode_auto.config.AI_PROVIDER", "openai")
        monkeypatch.setattr("leetcode_auto.config.AI_API_KEY", "sk-test")
        monkeypatch.setattr("leetcode_auto.config.AI_MODEL", "")
        monkeypatch.setattr("leetcode_auto.config.AI_BASE_URL", "")
        from leetcode_auto.config import get_ai_config
        cfg = get_ai_config()
        assert cfg["enabled"] is True
        assert cfg["model"] == "gpt-4o"  # default
