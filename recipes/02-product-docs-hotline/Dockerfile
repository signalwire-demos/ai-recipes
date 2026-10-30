FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=3000 \
    HF_HOME=/opt/hf NLTK_DATA=/opt/nltk_data
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Bake the query embedding model and NLTK data into the image, so the first call
# doesn't wait on a download (and the container can run without internet access).
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')" \
 && python -m nltk.downloader -q -d /opt/nltk_data averaged_perceptron_tagger_eng punkt_tab wordnet stopwords

COPY . .
RUN useradd --create-home app && chown -R app /app
USER app

EXPOSE 3000
CMD ["python", "app.py"]
