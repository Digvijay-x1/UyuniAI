import os
from uyuni_ai_agent.config import load_config


def get_llm():
    """Return a configured LangChain chat LLM based on settings.yaml.
    Supports: huggingface, google_genai, openai.
    API key is read from the LLM_API_KEY environment variable.
    """
    config = load_config()
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

    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
