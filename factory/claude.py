"""Claude API wrapper — uses API key if set, falls back to local CLI."""
import os
import subprocess


def call_claude(prompt: str, max_tokens: int = 2048) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    result = subprocess.run(
        ["claude", "--permission-mode", "bypassPermissions", "--print", prompt],
        capture_output=True, text=True,
    )
    return result.stdout.strip() or result.stderr.strip()
