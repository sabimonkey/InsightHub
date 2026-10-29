from dataclasses import dataclass, field


@dataclass
class LLMRequest:
    system_prompt: str
    user_content: str
    response_schema: dict | None = None
    temperature: float = 0
    max_output_tokens: int = 1200
    metadata: dict = field(default_factory=dict)


@dataclass
class LLMResponse:
    text: str
    structured_data: dict | None
    model: str
    provider: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    latency_ms: int
    finish_reason: str | None
    raw_response_metadata: dict = field(default_factory=dict)


class LLMError(Exception):
    def __init__(self, code: str, message: str, *, diagnostics: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.diagnostics = diagnostics or {}
