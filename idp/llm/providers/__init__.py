# Copyright (c) 2026, Sanjay Kumar and contributors
# For license information, please see license.txt

"""Built-in LLM provider adapters.

Importing this package triggers registration of the shipped providers
(openai, anthropic, ollama) via the :func:`register_provider` decorator.
"""

# Importing the modules registers the provider classes with the registry.
from idp.llm.providers import (
	anthropic_provider,
	ollama_provider,
	openai_provider,
)
