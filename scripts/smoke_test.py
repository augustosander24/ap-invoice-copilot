"""Send one short prompt to the configured model and print the reply."""

from langchain_ollama import ChatOllama

from ap_copilot.config import OLLAMA_HOST, get_model


def main() -> None:
    model = get_model("communicator")
    chat = ChatOllama(model=model, base_url=OLLAMA_HOST)
    reply = chat.invoke("Reply with the single word: ready")
    print(f"model: {model}")
    print(f"reply: {reply.text}")


if __name__ == "__main__":
    main()
