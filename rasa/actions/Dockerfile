FROM rasa/rasa-sdk:3.6.2

USER root
WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

CMD ["start", "--actions", "actions"]