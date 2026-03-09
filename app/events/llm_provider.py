"""
LLM abstraction interface for event extraction.
Provides a pluggable interface for different LLM providers.
"""
import httpx
import json
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from datetime import datetime

from app.core.config import settings


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str = None) -> str:
        """Generate a response from the LLM."""
        pass

    @abstractmethod
    async def generate_json(self, prompt: str, system_prompt: str = None) -> Dict[str, Any]:
        """Generate a JSON response from the LLM."""
        pass


class OpenAIProvider(LLMProvider):
    """OpenAI API provider."""

    def __init__(
        self,
        api_key: str = None,
        model: str = None,
        api_url: str = None,
        max_tokens: int = None,
        temperature: float = None
    ):
        self.api_key = api_key or settings.LLM_API_KEY
        self.model = model or settings.LLM_MODEL
        self.api_url = api_url or settings.LLM_API_URL or "https://api.openai.com/v1/chat/completions"
        self.max_tokens = max_tokens or settings.LLM_MAX_TOKENS
        self.temperature = temperature if temperature is not None else settings.LLM_TEMPERATURE

    async def generate(self, prompt: str, system_prompt: str = None) -> str:
        """Generate a response from OpenAI."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.api_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": self.max_tokens,
                    "temperature": self.temperature,
                },
                timeout=60.0,
            )

        if response.status_code != 200:
            raise Exception(f"OpenAI API error: {response.text}")

        data = response.json()
        return data["choices"][0]["message"]["content"]

    async def generate_json(self, prompt: str, system_prompt: str = None) -> Dict[str, Any]:
        """Generate a JSON response from OpenAI."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.api_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": self.max_tokens,
                    "temperature": self.temperature,
                    "response_format": {"type": "json_object"},
                },
                timeout=60.0,
            )

        if response.status_code != 200:
            raise Exception(f"OpenAI API error: {response.text}")

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            raise Exception(f"Failed to parse JSON response: {content}")


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API provider."""

    def __init__(
        self,
        api_key: str = None,
        model: str = None,
        api_url: str = None,
        max_tokens: int = None,
        temperature: float = None
    ):
        self.api_key = api_key or settings.LLM_API_KEY
        self.model = model or "claude-3-sonnet-20240229"
        self.api_url = api_url or settings.LLM_API_URL or "https://api.anthropic.com/v1/messages"
        self.max_tokens = max_tokens or settings.LLM_MAX_TOKENS
        self.temperature = temperature if temperature is not None else settings.LLM_TEMPERATURE

    async def generate(self, prompt: str, system_prompt: str = None) -> str:
        """Generate a response from Anthropic."""
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            body["system"] = system_prompt

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.api_url,
                headers=headers,
                json=body,
                timeout=60.0,
            )

        if response.status_code != 200:
            raise Exception(f"Anthropic API error: {response.text}")

        data = response.json()
        return data["content"][0]["text"]

    async def generate_json(self, prompt: str, system_prompt: str = None) -> Dict[str, Any]:
        """Generate a JSON response from Anthropic."""
        # Add JSON instruction to prompt
        json_prompt = f"{prompt}\n\nRespond with valid JSON only. No other text."
        content = await self.generate(json_prompt, system_prompt)
        
        try:
            # Try to extract JSON from response
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            return json.loads(content.strip())
        except json.JSONDecodeError:
            raise Exception(f"Failed to parse JSON response: {content}")


class MockLLMProvider(LLMProvider):
    """Mock LLM provider for testing."""

    async def generate(self, prompt: str, system_prompt: str = None) -> str:
        return "Mock response"

    async def generate_json(self, prompt: str, system_prompt: str = None) -> Dict[str, Any]:
        return {"is_event": False, "reason": "Mock response"}


def get_llm_provider(provider_type: str = None, **kwargs) -> LLMProvider:
    """Factory function to get the appropriate LLM provider."""
    provider_type = provider_type or settings.LLM_PROVIDER
    
    providers = {
        "openai": OpenAIProvider,
        "anthropic": AnthropicProvider,
        "mock": MockLLMProvider,
    }
    
    provider_class = providers.get(provider_type.lower())
    if not provider_class:
        raise ValueError(f"Unknown LLM provider: {provider_type}")
    
    return provider_class(**kwargs)


# Convenience function for the abstraction
async def call_llm(prompt: str, system_prompt: str = None, provider: LLMProvider = None) -> str:
    """
    Call LLM with a prompt and return the response.
    This is the main abstraction for LLM calls.
    """
    if provider is None:
        provider = get_llm_provider()
    
    return await provider.generate(prompt, system_prompt)


async def call_llm_json(prompt: str, system_prompt: str = None, provider: LLMProvider = None) -> Dict[str, Any]:
    """
    Call LLM with a prompt and return a JSON response.
    """
    if provider is None:
        provider = get_llm_provider()
    
    return await provider.generate_json(prompt, system_prompt)
