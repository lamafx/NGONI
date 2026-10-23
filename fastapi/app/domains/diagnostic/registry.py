"""Capability Registry du Diagnostic Engine (Phase 5, voir docs/diagnostic-roadmap.md).

La LISTE des microservices connus vient de services_registry.yaml (racine du
projet fastapi/), pas du code -- ajouter un service = ajouter une entree dans
ce fichier, sans redemarrer le Engine (voir poll_forever, appele depuis
app/main.py toutes les REGISTRY_POLL_INTERVAL_SECONDS). Le CONTENU de chaque
manifeste, lui, n'est jamais duplique ici : il est recupere reellement via
GET {base_url}/diagnostic/manifest et valide contre le meme contrat Pydantic
que celui teste en Phase 0 (app.domains.diagnostic.contracts.CapabilityManifest).
Ajouter un probleme cote wallet-service (ou un nouveau service deja dans le
YAML) n'exige donc aucune modification de ce fichier.

Avant la Phase 5, cette liste etait codee en dur dans une fonction Python
(_default_known_services, voir l'historique git) -- remplacee ici par
_load_services_from_yaml.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import yaml

try:
    from app.shared.embeddings import embed_passage_batch
except ImportError:  # pragma: no cover - support running as `main`
    from shared.embeddings import embed_passage_batch

from .contracts import CapabilityManifest, ProblemDefinition

logger = logging.getLogger(__name__)

# fastapi/services_registry.yaml par defaut (ce fichier vit dans
# fastapi/app/domains/diagnostic/) -- surchargeable via variable
# d'environnement pour les tests ou un deploiement qui range le fichier
# ailleurs.
SERVICES_REGISTRY_PATH = os.getenv(
    "SERVICES_REGISTRY_PATH",
    str(Path(__file__).resolve().parents[3] / "services_registry.yaml"),
)

# Frequence de rafraichissement periodique du Registry (voir
# CapabilityRegistry.poll_forever, demarre depuis app/main.py). Descendre
# cette valeur accelere la prise en compte d'un nouveau service ou d'un
# nouveau probleme, au prix d'appels HTTP GET /diagnostic/manifest et d'un
# recalcul batche des embeddings (voir _compute_all_embeddings) plus
# frequents. 30s convenait pour une demo/soutenance en developpement local ;
# remonte a 300s comme valeur par defaut de production (mise en conformite,
# voir checklist production) -- un nouveau probleme/service reste pris en
# compte au plus tard 5 minutes apres sa publication, sans redemarrage.
REGISTRY_POLL_INTERVAL_SECONDS = float(os.getenv("REGISTRY_POLL_INTERVAL_SECONDS", "300"))

# Delai minimal entre deux tentatives de chargement A LA DEMANDE lorsque le
# registre est ressorti VIDE du dernier refresh (voir ensure_loaded).
#
# Sans cette temporisation, `is_empty()` signifiait a la fois "jamais charge"
# et "charge, mais aucun service n'a repondu" : ensure_loaded() relancait donc
# un refresh complet a CHAQUE appel tant qu'aucun microservice n'etait
# joignable. Or ensure_loaded() est sur le chemin chaud de
# GET /diagnostic/capabilities ET de chaque tour de DiagnosticPipeline --
# avec les services eteints, chaque requete repayait le cout de connexion des
# services injoignables (mesure : ~2,4 s par service sous Windows, la pile
# TCP reemettant plusieurs SYN avant d'abandonner), soit ~5 s par appel.
# C'est ce qui rendait la page d'administration "Statistiques" lente a
# afficher alors que ses propres compteurs arrivent en 40 ms.
#
# La reprise reste rapide quand un service redemarre : au plus tard apres ce
# delai a la demande, et de toute facon au prochain cycle de poll_forever.
REGISTRY_EMPTY_RETRY_SECONDS = float(os.getenv("REGISTRY_EMPTY_RETRY_SECONDS", "30"))


@dataclass(frozen=True)
class RegisteredService:
    """Un microservice connu du Diagnostic Engine (charge depuis services_registry.yaml, Phase 5)."""

    name: str
    base_url: str
    internal_secret: str


@dataclass(frozen=True)
class RoutableProblem:
    """Cible resolue pour un couple (service, problem_id) : ou et comment appeler."""

    service: str
    problem: ProblemDefinition
    base_url: str
    internal_secret: str
    # Precalcule une seule fois par refresh() (pas a chaque message
    # utilisateur) : voir app.shared.embeddings. None si le modele
    # d'embeddings a echoue a charger/calculer -- le Dialogue Manager retombe
    # alors sur le matching par mots-cles pour ce probleme.
    embedding: list[float] | None = None
    # Un embedding par example_phrases, meme cycle de calcul. Voir
    # ProblemDefinition.example_phrases pour la justification (une seule
    # phrase de reference degrade le matching des que l'utilisateur
    # s'exprime dans un style different).
    example_embeddings: list[list[float]] = field(default_factory=list)


def _load_services_from_yaml(path: str | Path) -> list[RegisteredService]:
    """Charge la liste des microservices connus depuis un fichier YAML
    (Phase 5) -- remplace la liste codee en dur de la Phase 1. Chaque entree
    declare le NOM d'une variable d'environnement pour son URL/secret, pas la
    valeur elle-meme : la valeur reste fournie par l'environnement
    d'execution (docker-compose, .env...), le YAML ne fait que decrire quels
    services existent et quelles variables les configurent.

    Un fichier absent, illisible ou mal forme degrade vers une liste vide
    (log un warning) plutot que de faire planter le Engine au demarrage --
    coherent avec la politique de resilience du reste du Registry (un
    registre de services mal forme ne doit pas empecher tout le diagnostic,
    au pire aucun service n'est routable jusqu'a ce qu'il soit corrige).
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("[DIAG][REGISTRY] Impossible de charger '%s': %s", path, exc)
        return []

    services: list[RegisteredService] = []
    for entry in raw.get("services") or []:
        try:
            name = entry["name"]
            base_url = os.getenv(entry["base_url_env"], entry.get("base_url_default", ""))
            secret_env = entry.get("internal_secret_env")
            internal_secret = os.getenv(secret_env, "") if secret_env else ""
        except (KeyError, TypeError) as exc:
            logger.warning("[DIAG][REGISTRY] Entree de services_registry.yaml ignoree (invalide: %s) : %r", exc, entry)
            continue
        if not base_url:
            logger.warning(
                "[DIAG][REGISTRY] Service '%s' ignore : aucune base_url resolue (variable '%s' absente et pas de defaut)",
                name, entry.get("base_url_env"),
            )
            continue
        services.append(RegisteredService(name=name, base_url=base_url, internal_secret=internal_secret))
    return services


class CapabilityRegistry:
    """Index (service, problem_id) -> RoutableProblem, construit depuis les manifestes reels."""

    def __init__(
        self,
        services: list[RegisteredService] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        registry_path: str | Path | None = None,
    ) -> None:
        # `services` explicitement fourni (tests, ou tout appelant qui gere
        # sa propre liste) : figee pour la duree de vie de l'instance, jamais
        # relue depuis le YAML. Sinon (cas normal en production), la liste
        # est relue depuis `registry_path` a CHAQUE refresh() -- voir
        # _current_services -- pour qu'ajouter un service au fichier soit
        # visible au prochain cycle de poll_forever, sans redemarrer le
        # process (Phase 5, etape 24).
        self._explicit_services = services
        self._registry_path = registry_path if registry_path is not None else SERVICES_REGISTRY_PATH
        self._transport = transport
        self._index: dict[tuple[str, str], RoutableProblem] = {}
        # Instant (monotone) du dernier refresh ayant produit un index vide --
        # None des qu'un refresh a ramene au moins un probleme. Voir
        # REGISTRY_EMPTY_RETRY_SECONDS et ensure_loaded.
        self._empty_since: float | None = None

    def _current_services(self) -> list[RegisteredService]:
        if self._explicit_services is not None:
            return self._explicit_services
        return _load_services_from_yaml(self._registry_path)

    def is_empty(self) -> bool:
        return not self._index

    async def ensure_loaded(self) -> None:
        """Charge l'index au premier appel. Idempotent tant que refresh() n'est
        pas rappele.

        Si le dernier chargement a ramene un index VIDE (aucun microservice
        joignable), les appels suivants n'en redeclenchent pas un nouveau
        avant REGISTRY_EMPTY_RETRY_SECONDS : sinon chaque requete rejouerait
        l'attente de connexion vers des services eteints, sur le chemin chaud
        de /diagnostic/capabilities comme du pipeline de diagnostic.
        """
        if not self.is_empty():
            return
        if self._empty_since is not None:
            if time.monotonic() - self._empty_since < REGISTRY_EMPTY_RETRY_SECONDS:
                return
        await self.refresh()

    async def refresh(self) -> None:
        """Recharge entierement l'index en interrogeant GET /diagnostic/manifest
        de chaque service connu. Un service injoignable ou renvoyant un
        manifeste non conforme est ignore (log) plutot que de faire echouer
        tout le registre -- un service en panne ne doit pas empecher les autres
        d'etre diagnosticables.

        Relit aussi la LISTE des services elle-meme (_current_services, Phase
        5) : contrairement a la Phase 1 ou cette liste etait figee au
        demarrage du process, un service ajoute a services_registry.yaml
        pendant que le Engine tourne est donc pris en compte des le prochain
        appel a refresh() (voir poll_forever), sans redemarrage.
        """
        services = self._current_services()
        # (service, problem) -> (ProblemDefinition, manifest, service enregistre) :
        # collecte d'abord TOUS les problemes de TOUS les manifestes, avant de
        # calculer le moindre embedding -- necessaire pour les batcher en un
        # seul appel au modele juste apres (_compute_all_embeddings), plutot
        # que d'embedder chaque probleme des qu'il est decouvert.
        entries: dict[tuple[str, str], tuple[ProblemDefinition, CapabilityManifest, RegisteredService]] = {}
        # Manifestes interroges EN PARALLELE (asyncio.gather) et non plus l'un
        # apres l'autre : le cout d'un cycle etait la SOMME des temps de
        # reponse (ou d'echec) de tous les services, alors que ces appels sont
        # totalement independants. Avec deux services injoignables, le refresh
        # passe de ~5 s a ~2,4 s ; l'ecart grandit avec chaque service ajoute
        # au YAML. L'ordre de `services` est preserve par gather, donc en cas
        # de cle (service, probleme) dupliquee entre deux manifestes, c'est
        # toujours le dernier service du fichier qui l'emporte -- comme avant.
        async with httpx.AsyncClient(timeout=5.0, transport=self._transport) as client:
            manifests = await asyncio.gather(
                *(self._fetch_manifest(client, service) for service in services)
            )
        for service, manifest in zip(services, manifests):
            if manifest is None:
                continue
            for problem in manifest.problems:
                entries[(manifest.service, problem.id)] = (problem, manifest, service)

        embeddings_by_key = await self._compute_all_embeddings(entries)

        index: dict[tuple[str, str], RoutableProblem] = {}
        for key, (problem, manifest, service) in entries.items():
            embedding, example_embeddings = embeddings_by_key.get(key, (None, []))
            index[key] = RoutableProblem(
                service=manifest.service,
                problem=problem,
                base_url=manifest.base_url,
                internal_secret=service.internal_secret,
                embedding=embedding,
                example_embeddings=example_embeddings,
            )
        self._index = index
        self._empty_since = None if index else time.monotonic()

    async def poll_forever(self, interval_seconds: float = REGISTRY_POLL_INTERVAL_SECONDS) -> None:
        """Boucle de rafraichissement periodique (Phase 5, etape 23) -- a
        lancer une seule fois en tache de fond depuis app/main.py
        (asyncio.create_task), annulee proprement a l'arret du process.
        N'appelle jamais refresh() en boucle serree : une erreur inattendue
        (ex. YAML corrompu entre deux cycles) est journalisee et le prochain
        cycle reessaie, plutot que de laisser une exception non geree tuer la
        tache de fond silencieusement.
        """
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                await self.refresh()
            except Exception:
                logger.warning("[DIAG][REGISTRY] Echec du rafraichissement periodique", exc_info=True)

    @staticmethod
    async def _compute_all_embeddings(
        entries: dict[tuple[str, str], tuple[ProblemDefinition, CapabilityManifest, RegisteredService]]
    ) -> dict[tuple[str, str], tuple[list[float] | None, list[list[float]]]]:
        # Remplace l'ancien _compute_embedding/_compute_example_embeddings
        # (un appel embed_passage PAR phrase, ~67 appels par cycle avec le
        # catalogue actuel) par UN SEUL appel batche (embed_passage_batch),
        # execute dans un thread (asyncio.to_thread) plutot que directement
        # dans cette coroutine : model.encode() est un calcul CPU synchrone,
        # l'appeler sans le deleguer a un thread bloquerait toute la boucle
        # asyncio -- donc TOUT le process FastAPI, pas seulement ce
        # refresh() -- pendant toute sa duree (constate en pratique : des
        # requetes /feedback et /diagnostic/capabilities expiraient pendant
        # un refresh, sans rapport fonctionnel avec elles).
        #
        # Ne fait jamais echouer tout le registre si le modele est
        # indisponible : chaque probleme reste routable, juste sans embedding
        # (repli sur les mots-cles cote Rasa pour celui-ci) -- meme
        # comportement degrade qu'avant, mais desormais tout-ou-rien pour un
        # cycle donne plutot que phrase par phrase (embed_passage ne fait
        # aucun appel reseau, une panne partielle phrase-par-phrase n'etait
        # de toute façon pas un cas realiste).
        if not entries:
            return {}

        texts: list[str] = []
        positions: list[tuple[tuple[str, str], int]] = []  # index -1 = description, sinon index dans example_phrases
        for key, (problem, _manifest, _service) in entries.items():
            texts.append(problem.description or problem.label)
            positions.append((key, -1))
            for i, phrase in enumerate(problem.example_phrases):
                texts.append(phrase)
                positions.append((key, i))

        try:
            vectors = await asyncio.to_thread(embed_passage_batch, texts)
        except Exception:
            logger.warning("[DIAG][REGISTRY] Echec du calcul batche des embeddings", exc_info=True)
            return {}

        embedding_by_key: dict[tuple[str, str], list[float] | None] = {}
        examples_by_key: dict[tuple[str, str], list[list[float]]] = {key: [] for key in entries}
        for (key, role), vector in zip(positions, vectors):
            if role == -1:
                embedding_by_key[key] = vector
            else:
                examples_by_key[key].append(vector)

        return {key: (embedding_by_key.get(key), examples_by_key[key]) for key in entries}

    async def _fetch_manifest(
        self, client: httpx.AsyncClient, service: RegisteredService
    ) -> CapabilityManifest | None:
        try:
            response = await client.get(
                f"{service.base_url}/diagnostic/manifest",
                headers={"X-Internal-Secret": service.internal_secret},
            )
            response.raise_for_status()
            return CapabilityManifest.model_validate(response.json())
        except (httpx.HTTPError, ValueError):
            return None

    def lookup(self, service: str, problem_id: str) -> RoutableProblem | None:
        return self._index.get((service, problem_id))

    def all_problems(self) -> list[RoutableProblem]:
        return list(self._index.values())
