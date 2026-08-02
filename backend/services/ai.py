import os
from flask import current_app


def call_groq(prompt, max_tokens=3000):
    try:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            current_app.logger.warning("GROQ_API_KEY is not set.")
            return "{}"
        groq_client = current_app.config.get("GROQ_CLIENT")
        if not groq_client:
            from groq import Groq
            groq_client = Groq(api_key=api_key)

        models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]
        for m in models:
            try:
                response = groq_client.chat.completions.create(
                    model=m,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.4,
                    max_tokens=max_tokens,
                )
                return response.choices[0].message.content
            except Exception as m_err:
                if "rate_limit" in str(m_err).lower() or "429" in str(m_err):
                    current_app.logger.warning(f"Groq Model {m} rate limited, falling back to next model...")
                    continue
                raise m_err
        return "{}"
    except Exception as groq_err:
        current_app.logger.error(f"Groq API Error: {groq_err}")
        return "{}"
