"""基于相同 LlamaIndex 节点的向量、BM25 和 RRF 混合检索演示。"""
import argparse
import json
import os
import shutil
import sys
import uuid
from pathlib import Path

from common import INITIAL_POLICY, POLICY_NAME, QUESTION, fuse, node_id, tokenize, update_policy

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent.parent / "login_demo"
DATA = ROOT / "data"


def settings():
    """加载本地 Hugging Face 向量模型并配置聊天模型服务。"""
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding
    from llama_index.llms.openai_like import OpenAILike
    import torch
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("缺少环境变量 DEEPSEEK_API_KEY")
    model_name = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Embedding 运行设备：{device}")
    embedding = HuggingFaceEmbedding(
        model_name=model_name,
        device=device,
        query_instruction="为这个句子生成表示以用于检索相关文章：",
    )
    llm = OpenAILike(
        model="deepseek-v4-flash",
        api_key=api_key,
        api_base="https://api.deepseek.com",
        is_chat_model=True,
        context_window=8192,
    )
    return embedding, llm


def copy_materials(destination):
    """复制登录相关文本资料并添加明确标记的演示策略。"""
    destination.mkdir(parents=True)
    files = [SOURCE / "README.md"]
    for directory in ("artifacts", "src", "tests"):
        files.extend(p for p in (SOURCE / directory).rglob("*") if p.is_file() and p.suffix in {".md", ".ts", ".py"})
    for path in files:
        target = destination / path.relative_to(SOURCE)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    (destination / POLICY_NAME).write_text(INITIAL_POLICY, encoding="utf-8")


def build_nodes(corpus):
    """读取资料副本并分块，给每个节点附加相对来源和内容标识。"""
    from llama_index.core import Document
    from llama_index.core.node_parser import SentenceSplitter
    splitter = SentenceSplitter(chunk_size=300, chunk_overlap=30)
    nodes = []
    for path in sorted(corpus.rglob("*")):
        if not path.is_file():
            continue
        source = path.relative_to(corpus).as_posix()
        doc = Document(text=path.read_text(encoding="utf-8-sig"), metadata={"source": source})
        for node in splitter.get_nodes_from_documents([doc]):
            node.id_ = node_id(source, node.text)
            nodes.append(node)
    if not nodes:
        raise ValueError("资料副本为空，无法建立索引")
    return nodes


def build_generation(corpus, embedding):
    """由同一批节点构建并持久化两个索引，成功后才切换当前版本。"""
    from llama_index.core import VectorStoreIndex
    from rank_bm25 import BM25Okapi
    generation = DATA / "versions" / uuid.uuid4().hex
    generation.mkdir(parents=True)
    shutil.copytree(corpus, generation / "corpus")
    nodes = build_nodes(generation / "corpus")
    index = VectorStoreIndex(nodes, embed_model=embedding, show_progress=True)
    index.storage_context.persist(persist_dir=str(generation / "vector"))
    tokens = [tokenize(node.text) for node in nodes]
    BM25Okapi(tokens)  # 建库时验证 BM25 语料；持久化分词和节点，加载时重建统计量。
    (generation / "bm25.json").write_text(json.dumps({"nodes": [node.model_dump(mode="json") for node in nodes], "tokens": tokens}, ensure_ascii=False), encoding="utf-8")
    DATA.mkdir(exist_ok=True)
    temp = DATA / "current.tmp"
    temp.write_text(generation.name, encoding="utf-8")
    os.replace(temp, DATA / "current")
    print(f"节点数量：{len(nodes)}；索引版本：{generation.name}")
    print(f"分块样例来源：{nodes[0].metadata['source']}\n{nodes[0].text}\n")
    return generation


def current_generation():
    """定位当前已成功完成的索引版本。"""
    pointer = DATA / "current"
    if not pointer.exists():
        raise ValueError("尚未建库，请先运行 init")
    return DATA / "versions" / pointer.read_text(encoding="utf-8").strip()


