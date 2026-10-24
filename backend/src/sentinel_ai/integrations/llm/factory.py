"""Builds the application's gateway from settings (used by workflows from Step 4 on)."""

from sqlalchemy.orm import Session, sessionmaker

from sentinel_ai.core.config import Settings
from sentinel_ai.integrations.llm.gateway import GatewayConfig, LLMGateway
from sentinel_ai.integrations.llm.gemini import GeminiProvider
from sentinel_ai.integrations.llm.redaction import PromptRedactor


def build_gateway(settings: Settings, session_factory: sessionmaker[Session]) -> LLMGateway:
    """No API key or no model name -> a disabled gateway (workflows degrade with
    ``llm_disabled``). The redactor always knows every configured secret, key included."""
    enabled = settings.gemini_api_key is not None and bool(settings.gemini_model)
    provider = (
        GeminiProvider(settings.gemini_api_key) if enabled and settings.gemini_api_key else None
    )
    return LLMGateway(
        provider=provider,
        redactor=PromptRedactor.from_settings(settings),
        session_factory=session_factory,
        config=GatewayConfig.from_settings(settings),
    )
