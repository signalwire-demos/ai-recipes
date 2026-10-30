# Local document search

The native vector search skill answers questions from your own documents. It searches a local index file with the `.swsearch` extension, so no outside service is involved.

## Building an index

Install the search extra, then point `sw-search` at a folder of documents:

```bash
pip install "signalwire-sdk[search]"
sw-search ./docs --output data/knowledge.swsearch --chunking-strategy markdown
sw-search validate data/knowledge.swsearch
sw-search search data/knowledge.swsearch "how do I buy a number"
```

The build splits each document into chunks and stores an embedding for each chunk. The first build downloads a small embedding model. The markdown chunking strategy keeps headings and code blocks together.

## Searching

Each search combines vector similarity with keyword matching. The skill's `similarity_threshold` drops results that score too low, and `count` limits how many results come back. When nothing passes the threshold, the skill returns its `no_results_message`.

Rebuild the index whenever the documents change. The index is a single SQLite file, so you can commit it or ship it in a container image.

For larger sets of documents, the skill can also use a PostgreSQL database with pgvector, or a remote search server.
