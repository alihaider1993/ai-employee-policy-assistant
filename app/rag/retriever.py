from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery

from app.ai.embeddings import embeddings
from app.core.config import settings


search_client = SearchClient(
    endpoint=settings.azure_search_endpoint,
    index_name=settings.azure_search_index,
    credential=AzureKeyCredential(settings.azure_search_api_key),
)

def retrieve_policy_chunks(question: str, top_k: int = 3):
    question_vector = embeddings.embed_query(question)

    vector_query = VectorizedQuery(
        vector=question_vector,
        k_nearest_neighbors=top_k,
        fields="content_vector",
    )

    results = search_client.search(
        search_text=None,
        vector_queries=[vector_query],
        select=["content", "source", "page"],
        top=top_k,
    )

    return list(results)

if __name__ == "__main__":
    results = retrieve_policy_chunks(
        "Can I carry unused annual leave into the next year?"
    )

    for result in results:
        print("\n--- RESULT ---")
        print("Source:", result["source"])
        print("Page:", result["page"])
        print("Content:")
        print(result["content"])