"""验证不依赖外部模型的融合与版本更新逻辑。"""
import unittest
from types import SimpleNamespace
from common import INITIAL_POLICY, fuse, node_id, update_policy


class CommonTest(unittest.TestCase):
    """覆盖融合去重及演示策略更新。"""

    def test_fusion_deduplicates_and_boosts_shared_node(self):
        """两路同时命中的节点应得到更高的融合分数。"""
        a = SimpleNamespace(node=SimpleNamespace(node_id="a"))
        b = SimpleNamespace(node=SimpleNamespace(node_id="b"))
        c = SimpleNamespace(node=SimpleNamespace(node_id="c"))
        result = fuse([[a, b], [c, b]])
        self.assertEqual([node.node_id for node, _ in result], ["b", "a", "c"])

    def test_policy_update_changes_identity(self):
        """更新只影响演示副本，且内容变化后节点标识发生变化。"""
        updated = update_policy(INITIAL_POLICY)
        self.assertIn("有效期为 20 分钟", updated)
        self.assertNotIn("有效期为 30 分钟", updated)
        self.assertNotEqual(node_id("policy", INITIAL_POLICY), node_id("policy", updated))
        with self.assertRaises(ValueError):
            update_policy(updated)


if __name__ == "__main__":
    unittest.main()
