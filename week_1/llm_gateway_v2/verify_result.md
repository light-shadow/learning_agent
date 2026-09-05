## 验证输出的结果

Non-stream status: 200 <br>
Non-stream response: 
```
{
  "id": "71924df9-7367-4ab1-a173-93a5d75d47b1",
  "model": "deepseek-v4-pro",
  "content": "Hello! I'm doing well, thank you. How can I help you today?",
  "usage": {
    "prompt_tokens": 89,
    "completion_tokens": 65,
    "total_tokens": 154
  },
  "reasoning": "We need answer user. User says \"Hello, how are you?\" Need respond appropriately. We are AI assistant. Need be friendly. No need analysis. We can say hello, doing well, how can I help? Keep concise.",
  "latency_ms": 2142.446994781494,
  "first_token_latency_ms": null
}
``
Stream status: 200
Stream chunk: {'type': 'reasoning', 'content': 'We'}
Stream chunk: {'type': 'reasoning', 'content': ' need'}
Stream chunk: {'type': 'reasoning', 'content': ' answer'}
Stream chunk: {'type': 'reasoning', 'content': ' joke'}
Stream chunk: {'type': 'reasoning', 'content': '.'}
Stream chunk: {'type': 'reasoning', 'content': ' Need'}
Stream chunk: {'type': 'reasoning', 'content': ' comply'}
Stream chunk: {'type': 'reasoning', 'content': '.'}
Stream chunk: {'type': 'reasoning', 'content': ' Simple'}
Stream chunk: {'type': 'reasoning', 'content': '.'}
Stream chunk: {'type': 'content', 'content': 'Why'}
Stream chunk: {'type': 'content', 'content': ' don'}
Stream chunk: {'type': 'content', 'content': '’'}
Stream chunk: {'type': 'content', 'content': 't'}
Stream chunk: {'type': 'content', 'content': ' scientists'}
Stream chunk: {'type': 'content', 'content': ' trust'}
Stream chunk: {'type': 'content', 'content': ' atoms'}
Stream chunk: {'type': 'content', 'content': '?\n\n'}
Stream chunk: {'type': 'content', 'content': 'Because'}
Stream chunk: {'type': 'content', 'content': ' they'}
Stream chunk: {'type': 'content', 'content': ' make'}
Stream chunk: {'type': 'content', 'content': ' up'}
Stream chunk: {'type': 'content', 'content': ' everything'}
Stream chunk: {'type': 'content', 'content': '!'}
Template status: 200
Template response: 1. 这句话描述了一只狐狸跳过一只狗的场景。  
2. 狐狸被形容为动作敏捷、毛色棕黄。  
3. 狗则显得很懒惰，没有做出反应。
Structured output status: 200
Structured output: {"name": null, "age": null}
Valid JSON
Rate limit test results: [True, True, False]
All tests passed!