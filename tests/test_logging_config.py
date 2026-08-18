import io
import json
import logging
import unittest

from app.logging_config import (
    ContextFilter,
    JsonFormatter,
    bind_conversation_id,
    bind_request_id,
    log_event,
    reset_conversation_id,
    reset_request_id,
)


class LoggingConfigTests(unittest.TestCase):
    def test_json_log_has_context_and_redacts_secrets(self) -> None:
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(ContextFilter())
        handler.setFormatter(JsonFormatter())
        logger = logging.getLogger("tests.safe_logging")
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.INFO)

        request_token = bind_request_id("req-123")
        conversation_token = bind_conversation_id("conv-456")
        try:
            log_event(
                logger,
                logging.INFO,
                "security.redaction.test",
                "Bearer abc-secret and sk-example123456",
                api_key="sk-another123456",
                count=2,
            )
        finally:
            reset_conversation_id(conversation_token)
            reset_request_id(request_token)

        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["event"], "security.redaction.test")
        self.assertEqual(payload["request_id"], "req-123")
        self.assertEqual(payload["conversation_id"], "conv-456")
        self.assertEqual(payload["details"]["count"], 2)
        serialized = stream.getvalue()
        self.assertNotIn("abc-secret", serialized)
        self.assertNotIn("example123456", serialized)
        self.assertNotIn("another123456", serialized)


if __name__ == "__main__":
    unittest.main()
