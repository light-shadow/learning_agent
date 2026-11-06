"""与模型服务无关的分词、融合和演示资料操作。"""
import hashlib
import re

QUESTION = "登录会话的有效期是多少分钟？"
POLICY_NAME = "artifacts/homework-session-policy.md"
INITIAL_POLICY = """# 作业演示：假设的登录会话策略

本文件是为检索作业新增的假设资料，不代表 login_demo 的实际实现。
本作业演示中，登录会话的有效期为 30 分钟。
原始 login_demo 的 token 没有实现过期时间校验。
"""


def tokenize(text):
    """使用中文分词和连续字符组成关键词，供文档和查询共同使用。"""
    import jieba
    return [word.lower() for word in jieba.lcut(text) if re.search(r"[\w\u4e00-\u9fff]", word)]


def node_id(source, text):
    """根据来源和分块内容生成稳定标识，内容变化时标识也随之变化。"""
    return hashlib.sha256((source + "\0" + text).encode("utf-8")).hexdigest()


def fuse(rankings, limit=5, k=60):
    """按节点标识合并多路排序，使用 RRF 分数从高到低返回结果。"""
    scores, nodes = {}, {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, 1):
            key = item.node.node_id
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            nodes[key] = item.node
    return [(nodes[key], scores[key]) for key in sorted(scores, key=lambda key: (-scores[key], key))[:limit]]


def update_policy(text):
    """只替换演示策略中的初始有效期，避免误改其他资料。"""
    old = "登录会话的有效期为 30 分钟"
    if text.count(old) != 1:
        raise ValueError("演示资料中必须恰好包含一处初始有效期 30 分钟")
    return text.replace(old, "登录会话的有效期为 20 分钟")
