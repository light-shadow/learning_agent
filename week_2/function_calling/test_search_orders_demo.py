"""search_orders 最小 Function Calling 练习的测试。"""
from __future__ import annotations

import json
import unittest

from search_orders_demo import SEARCH_ORDERS_TOOL, run_demo


class SearchOrdersDemoTest(unittest.TestCase):
    """验证模型可见工具定义和调用结果的关联关系。"""

    def test_tool_json_does_not_expose_internal_implementation(self) -> None:
        """验证 Tool JSON 不包含 handler、权限或内部依赖信息。"""
        serialized_tool = json.dumps(SEARCH_ORDERS_TOOL, ensure_ascii=False)
        self.assertNotIn("handler", serialized_tool)
        self.assertNotIn("权限", serialized_tool)
        self.assertNotIn("internal", serialized_tool.lower())

    def test_each_result_references_its_original_tool_call(self) -> None:
        """验证两条不同 ID 的调用分别得到正确关联的结果。"""
        _, tool_calls, tool_results = run_demo()

        self.assertEqual([call.id for call in tool_calls], ["call_search_orders_001", "call_search_orders_002"])
        self.assertEqual([result.tool_call_id for result in tool_results], [call.id for call in tool_calls])
        self.assertEqual(json.loads(tool_results[0].content)["total"], 2)
        self.assertEqual(json.loads(tool_results[1].content)["total"], 1)


if __name__ == "__main__":
    unittest.main()
