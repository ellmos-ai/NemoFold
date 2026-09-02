from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import pytest

import nemofold.nebius_token_factory as token_factory_module
from nemofold.contracts import ActionMode, JobEnvelope, PrivacyMode, SourceRecord
from nemofold.document_index import SearchHit
from nemofold.evidence_analyst import ContextReceipt
from nemofold.live_result import json_sha256, validate_result_package
from nemofold.nebius_token_factory import (
    HTTPExchange,
    TokenFactoryConfig,
    preflight_token_factory_package,
    run_token_factory_package,
)
from nemofold.nemoclaw_package import (
    TRANSFER_ATTEMPT_FILENAME,
    export_job_package,
    validate_job_package,
)
from nemofold.policy import PolicyConfig, PolicyGate

QUESTION = "When does coverage begin?"
QUOTE = "Coverage begins in April."
MODEL_ID = "nvidia/nemotron-3-super-120b-a12b"


def make_package(tmp_path, *, budget: float = 1.0, model_id: str = MODEL_ID):
    private = tmp_path / "private"
    private.mkdir()
    job = JobEnvelope(
        workflow="evidence_analyst",
        input_roots=(str(private),),
        output_dir=str(private / "out"),
        questions=(QUESTION,),
        privacy_mode=PrivacyMode.ALLOW_ONCE,
        action_mode=ActionMode.DRY_RUN,
        model_id=model_id,
        model_budget_usd=budget,
        sources=(
            SourceRecord(
                source_id="src_a",
                path=str(private / "private.txt"),
                display_name="case/current.txt",
                sha256="a" * 64,
                mime_type="text/plain",
            ),
        ),
    )
    receipt = ContextReceipt(
        question=QUESTION,
        hits=(
            SearchHit(
                chunk_id="src_a:000000",
                source_id="src_a",
                text=QUOTE,
                rank=-1.0,
                char_end=len(QUOTE),
                line_end=1,
            ),
        ),
    )
    decision = PolicyGate(
        PolicyConfig(
            allowed_roots=job.input_roots,
            external_models_allowed=True,
            max_external_cost_usd=budget,
        )
    ).evaluate(job)
    return export_job_package(
        job,
        (receipt,),
        decision,
        tmp_path / "package",
        run_id="live_run_001",
    ).path


def successful_body(*, quote: str = QUOTE) -> bytes:
    output = {
        "answers": [
            {
                "question": QUESTION,
                "status": "answered",
                "claims": [
                    {
                        "statement": "Coverage begins in April.",
                        "uncertainty": 0.0,
                        "conflict_status": "none",
                        "evidence": [
                            {
                                "chunk_id": "src_a:000000",
                                "source_id": "src_a",
                                "quote": quote,
                            }
                        ],
                    }
                ],
            }
        ],
        "read_source_ids": ["src_a"],
    }
    return json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps(output)},
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
        }
    ).encode()


def catalog_body(*model_ids: str) -> bytes:
    listed = model_ids or (MODEL_ID,)
    return json.dumps(
        {"object": "list", "data": [{"id": item, "object": "model"} for item in listed]}
    ).encode()


def catalog_exchange(*model_ids: str, status: int = 200) -> HTTPExchange:
    return HTTPExchange(
        status=status,
        headers={"content-type": "application/json"},
        body=catalog_body(*model_ids),
    )


@dataclass
class RecordingTransport:
    exchange: HTTPExchange = field(
        default_factory=lambda: HTTPExchange(
            status=200,
            headers={"content-type": "application/json", "x-request-id": "req-test"},
            body=successful_body(),
        )
    )
    catalog: HTTPExchange = field(default_factory=catalog_exchange)
    calls: list[dict[str, object]] = field(default_factory=list)
    catalog_calls: list[dict[str, object]] = field(default_factory=list)

    def post(self, url, *, headers, body, timeout_seconds):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "body": body,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.exchange

    def get(self, url, *, headers, timeout_seconds):
        self.catalog_calls.append(
            {"url": url, "headers": headers, "timeout_seconds": timeout_seconds}
        )
        return self.catalog


