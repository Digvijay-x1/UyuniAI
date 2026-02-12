from langchain_huggingface import HuggingFaceEndpoint, ChatHuggingFace

llm_model = HuggingFaceEndpoint(
    repo_id="Qwen/Qwen2.5-7B-Instruct",
    huggingfacehub_api_token="",
    task="text-generation",
    max_new_tokens=64,
)


llm = ChatHuggingFace(llm=llm_model)
response = llm.invoke("What is OSPF?")
print(response)


