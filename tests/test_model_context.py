from __future__ import annotations

import io
import json
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from vlog_director.cli import main
from vlog_director.model_context import (
    ModelContextLimitError,
    build_reference_context_packet,
    build_responses_request,
    dispatch_model_request,
    dispatch_responses_request,
    serialize_model_request,
    serialized_model_request_size,
    validate_serialized_model_request,
    write_reference_context_packet,
)


class _ByteLimitGatewayHandler(BaseHTTPRequestHandler):
    byte_limit = 512
    request_count = 0

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        type(self).request_count += 1
        content_length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(content_length)
        self.send_response(413 if content_length >= self.byte_limit else 200)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


class ModelContextTests(unittest.TestCase):
    def test_strict_200k_utf8_byte_boundary(self) -> None:
        result = validate_serialized_model_request("x" * 199_999)
        self.assertIsNone(result)
        size = serialized_model_request_size("x" * 199_999)
        self.assertEqual(size["serialized_utf8_bytes"], 199_999)
        with self.assertRaisesRegex(ModelContextLimitError, "200,000 UTF-8 bytes"):
            validate_serialized_model_request("x" * 200_000)

    def test_multibyte_text_is_checked_by_utf8_bytes_not_characters(self) -> None:
        below = "汉" * 66_666
        above = below + "汉"
        self.assertEqual(len(below), 66_666)
        self.assertEqual(len(below.encode("utf-8")), 199_998)
        validate_serialized_model_request(below)
        with self.assertRaises(ModelContextLimitError):
            validate_serialized_model_request(above)

    def test_legacy_character_keyword_is_a_safe_byte_alias(self) -> None:
        with self.assertWarns(DeprecationWarning):
            self.assertIsNone(
                validate_serialized_model_request(
                    "x" * 511,
                    max_characters=512,
                )
            )
        with self.assertWarns(DeprecationWarning), self.assertRaises(
            ModelContextLimitError
        ):
            serialize_model_request(
                {"input": "汉" * 200},
                max_characters=512,
            )
        calls: list[str] = []
        with self.assertWarns(DeprecationWarning):
            result = dispatch_model_request(
                {"input": "small"},
                lambda body: calls.append(body) or "sent",
                max_characters=512,
            )
        self.assertEqual(result, "sent")
        self.assertEqual(len(calls), 1)
        with self.assertRaisesRegex(ValueError, "not both"):
            validate_serialized_model_request(
                "small",
                max_bytes=512,
                max_characters=512,
            )

    def test_complete_responses_envelope_is_checked_before_transport(self) -> None:
        calls: list[bytes] = []

        def transport(serialized: bytes) -> str:
            calls.append(serialized)
            return "sent"

        content = "x" * 199_950
        self.assertLess(len(content), 200_000)
        with self.assertRaises(ModelContextLimitError):
            dispatch_responses_request(
                "test-model",
                content,
                transport,
                instructions="review the complete evidence packet",
                tools=[{"type": "function", "name": "record_study"}],
            )
        self.assertEqual(calls, [])
        self.assertEqual(
            dispatch_responses_request("test-model", "small", transport),
            "sent",
        )
        self.assertEqual(
            calls,
            [
                serialize_model_request(
                    {"model": "test-model", "input": "small"}
                ).encode("utf-8")
            ],
        )

    def test_responses_builder_keeps_protocol_fields_in_one_envelope(self) -> None:
        payload = build_responses_request(
            "test-model",
            [{"role": "user", "content": "分析完整视频"}],
            instructions="Use only supplied evidence.",
            tools=[{"type": "function", "name": "record_study"}],
            request_options={"max_output_tokens": 1024},
        )
        self.assertEqual(
            set(payload),
            {"model", "instructions", "input", "tools", "max_output_tokens"},
        )
        with self.assertRaisesRegex(ValueError, "reserved fields"):
            build_responses_request(
                "test-model",
                "input",
                request_options={"model": "forged-model"},
            )
        with self.assertRaisesRegex(ValueError, "options must be an object"):
            build_responses_request(
                "test-model",
                "input",
                request_options=[],  # type: ignore[arg-type]
            )
        with self.assertRaises(ValueError):
            serialize_model_request({"input": float("nan")})
        with self.assertRaisesRegex(ValueError, "model"):
            build_responses_request("", "input")
        with self.assertRaisesRegex(ValueError, "input"):
            build_responses_request("test-model", None)
        for invalid_input in (False, 123, {}):
            with self.subTest(invalid_input=invalid_input), self.assertRaisesRegex(
                ValueError, "input must"
            ):
                build_responses_request("test-model", invalid_input)
        with self.assertRaisesRegex(ValueError, "input list items"):
            build_responses_request("test-model", ["not-an-input-item"])
        with self.assertRaisesRegex(ValueError, "tool entries"):
            build_responses_request(
                "test-model",
                "input",
                tools=[123],  # type: ignore[list-item]
            )
        with self.assertRaisesRegex(ValueError, "tool entries"):
            build_responses_request("test-model", "input", tools=[{}])
        with self.assertRaisesRegex(ValueError, "credential fields"):
            build_responses_request(
                "test-model",
                "input",
                request_options={
                    "headers": {"Authorization": "placeholder"},
                    "metadata": {"refresh_token": "placeholder"},
                },
            )

    def test_local_gateway_413_is_prevented_before_http_transport(self) -> None:
        _ByteLimitGatewayHandler.request_count = 0
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            _ByteLimitGatewayHandler,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/responses"

        def transport(serialized: bytes) -> int:
            request = Request(
                url,
                data=serialized,
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=3) as response:
                    return response.status
            except HTTPError as error:
                return error.code

        try:
            oversized_payload = build_responses_request(
                "test-model",
                "汉" * 200,
            )
            oversized_serialized = json.dumps(
                oversized_payload,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            oversized_size = serialized_model_request_size(oversized_serialized)
            self.assertLess(oversized_size["serialized_characters"], 512)
            self.assertGreaterEqual(oversized_size["serialized_utf8_bytes"], 512)

            with self.assertRaises(ModelContextLimitError):
                dispatch_responses_request(
                    "test-model",
                    "汉" * 200,
                    transport,
                    max_bytes=512,
                )
            self.assertEqual(_ByteLimitGatewayHandler.request_count, 0)

            self.assertEqual(transport(oversized_serialized.encode("utf-8")), 413)
            self.assertEqual(_ByteLimitGatewayHandler.request_count, 1)
            self.assertEqual(
                dispatch_responses_request(
                    "test-model",
                    "small request",
                    transport,
                    max_bytes=512,
                ),
                200,
            )
            self.assertEqual(_ByteLimitGatewayHandler.request_count, 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_reference_packet_is_compacted_below_character_and_byte_limits(self) -> None:
        segments = [
            {
                "start_sec": index * 30,
                "end_sec": index * 30 + 20,
                "text": ("叙事文本 " * 90) + str(index),
            }
            for index in range(500)
        ]
        shots = [
            {
                "shot_id": f"shot-{index:04d}",
                "start_sec": index * 3,
                "end_sec": index * 3 + 3,
                "duration_sec": 3,
                "role": "reaction" if index % 20 == 0 else "action",
                "recommendation": "protect",
                "keep_score": 0.9,
                "speech_ratio": 0.4,
                "visual": {
                    "motion": 0.1,
                    "brightness": 0.5,
                    "sharpness": 0.12,
                },
                "audio": {"kind": "speech", "rms": 0.08},
            }
            for index in range(800)
        ]
        analysis = {
            "source": {
                "source_id": "source-a",
                "url": "https://example.com/a",
                "media_path": "should-not-be-exported.mp4",
            },
            "configuration": {},
            "media": {"duration_sec": 2400},
            "transcription": {
                "status": "ready",
                "provider": "test",
                "segments": segments,
                "words": [{}] * 1000,
            },
            "shots": shots,
            "events": [],
            "audio_segments": [],
            "learning_summary": {},
        }
        packet = build_reference_context_packet(
            analysis,
            max_characters=60_000,
        )
        serialized = json.dumps(packet, ensure_ascii=False, indent=2)
        size = serialized_model_request_size(serialized)
        self.assertLess(size["serialized_characters"], 60_000)
        self.assertLess(size["serialized_utf8_bytes"], 200_000)
        self.assertEqual(
            packet["context_budget"]["serialized_characters"],
            size["serialized_characters"],
        )
        self.assertEqual(
            packet["context_budget"]["serialized_utf8_bytes"],
            size["serialized_utf8_bytes"],
        )
        self.assertNotIn("media_path", packet["source"])
        self.assertLess(
            len(packet["transcription"]["windows"]),
            len(segments),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "context.json"
            written_characters = write_reference_context_packet(
                packet,
                output_path,
            )
            written_bytes = output_path.read_bytes()
        self.assertFalse(written_bytes.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(written_bytes, serialized.encode("utf-8"))
        self.assertEqual(written_characters, len(serialized))

    def test_unshrinkable_packet_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            ModelContextLimitError,
            "no remaining safe compaction step",
        ):
            build_reference_context_packet(
                {
                    "source": {
                        "source_id": "source-a",
                        "title": "汉" * 10_000,
                    }
                },
                max_characters=10_000,
            )

    def test_preflight_cli_reports_complete_utf8_body_size(self) -> None:
        payload = build_responses_request(
            "test-model",
            "请分析完整证据",
            instructions="Do not infer unsupported causal claims.",
            tools=[{"type": "function", "name": "record_study"}],
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            request_path = Path(temporary_directory) / "request.json"
            exact_body = (
                json.dumps(payload, ensure_ascii=False, indent=2).replace(
                    "\n", "\r\n"
                )
                + "\r\n"
            )
            request_path.write_bytes(exact_body.encode("utf-8"))
            stdout = io.StringIO()
            with patch.object(
                sys,
                "argv",
                [
                    "vlog-director",
                    "preflight-model-request",
                    "--request",
                    str(request_path),
                ],
            ), redirect_stdout(stdout):
                exit_code = main()

        self.assertEqual(exit_code, 0)
        result = json.loads(stdout.getvalue())
        expected = serialized_model_request_size(exact_body)
        self.assertEqual(result["serialized_characters"], expected["serialized_characters"])
        self.assertEqual(result["serialized_utf8_bytes"], expected["serialized_utf8_bytes"])
        self.assertEqual(
            result["body_sha256"],
            sha256(exact_body.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(result["body_binding"], "exact_file_utf8_bytes")
        self.assertEqual(
            result["validation_scope"],
            "byte_limit_and_minimum_responses_structure",
        )
        self.assertEqual(result["maximum_utf8_bytes"], 200_000)

    def test_preflight_cli_rejects_non_responses_or_changed_body(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            request_path = Path(temporary_directory) / "request.json"
            request_path.write_bytes(b"{}")
            with patch.object(
                sys,
                "argv",
                [
                    "vlog-director",
                    "preflight-model-request",
                    "--request",
                    str(request_path),
                ],
            ), self.assertRaisesRegex(ValueError, "model"):
                main()

            request_path.write_bytes(
                b'{"model":"first","model":"second","input":"x"}'
            )
            with patch.object(
                sys,
                "argv",
                [
                    "vlog-director",
                    "preflight-model-request",
                    "--request",
                    str(request_path),
                ],
            ), self.assertRaisesRegex(ValueError, "duplicate JSON field"):
                main()

            request_path.write_bytes(
                b'{"model":"test-model","input":"x","headers":'
                b'{"Authorization":"placeholder"}}'
            )
            with patch.object(
                sys,
                "argv",
                [
                    "vlog-director",
                    "preflight-model-request",
                    "--request",
                    str(request_path),
                ],
            ), self.assertRaisesRegex(ValueError, "credential fields"):
                main()

            payload = {"model": "test-model", "input": "x" * 90}
            compact = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            pretty = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            maximum = len(compact.encode("utf-8")) + 1
            self.assertLess(len(compact.encode("utf-8")), maximum)
            self.assertGreaterEqual(len(pretty.encode("utf-8")), maximum)
            request_path.write_bytes(pretty.encode("utf-8"))
            with patch.object(
                sys,
                "argv",
                [
                    "vlog-director",
                    "preflight-model-request",
                    "--request",
                    str(request_path),
                    "--max-bytes",
                    str(maximum),
                ],
            ), self.assertRaises(ModelContextLimitError):
                main()

            request_path.write_bytes(b"\xef\xbb\xbf" + compact.encode("utf-8"))
            with patch.object(
                sys,
                "argv",
                [
                    "vlog-director",
                    "preflight-model-request",
                    "--request",
                    str(request_path),
                ],
            ), self.assertRaisesRegex(ValueError, "without BOM"):
                main()


if __name__ == "__main__":
    unittest.main()
