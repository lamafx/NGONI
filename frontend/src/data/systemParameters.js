// Valeurs par defaut = ce qui est REELLEMENT en dur dans le backend a ce
// jour (chaque `source` pointe le fichier/constante exacts, verifies dans
// le depot -- pas une estimation). Modifiables depuis AdminSettingsPage,
// mais persistees UNIQUEMENT dans DemoStore/localStorage (voir
// state/DemoStore.jsx, action UPDATE_PARAMETER) -- aucune route backend ne
// permet encore d'ecrire ces constantes (voir api_admin_a_developper.md).
// Modifier une valeur ici ne change donc rien au comportement reel de Rasa/
// FastAPI tant que ce pont n'existe pas ; c'est explique dans le bandeau de
// la page.
export const SYSTEM_PARAMETERS = [
  {
    group: "Compréhension (NLU)",
    description:
      "Décide si un message est compris avec assez de confiance, ou si l'agent doit demander de reformuler / transmettre à un conseiller.",
    items: [
      {
        id: "nlu.confidence_threshold",
        label: "Confiance minimale acceptée",
        value: 0.7,
        format: "pct",
        step: 0.01,
        source: "rasa/config.yml — FallbackClassifier.threshold",
      },
      {
        id: "nlu.ambiguity_threshold",
        label: "Écart minimal entre deux intentions proches",
        value: 0.08,
        format: "pct",
        step: 0.01,
        source: "rasa/config.yml — FallbackClassifier.ambiguity_threshold",
      },
    ],
  },
  {
    group: "Recherche FAQ",
    description: "Contrôle quand une question obtient une réponse directe, une suggestion, ou aucune réponse.",
    items: [
      {
        id: "faq.default_threshold",
        label: "Similarité pour une réponse directe",
        value: 0.57,
        format: "pct",
        step: 0.01,
        source: "fastapi/app/domains/faq/service.py — DEFAULT_THRESHOLD",
      },
      {
        id: "faq.secondary_threshold",
        label: "Similarité pour une suggestion (« vouliez-vous dire… »)",
        value: 0.42,
        format: "pct",
        step: 0.01,
        source: "fastapi/app/domains/faq/service.py — SECONDARY_THRESHOLD",
      },
      {
        id: "faq.keyword_boost",
        label: "Bonus par mot-clé exact retrouvé",
        value: 0.02,
        format: "pct",
        step: 0.01,
        source: "fastapi/app/domains/faq/service.py — KEYWORD_BOOST_PER_MATCH",
      },
    ],
  },
  {
    group: "Diagnostic",
    description: "Seuils de similarité utilisés pour rattacher un message au bon problème du Capability Registry.",
    items: [
      {
        id: "diagnostic.min_embedding_similarity",
        label: "Similarité minimale (classification directe)",
        value: 0.55,
        format: "pct",
        step: 0.01,
        source: "rasa/actions/diagnostic.py — MIN_EMBEDDING_SIMILARITY",
      },
      {
        id: "diagnostic.keyword_rescue_similarity",
        label: "Similarité minimale (repêchage par mot-clé)",
        value: 0.45,
        format: "pct",
        step: 0.01,
        source: "rasa/actions/diagnostic.py — KEYWORD_RESCUE_MIN_EMBEDDING_SIMILARITY",
      },
    ],
  },
  {
    group: "Réclamation",
    description: "Reconnaissance des réponses de l'utilisateur pendant le formulaire guidé de réclamation.",
    items: [
      {
        id: "reclamation.field_similarity",
        label: "Similarité minimale pour reconnaître un champ",
        value: 0.9,
        format: "pct",
        step: 0.01,
        source: "rasa/actions/reclamation.py — MIN_FIELD_SEMANTIC_SIMILARITY",
      },
    ],
  },
  {
    group: "Fiabilité & résilience",
    description: "Protège le système contre un microservice en panne ou un usage abusif.",
    items: [
      {
        id: "reclamation.failure_threshold",
        label: "Échecs consécutifs avant coupure (réclamation)",
        value: 3,
        format: "count",
        step: 1,
        source: "rasa/actions/reclamation.py — FAILURE_THRESHOLD",
      },
      {
        id: "reclamation.cooldown_seconds",
        label: "Délai avant nouvel essai (réclamation)",
        value: 30,
        format: "seconds",
        step: 5,
        source: "rasa/actions/reclamation.py — COOLDOWN_SECONDS",
      },
      {
        id: "diagnostic.circuit_breaker_failure_threshold",
        label: "Échecs consécutifs avant coupure (diagnostic)",
        value: 3,
        format: "count",
        step: 1,
        source: "fastapi/app/domains/diagnostic/adapter.py — CIRCUIT_BREAKER_FAILURE_THRESHOLD",
      },
      {
        id: "diagnostic.circuit_breaker_reset_seconds",
        label: "Délai avant nouvel essai (diagnostic)",
        value: 30,
        format: "seconds",
        step: 5,
        source: "fastapi/app/domains/diagnostic/adapter.py — CIRCUIT_BREAKER_RESET_TIMEOUT_SECONDS",
      },
      {
        id: "rate_limit.max_requests",
        label: "Requêtes maximum par minute (anti-abus)",
        value: 30,
        format: "count",
        step: 5,
        source: "fastapi/app/shared/rate_limit.py — RATE_LIMIT_MAX_REQUESTS",
      },
    ],
  },
];