def query(generation, embedding, llm):
    """加载两路索引，展示前三和前五结果并用真实模型生成引用回答。"""
    from llama_index.core import StorageContext, load_index_from_storage
    from llama_index.core.schema import NodeWithScore, TextNode
    from rank_bm25 import BM25Okapi
    index = load_index_from_storage(StorageContext.from_defaults(persist_dir=str(generation / "vector")), embed_model=embedding)
    vector = index.as_retriever(similarity_top_k=5).retrieve(QUESTION)
    saved = json.loads((generation / "bm25.json").read_text(encoding="utf-8"))
    nodes = [TextNode.model_validate(item) for item in saved["nodes"]]
    scores = BM25Okapi(saved["tokens"]).get_scores(tokenize(QUESTION))
    ordered = sorted(range(len(nodes)), key=lambda i: (-float(scores[i]), nodes[i].node_id))[:5]
    keyword = [NodeWithScore(node=nodes[i], score=float(scores[i])) for i in ordered]
    combined = fuse([vector, keyword])
    for name, results in (("向量", [(x.node, x.score) for x in vector]), ("BM25", [(x.node, x.score) for x in keyword]), ("RRF 混合", combined)):
        print(f"\n{name}检索前 {len(results)} 条：")
        for rank, (node, score) in enumerate(results, 1):
            print(f"[{rank}] 分数={score:.6f} 来源={node.metadata['source']} 节点={node.node_id}\n{node.text}\n")
    evidence = "\n\n".join(f"[{i}] 来源：{node.metadata['source']}\n{node.text}" for i, (node, _) in enumerate(combined, 1))
    prompt = ("请仅依据以下资料回答问题，资料不足时明确说明。每个事实后用 [编号] 引用证据；"
              "注意区分作业演示假设和原项目实际行为。\n问题：" + QUESTION + "\n资料：\n" + evidence)
    response = llm.complete(prompt)
    print("\n混合检索回答：\n" + str(response))
    print("\n引用来源：")
    for i, (node, _) in enumerate(combined, 1):
        print(f"[{i}] {node.metadata['source']} (节点 {node.node_id})")
    return combined


def main():
    """执行建库、查询或资料更新，并保留失败时的原索引版本。"""
    parser = argparse.ArgumentParser(description="登录资料混合检索作业")
    parser.add_argument("action", choices=["init", "query", "update"])
    args = parser.parse_args()
    embedding, llm = settings()
    if args.action == "init":
        import tempfile
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            corpus = Path(temp) / "corpus"
            copy_materials(corpus)
            build_generation(corpus, embedding)
    elif args.action == "query":
        query(current_generation(), embedding, llm)
    else:
        import tempfile
        old = current_generation()
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            corpus = Path(temp) / "corpus"
            shutil.copytree(old / "corpus", corpus)
            policy = corpus / POLICY_NAME
            policy.write_text(update_policy(policy.read_text(encoding="utf-8")), encoding="utf-8")
            generation = build_generation(corpus, embedding)
        old_nodes = json.loads((old / "bm25.json").read_text(encoding="utf-8"))["nodes"]
        new_nodes = json.loads((generation / "bm25.json").read_text(encoding="utf-8"))["nodes"]
        old_ids = {n["id_"] for n in old_nodes if n["metadata"]["source"] == POLICY_NAME}
        new_ids = {n["id_"] for n in new_nodes if n["metadata"]["source"] == POLICY_NAME}
        if old_ids & new_ids:
            raise RuntimeError("旧策略分块仍存在于新版本")
        print(f"旧策略节点已退出当前索引：{len(old_ids)} 个；新策略节点：{len(new_ids)} 个")
        results = query(generation, embedding, llm)
        if any(node.node_id in old_ids for node, _ in results):
            raise RuntimeError("混合检索仍返回旧策略分块")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, ImportError) as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        sys.exit(1)
