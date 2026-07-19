# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from tools.reachops_delivery_audit import run_operator_console_contract_fixture
from tools.reachops_delivery_audit import run_web_local_api_architecture_fixture


class OperatorControlsMappingTests(unittest.TestCase):
    def test_customer_visible_operator_controls_map_to_execution_evidence(self) -> None:
        evidence = run_operator_console_contract_fixture()
        self.assertTrue(evidence["operator_controls_all_real"])
        for label in [
            "每个目标最多视频",
            "每条视频最多评论",
            "参与账号数",
            "任务间隔秒",
            "意向词",
            "排除词",
            "触达并发",
        ]:
            self.assertTrue(evidence["operator_control_evidence"][label]["passed"], label)

    def test_live_actions_use_workbench_browser_adapter_contract(self) -> None:
        evidence = run_web_local_api_architecture_fixture()
        self.assertTrue(evidence["checks"]["actions_use_workbench_browser_adapter"])


if __name__ == "__main__":
    unittest.main()
