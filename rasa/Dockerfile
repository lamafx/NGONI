FROM rasa/rasa:3.6.20 AS trainer

WORKDIR /app

USER root

COPY . /app

RUN rasa train

FROM rasa/rasa:3.6.20

WORKDIR /app

USER root

# CamemBERT (LanguageModelFeaturizer, config-embedding-experiment.yml)
# abandonne formellement le 2026-07-23 : gain mesure +1.2pt d'accuracy
# globale sur le corpus adversarial (16.8), pour un cout de latence ~15-20x
# (0.05-0.07s -> ~0.95s par appel /model/parse) juge disproportionne pour un
# assistant conversationnel temps reel, sans regler le desequilibre de fond
# diagnostic/ask_faq (387 vs 210 exemples). transformers/sentencepiece
# retires en consequence -- config.yml (pipeline reellement servi) ne les a
# jamais references, seul config-embedding-experiment.yml en a besoin,
# conserve pour reference avec les modeles associes (models/experiments/).

COPY . /app
COPY --from=trainer /app/models /app/models

CMD ["run", "--enable-api", "--port", "5005"]