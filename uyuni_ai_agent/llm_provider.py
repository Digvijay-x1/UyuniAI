import os


def get_llm(config):
    """Return a configured LangChain chat LLM based on the passed config.

    Supports: huggingface, google_genai, openai, tokenrouter.
    The API key is read from config["llm"]["api_key"] (populated from the
    LLM_API_KEY env var by load_config()) with an env fallback.

    This function stays synchronous on purpose: chat-model constructors are
    sync, and every returned class supports async invocation (ainvoke)
    natively. If the "huggingface" provider is ever used and ainvoke is
    unsupported by the installed langchain-huggingface version, fall back to
    asyncio.to_thread(llm.invoke, ...) at the call site (investigate).
    """
    provider = config["llm"]["provider"]
    model = config["llm"]["model"]
    api_key = config["llm"].get("api_key", os.environ.get("LLM_API_KEY", ""))

    if provider == "huggingface":
        from langchain_huggingface import HuggingFaceEndpoint, ChatHuggingFace
        llm_model = HuggingFaceEndpoint(
            repo_id=model,
            huggingfacehub_api_token=api_key,
            task="text-generation",
            max_new_tokens=512,
        )
        return ChatHuggingFace(llm=llm_model)

    elif provider == "google_genai":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
        )

    elif provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=api_key,
        )
    elif provider == "tokenrouter":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url="https://api.tokenrouter.com/v1",
        )
    # If we wanted to support more providers in the future, we could add more branches here.
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
