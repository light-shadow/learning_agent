# login_demo 测试说明

## 会话测试入口

- 测试文件：`tests/auth/test_session.py`
- 运行命令：`python -m unittest tests.auth.test_session -v`
- 覆盖内容：登录会话 token 的签发/解析契约（对应 `artifacts/login-flow.md` §2.6 与 `src/utils/token.ts`）。

## 期望结果

- 5 条断言全部通过（token 前缀、载荷往返、确定性向量、拒绝外来 token、拒绝畸形载荷）。
