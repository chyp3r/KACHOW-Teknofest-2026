import asyncio
import os
import sys

# Add backend directory to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.ai.llms import get_llm_client


async def main():
    print("==================================================")
    print("   AI Core & Local Ollama Integration Test")
    print("==================================================")

    # Set defaults if not already present in environment
    if "OLLAMA_BASE_URL" not in os.environ:
        os.environ["OLLAMA_BASE_URL"] = "http://localhost:11434"
    if "OLLAMA_MODEL" not in os.environ:
        os.environ["OLLAMA_MODEL"] = "qwen3.5:9b"

    try:
        client = get_llm_client(provider="ollama")
        print(
            f"Configured Client: base_url={client.base_url}, model={client.model_name}\n"
        )

        prompt = "Hello! Please say 'KACHOW!' in a friendly tone and confirm you are Qwen."
        print(f"Sending prompt: '{prompt}'")

        print("\n--- Testing Generate (Awaiting response...) ---")
        response = await client.generate_text(prompt=prompt)
        print(f"Response:\n{response}")

        print("\n--- Testing Stream (Streaming response...) ---")
        print("Response: ", end="", flush=True)
        async for chunk in client.stream_text(prompt=prompt):
            print(chunk, end="", flush=True)
        print("\n")

        print("==================================================")
        print("✅ Integration test completed successfully!")
        print("==================================================")
    except Exception as e:
        print("\n❌ Error running integration test:")
        print(e)
        print("\nEnsure that:")
        print("1. Local Ollama is running at http://localhost:11434")
        print("2. 'qwen3.5:9b' model is pulled ('ollama pull qwen3.5:9b')")
        print("==================================================")


if __name__ == "__main__":
    asyncio.run(main())