def config(**overrides) -> TokenFactoryConfig:
    values = {
        "api_key": "test-secret-do-not-log",
        "input_price_usd_per_million": 0.1,
        "output_price_usd_per_million": 0.2,
        "max_completion_tokens": 100,
    }
    values.update(overrides)
    return TokenFactoryConfig(**values)


def test_live_adapter_records_verifiable_proof_without_secret(tmp_path) -> None:
    package = make_package(tmp_path)
    transport = RecordingTransport()

    result_path = run_token_factory_package(
        package,
        config(declared_nemoclaw_version="0.1.0-test"),
        approve_live_transfer=True,
        transport=transport,
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    validation = validate_result_package(package)

    assert len(transport.calls) == 1
    assert transport.calls[0]["url"] == ("https://api.tokenfactory.nebius.com/v1/chat/completions")
    assert transport.calls[0]["headers"]["Authorization"] == ("Bearer test-secret-do-not-log")
    assert result["status"] == "executed"
    assert result["transfer_performed"] is True
    assert result["cloud_proof"] is True
    assert result["runtime_evidence"]["declared_execution_environment"] == "nemoclaw"
    assert result["runtime_evidence"]["declared_nemoclaw_version"] == "0.1.0-test"
    assert result["runtime_evidence"]["nemoclaw_proof"] is False
    assert validation.valid is True
    assert validate_job_package(package).valid is True
    assert "test-secret-do-not-log" not in result_path.read_text(encoding="utf-8")

    with pytest.raises(FileExistsError, match="duplicate paid request"):
        run_token_factory_package(
            package,
            config(),
            approve_live_transfer=True,
            transport=transport,
        )
    assert len(transport.calls) == 1


def test_request_uses_portable_json_mode_and_supplies_the_local_schema(tmp_path) -> None:
    package = make_package(tmp_path)
    transport = RecordingTransport()

    run_token_factory_package(
        package,
        config(),
        approve_live_transfer=True,
        transport=transport,
    )

    request = json.loads(transport.calls[0]["body"])
    task = json.loads(request["messages"][1]["content"])

    assert request["response_format"] == {"type": "json_object"}
    assert task["output_schema"]["type"] == "object"
    assert task["output_schema"]["required"] == ["answers", "read_source_ids"]
    assert task["output_schema"]["additionalProperties"] is False


def test_preflight_proves_local_readiness_without_network_or_writes(tmp_path) -> None:
    package = make_package(tmp_path)
    before = sorted(path.name for path in package.iterdir())

    report = preflight_token_factory_package(
        package,
        config(),
        api_key_present=False,
    )

    assert report["local_preflight_passed"] is True
    assert report["transfer_prerequisites_present"] is False
    assert report["external_gates"] == [
        "api_key_missing",
        "explicit_user_approval_required",
    ]
    assert report["model_id"] == MODEL_ID
    assert report["response_mode"] == "json_object"
    assert report["local_schema_in_payload"] is True
    assert report["budget_ok"] is True
    assert report["network_called"] is False
    assert report["transfer_performed"] is False
    assert report["cloud_proof"] is False
    assert sorted(path.name for path in package.iterdir()) == before


def test_preflight_blocks_a_package_with_existing_transfer_evidence(tmp_path) -> None:
    package = make_package(tmp_path)
    (package / TRANSFER_ATTEMPT_FILENAME).write_text("{}\n", encoding="utf-8")

    report = preflight_token_factory_package(package, config(), api_key_present=True)

    assert report["local_preflight_passed"] is False
    assert report["transfer_prerequisites_present"] is False
    assert "transfer_attempt_already_exists" in report["errors"]


def test_provider_echoed_secret_is_redacted_before_result_is_written(tmp_path) -> None:
    package = make_package(tmp_path)
    echoed_secret = "Bearer test-secret-do-not-log"
    transport = RecordingTransport(
        exchange=HTTPExchange(
            status=400,
            headers={"content-type": "application/json", "x-request-id": echoed_secret},
            body=json.dumps({"error": echoed_secret, echoed_secret: "redacted key"}).encode(),
        )
    )

    result_path = run_token_factory_package(
        package,
        config(),
        approve_live_transfer=True,
        transport=transport,
    )
    result_text = result_path.read_text(encoding="utf-8")
    result = json.loads(result_text)

    assert echoed_secret not in result_text
    assert result["provider_log"]["response"]["body"]["error"] == "<SECRET_001>"
    assert result["provider_log"]["response"]["body"]["<SECRET_001>"] == "redacted key"
    assert result["provider_log"]["response"]["headers"]["x-request-id"] == "<SECRET_001>"
    assert validate_result_package(package).valid is True


def test_non_json_provider_secret_is_redacted_before_result_is_written(tmp_path) -> None:
    package = make_package(tmp_path)
    echoed_secret = "Bearer test-secret-do-not-log"
    transport = RecordingTransport(
        exchange=HTTPExchange(
            status=502,
            headers={"content-type": "text/plain"},
            body=f"upstream error: {echoed_secret}".encode(),
        )
    )

    result_path = run_token_factory_package(
        package,
        config(),
        approve_live_transfer=True,
        transport=transport,
    )
    result_text = result_path.read_text(encoding="utf-8")
    result = json.loads(result_text)

    assert echoed_secret not in result_text
    assert result["provider_log"]["response"]["body"]["raw_text"] == (
        "upstream error: <SECRET_001>"
    )
    assert validate_result_package(package).valid is True


def test_adapter_blocks_without_approval_before_transport(tmp_path) -> None:
    package = make_package(tmp_path)
    transport = RecordingTransport()

    with pytest.raises(PermissionError, match="explicit approval"):
        run_token_factory_package(
            package,
            config(),
            approve_live_transfer=False,
            transport=transport,
        )

    assert transport.calls == []

    costly = config(input_price_usd_per_million=100_000.0)
    with pytest.raises(PermissionError, match="cost bound exceeds"):
        run_token_factory_package(
            package,
            costly,
            approve_live_transfer=True,
            transport=transport,
        )
    assert transport.calls == []
    assert not (package / "result.json").exists()


def test_uncertain_transport_attempt_is_durable_and_blocks_retry(tmp_path) -> None:
    package = make_package(tmp_path)

    class UncertainTransport:
        calls = 0

        def post(self, url, *, headers, body, timeout_seconds):
            self.calls += 1
            raise OSError("connection ended without a response")

        def get(self, url, *, headers, timeout_seconds):
            return catalog_exchange()

    transport = UncertainTransport()
    with pytest.raises(OSError, match="without a response"):
        run_token_factory_package(
            package,
            config(),
            approve_live_transfer=True,
            transport=transport,
        )

    attempt_path = package / TRANSFER_ATTEMPT_FILENAME
    attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
    assert attempt["status"] == "request_ready"
    assert attempt["request_sha256"]
    assert attempt["response_sha256"] is None
    assert transport.calls == 1

    with pytest.raises(FileExistsError, match="duplicate paid request"):
        run_token_factory_package(
            package,
            config(),
            approve_live_transfer=True,
            transport=transport,
        )
    assert transport.calls == 1


def test_adapter_rejects_unapproved_endpoint_and_excessive_cost_before_transport(
    tmp_path,
) -> None:
    package = make_package(tmp_path)
    transport = RecordingTransport()

    with pytest.raises(ValueError, match="outside the approved Nebius endpoint"):
        run_token_factory_package(
            package,
            config(base_url="https://example.org/v1"),
            approve_live_transfer=True,
            transport=transport,
        )
    assert transport.calls == []


def test_adapter_rejects_non_finite_job_budget_before_transport(tmp_path) -> None:
    package = make_package(tmp_path)
    job_path = package / "job.json"
    job = json.loads(job_path.read_text(encoding="utf-8"))
    job["model"]["max_cost_usd"] = float("nan")
    job_bytes = (json.dumps(job, indent=2, sort_keys=True) + "\n").encode("utf-8")
    job_path.write_bytes(job_bytes)
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["job.json"] = hashlib.sha256(job_bytes).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    transport = RecordingTransport()

    with pytest.raises(ValueError, match="model_budget_invalid"):
        run_token_factory_package(
            package,
            config(),
            approve_live_transfer=True,
            transport=transport,
        )

    assert transport.calls == []
    assert not (package / TRANSFER_ATTEMPT_FILENAME).exists()


def test_parallel_starts_create_one_attempt_and_one_paid_request(tmp_path, monkeypatch) -> None:
    package = make_package(tmp_path)
    transport = RecordingTransport()
    real_load_package = token_factory_module._load_package
    rendezvous = threading.Barrier(2)

    def synchronized_load(path):
        loaded = real_load_package(path)
        rendezvous.wait(timeout=5)
        return loaded

    monkeypatch.setattr(token_factory_module, "_load_package", synchronized_load)

    def invoke():
        try:
            return run_token_factory_package(
                package,
                config(),
                approve_live_transfer=True,
                transport=transport,
            )
        except Exception as exc:  # noqa: BLE001 - the result is asserted below
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: invoke(), range(2)))

    assert len(transport.calls) == 1
    assert sum(isinstance(outcome, FileExistsError) for outcome in outcomes) == 1
    assert sum(not isinstance(outcome, Exception) for outcome in outcomes) == 1


