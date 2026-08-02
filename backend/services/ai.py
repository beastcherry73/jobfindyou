import os
from flask import current_app


class GroqError(Exception):
    """Raised when the Groq AI service cannot produce a response."""


def call_groq(prompt, max_tokens=3000):
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

    models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "gemma2-9b-it"]
    last_rate_limit = None
    for m in models:
        try:
            response = groq_client.chat.completions.create(
                model=m,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=max_tokens,
                timeout=40.0,
            )
            content = response.choices[0].message.content
            if content is None:
                raise GroqError(f"Groq model {m} returned an empty response.")
            return content
        except GroqError:
            raise
        except Exception as m_err:
            if "rate_limit" in str(m_err).lower() or "429" in str(m_err):
                current_app.logger.warning(f"Groq Model {m} rate limited, falling back to next model...")
                last_rate_limit = m_err
                continue
            current_app.logger.error(f"Groq Model {m} failed: {m_err}")
            raise GroqError(f"Groq API error: {m_err}")

    current_app.logger.error("All Groq models rate limited or unavailable.")
    raise GroqError(f"All Groq models are rate limited: {last_rate_limit}")
