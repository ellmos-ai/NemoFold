from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from nemofold.providers import ProviderConfig, ProviderRequest, create_provider


class _LMStudioContractHandler(BaseHTTPRequestHandler):
    server: _RecordingHTTPServer

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        self.server.requests.append({"path": self.path, "body": body})
        payload = {
            "id": "lmstudio-contract-1",
            "model": "contract-model",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"answers": [], "unanswered_question_ids": ["q_001"]}
                        )
                    }
                }
            ],
            "usage": {"prompt_tokens": 11, "completion_tokens": 5},
        }
        encoded = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        return


class _RecordingHTTPServer(ThreadingHTTPServer):
    requests: list[dict[str, object]]


@contextmanager
def _contract_server() -> Iterator[tuple[_RecordingHTTPServer, str]]:
    server = _RecordingHTTPServer(("127.0.0.1", 0), _LMStudioContractHandler)
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_lm_studio_adapter_uses_real_loopback_http_and_json_schema() -> None:
    request = ProviderRequest(
        system_prompt="Use evidence only.",
        user_prompt='{"questions":[{"question_id":"q_001"}]}',
        response_schema={
            "type": "object",
            "properties": {
                "answers": {"type": "array"},
                "unanswered_question_ids": {"type": "array"},
            },
            "required": ["answers", "unanswered_question_ids"],
            "additionalProperties": False,
        },
    )

    with _contract_server() as (server, base_url):
        adapter = create_provider(
            ProviderConfig(
                provider_id="lm-studio",
                model="contract-model",
                base_url=base_url,
            )
        )
        response = adapter.generate(request)

    assert len(server.requests) == 1
    recorded = server.requests[0]
    assert recorded["path"] == "/v1/chat/completions"
    body = recorded["body"]
    assert isinstance(body, dict)
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "nemofold_provider_analysis",
            "strict": True,
            "schema": request.response_schema,
        },
    }
    assert "reasoning_effort" not in body
    assert response.request_id == "lmstudio-contract-1"
    assert response.usage == {"input_tokens": 11, "output_tokens": 5}
