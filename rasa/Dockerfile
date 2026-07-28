FROM python:3.9-slim

WORKDIR /app

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

# Dépendances système de base
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Installation des dépendances Python
COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade "pip<24" "setuptools<70" wheel && \
    pip install -r /tmp/requirements.txt

# Téléchargement du modèle de langue français SpaCy
RUN python -m spacy download fr_core_news_md

# Copie du code source dans le conteneur
COPY . /app

# Entraînement du modèle NLU Rasa
RUN python -m rasa train nlu --config config.yml --nlu data --out models

# Exposition du port Rasa
EXPOSE 5005

# Lancement du serveur d'API Rasa
CMD ["python", "-m", "rasa", "run", "--enable-api", "--port", "5005", "--debug"]