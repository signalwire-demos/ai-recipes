# Rebuild the search index after you change anything in docs/.
# Needs the search extra (already in requirements.txt). The first build downloads the
# all-MiniLM-L6-v2 embedding model (about 90 MB).
index:
	sw-search ./docs --output data/knowledge.swsearch --chunking-strategy markdown \
		--min-chunk-size 40 --file-types md
	sw-search validate data/knowledge.swsearch

.PHONY: index
