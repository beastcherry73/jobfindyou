import os
from flask import current_app


class GroqError(Exception):
    """Raised when the Groq AI service cannot produce a response."""


def call_groq(prompt, max_tokens=6000):
    """Call Groq and return the raw model output.

    Raises GroqError on any failure so callers fail loudly instead of
    silently returning a fabricated analysis.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        current_app.logger.warning("GROQ_API_KEY is not set.")
        raise GroqError("GROQ_API_KEY is not set. Configure it before using AI features.")

    groq_client = current_app.config.get("GROQ_CLIENT")
    if not groq_client:
        try:
            from groq import Groq
            groq_client = Groq(api_key=api_key, timeout=40.0, max_retries=1)
        except Exception as client_err:
            current_app.logger.error(f"Failed to initialize Groq client: {client_err}")
            raise GroqError("AI service is misconfigured.")

    models = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    last_err = None
    for m in models:
        try:
            response = groq_client.chat.completions.create(
                model=m,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=max_tokens,
                timeout=40.0,
                reasoning_effort="low",
            )
            content = response.choices[0].message.content
            if not content:
                current_app.logger.warning(f"Groq model {m} returned an empty response, trying next model...")
                last_err = GroqError(f"Groq model {m} returned an empty response.")
                continue
            return content
        except Exception as m_err:
            current_app.logger.warning(f"Groq model {m} failed ({m_err}), trying next model...")
            last_err = m_err
            continue

    current_app.logger.error(f"All Groq models failed or are unavailable: {last_err}")
    raise GroqError(f"All Groq models are unavailable: {last_err}")
