from rag import retrieve_policy

question = input("Ask: ")

context = retrieve_policy(question)

print("\nRetrieved Context:\n")
print(context)