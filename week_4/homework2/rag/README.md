# 登录资料混合检索 RAG

使用 LlamaIndex 分块并构建向量索引，对同一批节点使用 jieba 分词和 BM25，RRF 融合后调用真实聊天模型回答并显示引用。BM25 文件保存节点和分词，加载时重建统计量。更新重建两路索引，仅检索当前版本。

**资料边界：** 原项目 `src/utils/token.ts` 未实现过期校验，原始资料没有分钟数。程序在资料副本中新增 `artifacts/homework-session-policy.md`，将 30 分钟明确标为作业假设；更新后改为 20 分钟。这不是对原项目实际行为的声明，原项目不受修改。

## 配置与运行

需要 Python 3.10+、可连接 Hugging Face 的网络和 DeepSeek API 密钥。Embedding 使用 `BAAI/bge-small-zh-v1.5`，自动优先选择可用的 NVIDIA CUDA GPU，否则使用 CPU：首次运行时下载模型到 Hugging Face 本机缓存，后续复用缓存。下载完成后，本地向量化可以离线进行；生成回答仍需连接 DeepSeek API。

```powershell
cd H:\agent_fullstack_geek\learning_agent\week_4\homework2\rag
uv sync
uv run python -c "import torch; print('CUDA 可用:', torch.cuda.is_available(), 'PyTorch:', torch.__version__)"
# 若当前终端尚未设置，可设置：$env:DEEPSEEK_API_KEY = '<DeepSeek API Key>'
uv run python main.py init     # 截图 1：节点总数和带来源的分块
uv run python main.py query    # 截图 2：三路前 5 条、回答和来源
uv run python main.py update   # 截图 3：更新后的回答和来源
```

程序从当前进程环境变量 `DEEPSEEK_API_KEY` 读取密钥，使用 `https://api.deepseek.com` 和 `deepseek-v4-flash`。若密钥已设置在本机环境变量中，无需重复设置；新设置的用户环境变量可能需要重启终端或 Codex 后才能读取。不要将密钥提交到项目。可选地设置 `$env:EMBEDDING_MODEL` 为其他 Hugging Face 模型名或已下载模型的本地目录；代码的查询指令针对默认的中文 BGE 模型，换模型时也应核对其指令要求。各次使用相同的 embedding 模型和维度；从旧版在线模型切换或更换模型后必须先运行 `init`。`update` 只接受初始 30 分钟版本；重新演示先运行 `init`。结果可滚动查看并截取实际输出。

模型缓存默认由 Hugging Face 管理；可在首次运行前通过 `$env:HF_HOME = '本地缓存目录'` 自定义。模型完整下载后，可设置 `$env:HF_HUB_OFFLINE = '1'` 禁止访问 Hugging Face；如果缓存不完整或模型未下载，离线加载会失败。依赖包含 PyTorch，安装和首次下载可能需要较长时间及较多磁盘空间。

Windows x64 的 `uv sync` 从 PyTorch 官方 CUDA 12.8 软件源安装 PyTorch，需要能访问该源及足够的磁盘空间。执行上述检查应显示 CUDA 可用为 `True`；如果为 `False`，请检查 NVIDIA 驱动及 PyTorch 版本，程序会自动回退到 CPU。`requirements.txt` 的普通 pip 安装不保证获得 CUDA 版本，GPU 环境请使用 `uv sync`。

索引和资料副本保存在 `data/versions/`，`data/current` 指向当前版本。新版本写入成功后才切换指针，历史版本保留但不参与检索；索引可能包含项目源码，请注意本地保管。

可运行 `python -m unittest test_common -v` 检查无需模型的逻辑；这不代替真实模型的端到端验证。