def test_competition_adapter_rejects_a_non_nemotron_model_before_transport(
    tmp_path,
) -> None:
    package = make_package(tmp_path, model_id="meta-llama/Llama-3.3-70B-Instruct")
    transport = RecordingTransport()

    with pytest.raises(PermissionError, match="NVIDIA Nemotron"):
        run_token_factory_package(
            package,
            config(),
            approve_live_transfer=True,
            transport=transport,
        )

    assert transport.calls == []
    assert not (package / TRANSFER_ATTEMPT_FILENAME).exists()


def test_result_verifier_detects_rehashed_request_and_quote_tampering(tmp_path) -> None:
    package = make_package(tmp_path)
    result_path = run_token_factory_package(
        package,
        config(),
        approve_live_transfer=True,
        transport=RecordingTransport(),
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))

    result["provider_log"]["request"]["body"]["temperature"] = 0.5
    result["runtime_evidence"]["request_sha256"] = json_sha256(
        result["provider_log"]["request"]["body"]
    )
    result["runtime_evidence"]["verbatim_log_sha256"] = json_sha256(result["provider_log"])
    result_path.write_text(json.dumps(result), encoding="utf-8")

    request_validation = validate_result_package(package)
    assert request_validation.valid is False
    assert "provider_request_package_mismatch" in request_validation.errors

    result["provider_log"]["request"]["body"]["temperature"] = 0
    tampered_output = result["model_output"]
    tampered_output["answers"][0]["claims"][0]["evidence"][0]["quote"] = "May"
    result["provider_log"]["response"]["body"] = json.loads(successful_body(quote="May"))
    result["runtime_evidence"]["request_sha256"] = json_sha256(
        result["provider_log"]["request"]["body"]
    )
    result["runtime_evidence"]["response_sha256"] = json_sha256(
        result["provider_log"]["response"]["body"]
    )
    result["runtime_evidence"]["verbatim_log_sha256"] = json_sha256(result["provider_log"])
    result_path.write_text(json.dumps(result), encoding="utf-8")

    quote_validation = validate_result_package(package)
    assert quote_validation.valid is False
    assert "locator_quote_invalid" in quote_validation.errors


