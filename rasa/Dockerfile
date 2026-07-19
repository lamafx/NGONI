FROM rasa/rasa:3.6.20 AS trainer

WORKDIR /app

USER root

COPY . /app

RUN rasa train

FROM rasa/rasa:3.6.20

WORKDIR /app

USER root

COPY . /app
COPY --from=trainer /app/models /app/models

CMD ["run", "--enable-api", "--port", "5005"]