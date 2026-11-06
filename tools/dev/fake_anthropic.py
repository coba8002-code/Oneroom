"""Messages API 흉내 (시험용): 첫 요청엔 list_unpaid 도구 호출, 도구 결과가 오면 그 숫자로 답한다. 요청 본문을 기록."""
import json
from fastapi import FastAPI, Request

app = FastAPI()
LOG = []


@app.post("/v1/messages")
async def messages(req: Request):
    body = await req.json()
    LOG.append({"headers": {k: v for k, v in req.headers.items() if k.startswith("anthropic")}, "body": body})
    last = body["messages"][-1]
    base = {"id": "msg_fake", "type": "message", "role": "assistant", "model": body["model"], "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10}}
    if isinstance(last["content"], list) and last["content"] and last["content"][0].get("type") == "tool_result":
        data = json.loads(last["content"][0]["content"])
        items = data.get("items", [])
        text = "미수 " + ", ".join(f"{i['unit_no']}호 {i['outstanding']:,}원" for i in items) if items else "미수가 없습니다."
        return {**base, "stop_reason": "end_turn", "content": [{"type": "text", "text": text}]}
    return {**base, "stop_reason": "tool_use", "content": [
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {"type": "tool_use", "id": "toolu_1", "name": "list_unpaid", "input": {"as_of": ""}}]}


@app.get("/log")
def log():
    return LOG
