"""Miroir Pydantic des contrats JSON Schema de contracts/diagnostic/v1/.

Ces modeles ne portent aucune logique metier : ils ne font qu'appliquer, cote
Python, exactement les memes regles que les fichiers .schema.json versionnes
dans contracts/diagnostic/v1/. Toute modification d'un schema doit se
repercuter ici dans le meme changement (voir contracts/diagnostic/README.md,
section 7 "Processus de changement").

Correspondance fichier JSON Schema -> classe(s) Pydantic :
  - client-request.schema.json                -> DiagnosticResolveRequest
  - service-invocation-request.schema.json    -> DiagnosticInvocationRequest
  - service-invocation-response.schema.json   -> DiagnosticInvocationResponse
                                                  (ResolvedOutcome | EscalateOutcome | NeedMoreInfoOutcome)
  - capability-manifest.schema.json           -> CapabilityManifest
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter

_SNAKE_CASE = r"^[a-z][a-z0-9_]*$"
_SCREAMING_SNAKE_CASE = r"^[A-Z][A-Z0-9_]*$"


# ---------------------------------------------------------------------------
# client-request.schema.json
# POST /diagnostic/resolve : Dialogue Manager (Rasa) -> Diagnostic Engine
# ---------------------------------------------------------------------------


class DiagnosticResolveRequest(BaseModel):
    model_config = {"extra": "forbid"}

    session_id: str
    service: str = Field(pattern=_SNAKE_CASE)
    problem: str = Field(pattern=_SNAKE_CASE)
    entities: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# service-invocation-request.schema.json
# POST {base_url}/diagnostic/{problem_id} : Diagnostic Engine -> microservice
# ---------------------------------------------------------------------------


class DiagnosticInvocationRequest(BaseModel):
    model_config = {"extra": "forbid"}

    session_id: str
    trace_id: str
    user_id: str
    problem_id: str = Field(pattern=_SNAKE_CASE)
    entities: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# service-invocation-response.schema.json
# Reponse du microservice au Diagnostic Engine (3 variantes discriminees par
# le champ "outcome", miroir du oneOf/$defs du schema JSON).
# ---------------------------------------------------------------------------


class ResolvedOutcome(BaseModel):
    model_config = {"extra": "forbid"}

    outcome: Literal["RESOLVED"] = "RESOLVED"
    message: str = Field(min_length=1)
    resolution_code: str = Field(pattern=_SCREAMING_SNAKE_CASE)
    data: dict = Field(default_factory=dict)


class EscalationPayload(BaseModel):
    model_config = {"extra": "forbid"}

    category: str
    urgency: Literal["low", "medium", "high"]
    context: dict = Field(default_factory=dict)


class EscalateOutcome(BaseModel):
    model_config = {"extra": "forbid"}

    outcome: Literal["ESCALATE"] = "ESCALATE"
    message: str = Field(min_length=1)
    escalation_reason: str = Field(pattern=_SCREAMING_SNAKE_CASE)
    escalation_payload: EscalationPayload


class NeedMoreInfoOutcome(BaseModel):
    model_config = {"extra": "forbid"}

    outcome: Literal["NEED_MORE_INFO"] = "NEED_MORE_INFO"
    missing_fields: list[str] = Field(min_length=1)


DiagnosticInvocationResponse = Annotated[
    Union[ResolvedOutcome, EscalateOutcome, NeedMoreInfoOutcome],
    Field(discriminator="outcome"),
]
"""Type discrimine, a valider via `DiagnosticInvocationResponseAdapter.validate_python(...)`
(un Union discrimine n'est pas un BaseModel et ne peut pas etre instancie directement)."""

DiagnosticInvocationResponseAdapter = TypeAdapter(DiagnosticInvocationResponse)


# ---------------------------------------------------------------------------
# capability-manifest.schema.json
# GET {base_url}/diagnostic/manifest : auto-description d'un microservice
# ---------------------------------------------------------------------------


class FieldSpec(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(pattern=_SNAKE_CASE)
    type: Literal["string", "number", "boolean", "datetime"]
    description: str | None = None
    # Regex optionnelle que la valeur capturee doit satisfaire cote Dialogue
    # Manager avant d'etre envoyee a l'Engine (voir action_extract_diagnostic_entities
    # dans rasa/actions/actions.py). Absente = aucune validation de format.
    pattern: str | None = None


class DiagnosticEndpoint(BaseModel):
    model_config = {"extra": "forbid"}

    method: Literal["POST"]
    path: str = Field(pattern=r"^/diagnostic/.+")


class ResolutionCause(BaseModel):
    model_config = {"extra": "forbid"}

    code: str = Field(pattern=_SCREAMING_SNAKE_CASE)
    action: str


class ProblemDefinition(BaseModel):
    model_config = {"extra": "forbid"}

    id: str = Field(pattern=_SNAKE_CASE)
    label: str
    # Description en langage naturel du probleme (une ou deux phrases),
    # utilisee pour le matching semantique (embeddings) cote Dialogue Manager
    # -- voir GET /diagnostic/capabilities. Optionnelle : a defaut, le label
    # sert de texte a vectoriser (moins riche mais fonctionnel).
    description: str | None = None
    # Formulations alternatives, plus proches de la maniere dont un
    # utilisateur reel decrit le probleme (familier, detourne...) qu'une
    # description formelle unique. Chacune est vectorisee separement cote
    # Dialogue Manager, qui retient le MEILLEUR score parmi description +
    # example_phrases -- une seule phrase de reference degrade le matching
    # des que l'utilisateur s'exprime dans un style different (constate en
    # pratique). Optionnel, purement additif.
    example_phrases: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    endpoint: DiagnosticEndpoint
    required_fields: list[FieldSpec] = Field(default_factory=list)
    optional_fields: list[FieldSpec] = Field(default_factory=list)
    # Groupe de repli utilisable A LA PLACE de required_fields quand
    # l'utilisateur indique explicitement ne pas pouvoir fournir un des
    # champs requis (voir intent cannot_provide_field, rasa/actions/
    # diagnostic.py) -- ex. pas de reference de transaction mais date +
    # montant du retrait. Optionnel : une liste vide (defaut) signifie
    # qu'aucun repli n'existe pour ce probleme, required_fields reste alors
    # strictement obligatoire comme avant l'ajout de ce champ.
    fallback_fields: list[FieldSpec] = Field(default_factory=list)
    resolution_causes: list[ResolutionCause] = Field(default_factory=list)
    escalation_causes: list[str] = Field(default_factory=list)


class CapabilityManifest(BaseModel):
    model_config = {"extra": "forbid"}

    service: str = Field(pattern=_SNAKE_CASE)
    manifest_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    base_url: str
    protocol: Literal["REST", "GRPC"]
    problems: list[ProblemDefinition] = Field(min_length=1)


# ---------------------------------------------------------------------------
# GET /diagnostic/capabilities : agrege tous les manifestes connus, pour que
# le Dialogue Manager (Rasa) decouvre dynamiquement quels (service, probleme)
# sont reellement diagnosticables, sans registre statique cote Rasa.
# ---------------------------------------------------------------------------


class CapabilityProblemSummary(BaseModel):
    model_config = {"extra": "forbid"}

    service: str
    id: str
    label: str
    description: str | None = None
    keywords: list[str] = Field(default_factory=list)
    required_fields: list[FieldSpec] = Field(default_factory=list)
    optional_fields: list[FieldSpec] = Field(default_factory=list)
    fallback_fields: list[FieldSpec] = Field(default_factory=list)
    # Vecteur d'embedding precalcule (voir app.shared.embeddings), a partir de
    # la description (ou du label a defaut) -- calcule une seule fois par
    # rafraichissement du registre (CapabilityRegistry.refresh), pas a chaque
    # message utilisateur. Absent si le calcul a echoue (modele indisponible) :
    # le Dialogue Manager retombe alors sur le matching par mots-cles.
    embedding: list[float] | None = None
    # Un embedding precalcule par example_phrases (meme cycle de calcul que
    # `embedding` ci-dessus). Le Dialogue Manager compare le message a TOUS
    # ces vecteurs (embedding inclus) et retient le meilleur score -- voir le
    # commentaire de ProblemDefinition.example_phrases.
    example_embeddings: list[list[float]] = Field(default_factory=list)


class CapabilitiesResponse(BaseModel):
    model_config = {"extra": "forbid"}

    problems: list[CapabilityProblemSummary] = Field(default_factory=list)


class ClassifyDebugRequest(BaseModel):
    """Corps de POST /diagnostic/debug/classify (outil de debug/demo, voir
    router.py) : une phrase libre a comparer a tout le catalogue connu."""

    model_config = {"extra": "forbid"}

    text: str = Field(min_length=1)


class ClassifyDebugCandidate(BaseModel):
    model_config = {"extra": "forbid"}

    service: str
    problem_id: str
    label: str
    # Meilleure similarite cosinus entre le message et (description +
    # example_phrases) de ce probleme -- voir _score_capabilities_embeddings
    # cote rasa/actions/diagnostic.py, dont ce endpoint reproduit le calcul
    # de base (pas le repli mots-cles ni le rescue par clause, qui vivent
    # cote Rasa et dependent de l'etat de conversation).
    score: float
    has_embedding: bool


class ClassifyDebugResponse(BaseModel):
    model_config = {"extra": "forbid"}

    text: str
    # Tous les candidats, tries par score decroissant -- contrairement au
    # Dialogue Manager (qui ne garde que le top MAX_CANDIDATES et applique un
    # seuil/une marge), cet endpoint montre TOUT pour permettre de
    # diagnostiquer une collision comme celle corrigee sur withdrawal_pending
    # vs compliance_hold_blocking sans avoir a rejouer un script jetable.
    candidates: list[ClassifyDebugCandidate] = Field(default_factory=list)
