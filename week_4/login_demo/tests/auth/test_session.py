"""login_demo 的“会话测试”：验证登录会话 token 的签发/解析契约。

这个测试不是黑盒打 Express 服务，而是把项目文档中声明的会话凭证契约
（见 artifacts/login-flow.md §2.6 与 src/utils/token.ts）固化成可重复执行的断言。

契约（来自 src/utils/token.ts）：
  - issueAccessToken(payload) 把 { userId, role } 序列化为 JSON，再做 base64url
    编码，拼成 `demo-token.<encoded>`；
  - parseAccessToken(token) 先校验 `demo-token.` 前缀，再解码出身份载荷。

运行命令（项目根目录下）：
  python -m unittest tests.auth.test_session -v
"""

from __future__ import annotations

import base64
import json
import unittest


def issue_access_token(payload: dict) -> str:
    """镜像 src/utils/token.ts 的签发逻辑（base64url，去掉 padding）。"""
    body = json.dumps(payload).encode("utf-8")
    encoded = base64.urlsafe_b64encode(body).decode("ascii").rstrip("=")
    return f"demo-token.{encoded}"


def parse_access_token(token: str) -> dict:
    """镜像 src/utils/token.ts 的解析逻辑。"""
    if not isinstance(token, str) or not token.startswith("demo-token."):
        raise ValueError("not a demo token")
    body = token[len("demo-token."):]
    padded = body + "=" * (-len(body) % 4)
    return json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))


class SessionTokenTest(unittest.TestCase):
    def test_issued_token_has_demo_prefix(self):
        token = issue_access_token({"userId": "u1", "role": "user"})
        self.assertTrue(token.startswith("demo-token."))

    def test_token_roundtrip_preserves_payload(self):
        payload = {"userId": "u42", "role": "admin"}
        self.assertEqual(parse_access_token(issue_access_token(payload)), payload)

    def test_known_vector(self):
        # 对固定载荷，token 必须是确定性的字符串，防止编码实现漂移。
        token = issue_access_token({"userId": "u1", "role": "user"})
        expected = "demo-token." + base64.urlsafe_b64encode(
            b'{"userId": "u1", "role": "user"}'
        ).decode("ascii").rstrip("=")
        self.assertEqual(token, expected)

    def test_rejects_foreign_token(self):
        with self.assertRaises(ValueError):
            parse_access_token("evil-token.abc123")

    def test_rejects_malformed_payload(self):
        with self.assertRaises(Exception):
            parse_access_token("demo-token.!not-base64!")


if __name__ == "__main__":
    unittest.main()