def test_result_verifier_binds_the_durable_transfer_attempt(tmp_path) -> None:
    package = make_package(tmp_path)
    run_token_factory_package(
        package,
        config(),
        approve_live_transfer=True,
        transport=RecordingTransport(),
    )
    attempt_path = package / TRANSFER_ATTEMPT_FILENAME
    attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
    attempt["endpoint_origin"] = "https://example.org"
    attempt_path.write_text(json.dumps(attempt), encoding="utf-8")

    validation = validate_result_package(package)

    assert validation.valid is False
    assert "transfer_attempt_endpoint_mismatch" in validation.errors


@pytest.mark.parametrize(
    "proof_value,remove_key",
    [(True, False), ("false", False), (0, False), (None, True)],
    ids=["true", "string-false", "integer-zero", "missing"],
)
def test_declared_nemoclaw_metadata_cannot_become_runtime_proof(
    tmp_path, proof_value: object, remove_key: bool
) -> None:
    package = make_package(tmp_path)
    result_path = run_token_factory_package(
        package,
        config(declared_nemoclaw_version="0.1.0-test"),
        approve_live_transfer=True,
        transport=RecordingTransport(),
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if remove_key:
        result["runtime_evidence"].pop("nemoclaw_proof")
    else:
        result["runtime_evidence"]["nemoclaw_proof"] = proof_value
    result_path.write_text(json.dumps(result), encoding="utf-8")

    validation = validate_result_package(package)

    assert validation.valid is False
    assert "nemoclaw_proof_unverified" in validation.errors


def test_result_verifier_labels_legacy_runtime_field_names(tmp_path) -> None:
    package = make_package(tmp_path)
    result_path = run_token_factory_package(
        package,
        config(),
        approve_live_transfer=True,
        transport=RecordingTransport(),
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["runtime_evidence"]["execution_environment"] = result["runtime_evidence"].pop(
        "declared_execution_environment"
    )
    result_path.write_text(json.dumps(result), encoding="utf-8")

    validation = validate_result_package(package)

    assert validation.valid is False
    assert "legacy_runtime_fields_present" in validation.errors


def test_provider_failure_is_truthfully_recorded_but_not_cloud_proof(tmp_path) -> None:
    package = make_package(tmp_path)
    transport = RecordingTransport(
        HTTPExchange(
            status=500,
            headers={"content-type": "application/json"},
            body=json.dumps({"error": {"message": "temporary failure"}}).encode(),
        )
    )

    result_path = run_token_factory_package(
        package,
        config(),
        approve_live_transfer=True,
        transport=transport,
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    validation = validate_result_package(package)

    assert result["status"] == "failed"
    assert result["transfer_performed"] is True
    assert result["cloud_proof"] is False
    assert "provider_http_status:500" in result["errors"]
    assert validation.valid is True


def test_request_carries_only_documented_chat_completion_parameters(tmp_path) -> None:
    package = make_package(tmp_path)
    transport = RecordingTransport()

    run_token_factory_package(
        package,
        config(),
        approve_live_transfer=True,
        transport=transport,
    )

    request = json.loads(transport.calls[0]["body"])

    assert "store" not in request
    # Token Factory: extra_forbidden (live 400, 2026-09-02)
    assert "max_completion_tokens" not in request
    assert set(request) == {
        "max_tokens",
        "messages",
        "model",
        "n",
        "response_format",
        "stream",
        "temperature",
    }


def test_model_catalog_is_confirmed_before_job_content_and_before_the_receipt(
    tmp_path,
) -> None:
    package = make_package(tmp_path)
    attempt_path = package / TRANSFER_ATTEMPT_FILENAME
    observed: list[str] = []

    class OrderedTransport(RecordingTransport):
        def get(self, url, *, headers, timeout_seconds):
            observed.append("catalog_after_receipt" if attempt_path.exists() else "catalog")
            return super().get(url, headers=headers, timeout_seconds=timeout_seconds)

        def post(self, url, *, headers, body, timeout_seconds):
            observed.append("chat")
            return super().post(url, headers=headers, body=body, timeout_seconds=timeout_seconds)

    transport = OrderedTransport()
    result_path = run_token_factory_package(
        package,
        config(),
        approve_live_transfer=True,
        transport=transport,
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))

    assert observed == ["catalog", "chat"]
    assert len(transport.catalog_calls) == 1
    assert transport.catalog_calls[0]["url"] == "https://api.tokenfactory.nebius.com/v1/models"
    assert transport.catalog_calls[0]["headers"]["Authorization"] == (
        "Bearer test-secret-do-not-log"
    )
    assert result["runtime_evidence"]["model_catalog_checked"] is True
    assert validate_result_package(package).valid is True


def test_result_claiming_an_unchecked_catalog_is_rejected(tmp_path) -> None:
    package = make_package(tmp_path)
    result_path = run_token_factory_package(
        package,
        config(),
        approve_live_transfer=True,
        transport=RecordingTransport(),
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["runtime_evidence"]["model_catalog_checked"] = False
    result_path.write_text(json.dumps(result), encoding="utf-8")

    validation = validate_result_package(package)

    assert validation.valid is False
    assert "model_catalog_unverified" in validation.errors


def test_model_missing_from_the_catalog_leaves_the_package_reusable(tmp_path) -> None:
    package = make_package(tmp_path)
    transport = RecordingTransport(catalog=catalog_exchange("nvidia/nemotron-other-model"))

    with pytest.raises(PermissionError, match="not offered by the Token Factory catalog"):
        run_token_factory_package(
            package,
            config(),
            approve_live_transfer=True,
            transport=transport,
        )

    assert transport.calls == []
    assert not (package / TRANSFER_ATTEMPT_FILENAME).exists()
    assert not (package / "result.json").exists()

    retry = RecordingTransport()
    result_path = run_token_factory_package(
        package,
        config(),
        approve_live_transfer=True,
        transport=retry,
    )

    assert json.loads(result_path.read_text(encoding="utf-8"))["status"] == "executed"
    assert len(retry.calls) == 1


@pytest.mark.parametrize(
    "catalog_failure",
    [
        pytest.param(OSError("catalog connection refused"), id="network-error"),
        pytest.param(catalog_exchange(status=401), id="unauthorized"),
        pytest.param(
            HTTPExchange(status=200, headers={}, body=b"<html>not json</html>"),
            id="unreadable-body",
        ),
        pytest.param(
            HTTPExchange(status=200, headers={}, body=json.dumps({"data": []}).encode()),
            id="empty-catalog",
        ),
    ],
)
def test_catalog_failure_aborts_without_a_receipt(tmp_path, catalog_failure) -> None:
    package = make_package(tmp_path)

    class FailingCatalogTransport(RecordingTransport):
        def get(self, url, *, headers, timeout_seconds):
            self.catalog_calls.append({"url": url})
            if isinstance(catalog_failure, OSError):
                raise catalog_failure
            return catalog_failure

    transport = FailingCatalogTransport()
    with pytest.raises(RuntimeError, match="catalog"):
        run_token_factory_package(
            package,
            config(),
            approve_live_transfer=True,
            transport=transport,
        )

    assert len(transport.catalog_calls) == 1
    assert transport.calls == []
    assert not (package / TRANSFER_ATTEMPT_FILENAME).exists()
    assert not (package / "result.json").exists()


def test_chunk_reuse_across_receipts_is_expected_not_duplicate() -> None:
    from nemofold.live_result import validate_model_output

    chunk = {
        "chunk_id": "src_a:000000",
        "source_id": "src_a",
        "text": "Der Zeuge stand am Kiosk.",
        "char_start": 0,
        "char_end": 25,
        "line_start": 1,
        "line_end": 1,
        "page_start": None,
        "page_end": None,
    }
    job = {
        "questions": ["Frage eins?", "Frage zwei?"],
        "sources": [{"source_id": "src_a"}],
    }
    receipts = [
        {"question": "Frage eins?", "chunks": [chunk]},
        {"question": "Frage zwei?", "chunks": [dict(chunk)]},
    ]
    output = {
        "answers": [
            {
                "question": "Frage eins?",
                "status": "insufficient_evidence",
                "claims": [],
            },
            {
                "question": "Frage zwei?",
                "status": "insufficient_evidence",
                "claims": [],
            },
        ],
        "read_source_ids": ["src_a"],
    }

    shared = validate_model_output(job, receipts, output)
    assert "chunk_id_invalid_or_duplicate" not in shared

    within = validate_model_output(
        job, [{"question": "Frage eins?", "chunks": [chunk, dict(chunk)]}], output
    )
    assert "chunk_id_invalid_or_duplicate" in within

    twisted = dict(chunk)
    twisted["text"] = "Ein anderer Text unter derselben ID."
    conflicting = validate_model_output(
        job,
        [
            {"question": "Frage eins?", "chunks": [chunk]},
            {"question": "Frage zwei?", "chunks": [twisted]},
        ],
        output,
    )
    assert "chunk_id_invalid_or_duplicate" in conflicting
