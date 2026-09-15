import asyncio
from app.config import settings
from app.providers.vectordb.chromadb import ChromaDBProvider
from app.providers.embeddings.huggingface import HuggingFaceEmbeddingProvider

async def main():
    emb = HuggingFaceEmbeddingProvider(settings.HUGGINGFACE_MODEL)
    vectordb = ChromaDBProvider(settings.CHROMA_PERSIST_DIR)
    
    query = "What happens if a student is caught copying?"
    sq = await emb.embed_texts([query])
    sq = sq[0]
    
    res = await vectordb.search("vnr", sq, top_k=5)
    print("--- RAW RETRIEVED CHUNKS ---")
    for idx, c in enumerate(res):
        print(f"\nChunk {idx+1} (Score: {c['score']}):")
        print(c['text'])
        print("-" * 40)

if __name__ == "__main__":
    asyncio.run(main())
