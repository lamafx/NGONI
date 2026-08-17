from os import getenv
from pathlib import Path

import asyncio
import logging
import uuid
import httpx
from dotenv import load_dotenv
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

# Configure au tout debut de l'import : uvicorn ne configure QUE ses propres
# loggers (uvicorn/uvicorn.access/uvicorn.error), jamais le logger racine --
# sans ceci, tous les logger.info(...) applicatifs (voir app.domains.diagnostic)
# sont silencieusement avales (root reste au niveau WARNING par defaut).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

load_dotenv(Path(__file__).resolve().parents[1] / '.env')

try:
    from .domains.faq.router import router as faq_router
    from .domains.complaints.router import router as complaints_router, create_ticket as complaints_create_ticket
    from .domains.complaints.admin_router import router as complaints_admin_router
    from .domains.feedback.router import router as feedback_router
    from .domains.diagnostic.registry import REGISTRY_POLL_INTERVAL_SECONDS
    from .domains.diagnostic.router import router as diagnostic_router, get_registry
    from .domains.audit.router import router as audit_router
    from .domains.audit.service import record_faq_lookup
    from .domains.nlu.engines import DEFAULT_ENGINE, predict as nlu_predict
    from .domains.nlu.router import router as nlu_router
    from .shared.admin_auth import warn_if_admin_secret_missing
    from .shared.rate_limit import InMemoryRateLimitMiddleware
    from .shared.embeddings.router import router as embeddings_router
    from .shared.embeddings import get_embedding_model
    from .shared.rasa_client import RASA_PARSE_URL, RASA_WEBHOOK_URL, call_rasa_with_retry
    from .domains.faq.service import FaqService
    from .domains.faq.repository import FaqRepository
    from .domains.complaints.schemas import TicketCreateResponse
    from .database import get_db
except ImportError:  # pragma: no cover - support running as `uvicorn main:app`
    from domains.faq.router import router as faq_router
    from domains.complaints.router import router as complaints_router, create_ticket as complaints_create_ticket
    from domains.complaints.admin_router import router as complaints_admin_router
    from domains.feedback.router import router as feedback_router
    from domains.diagnostic.registry import REGISTRY_POLL_INTERVAL_SECONDS
    from domains.diagnostic.router import router as diagnostic_router, get_registry
    from domains.audit.router import router as audit_router
    from domains.audit.service import record_faq_lookup
    from domains.nlu.engines import DEFAULT_ENGINE, predict as nlu_predict
    from domains.nlu.router import router as nlu_router
    from shared.admin_auth import warn_if_admin_secret_missing
    from shared.rate_limit import InMemoryRateLimitMiddleware
    from shared.embeddings.router import router as embeddings_router
    from shared.embeddings import get_embedding_model
    from shared.rasa_client import RASA_PARSE_URL, RASA_WEBHOOK_URL, call_rasa_with_retry
    from domains.faq.service import FaqService
    from domains.faq.repository import FaqRepository
    from domains.complaints.schemas import TicketCreateResponse
    from database import get_db

logger = logging.getLogger(__name__)

app = FastAPI(title="NGONI FastAPI", version="1.0.0")
app.add_middleware(InMemoryRateLimitMiddleware)

RASA_RETRY_COUNT = int(getenv("RASA_RETRY_COUNT", "3"))
RASA_RETRY_DELAY = float(getenv("RASA_RETRY_DELAY", "1.0"))

app.include_router(faq_router)
app.include_router(complaints_router)
app.include_router(complaints_admin_router)
app.include_router(feedback_router)
app.include_router(diagnostic_router)
app.include_router(audit_router)
app.include_router(embeddings_router)
app.include_router(nlu_router)


_registry_poll_task: asyncio.Task | None = None


@app.on_event("startup")
async def startup():
    global _registry_poll_task
    logger.info("Starting service initialization...")
    warn_if_admin_secret_missing()
    await wait_for_rasa()

    # Le modele d'embeddings et le Capability Registry se chargeaient jusqu'ici
    # au premier appel reel (singleton paresseux) : la 1ere requete utilisateur
    # apres chaque redemarrage payait donc le cout de chargement (~10-20s, avec
    # verifications reseau vers huggingface.co) dans le budget des 10s alloues
    # par Rasa a _fetch_capabilities/_embed_message, provoquant un faux
    # "service indisponible" -- constate en pratique a deux reprises. On paie
    # ce cout ici, une seule fois au demarrage, avant d'accepter du trafic.
    logger.info("Pré-chargement du modèle d'embeddings...")
    get_embedding_model()
    logger.info("Pré-chauffage du Capability Registry...")
    registry = get_registry()
    await registry.ensure_loaded()

    # Phase 5 (voir docs/diagnostic-roadmap.md) : rafraichissement periodique
    # en tache de fond, PAS juste au demarrage -- un service ajoute a
    # services_registry.yaml (ou un manifeste modifie) pendant que le process
    # tourne devient diagnosticable au prochain cycle, sans redemarrer le
    # Engine. La tache tourne pour toute la duree de vie du process ;
    # reference gardee dans _registry_poll_task pour pouvoir l'annuler
    # proprement a l'arret (voir shutdown() plus bas).
    logger.info(
        "Démarrage du rafraîchissement périodique du Capability Registry (toutes les %.0fs)...",
        REGISTRY_POLL_INTERVAL_SECONDS,
    )
    _registry_poll_task = asyncio.create_task(registry.poll_forever())

    # Avertissement operationnel (audit robustesse) : get_registry()/get_adapter()
    # (diagnostic/router.py) et les compteurs de rate-limiting/circuit-breaker
    # (rasa/actions/reclamation.py) sont TOUS un etat en memoire d'UN SEUL
    # process Python -- corrects avec `uvicorn ...` (sans --workers), mais
    # divergent silencieusement des qu'on lance plusieurs workers/replicas
    # (chacun avec son propre disjoncteur/compteur/cache independant). Aucun
    # moyen fiable de detecter le nombre de workers depuis l'interieur du
    # process (uvicorn --workers ne pose pas de variable d'environnement
    # dediee) -- ce log rend la contrainte visible au demarrage via la
    # variable WEB_CONCURRENCY (convention gunicorn/uvicorn courante), plutot
    # que de la laisser purement documentaire dans le code.
    if int(getenv("WEB_CONCURRENCY", "1")) > 1:
        logger.warning(
            "WEB_CONCURRENCY=%s : ce service suppose un SEUL worker (Capability Registry, "
            "circuit breakers et rate-limiters sont en memoire de process, non partages). "
            "Deployer plusieurs workers/replicas sans etat partage (Redis) casse silencieusement "
            "ces garanties.",
            getenv("WEB_CONCURRENCY"),
        )

    # Pas d'emoji dans ce message (contrairement a une version precedente) :
    # la console Windows par defaut (codepage cp1252) ne peut pas l'encoder,
    # ce qui fait planter le process au demarrage avec un UnicodeEncodeError
    # -- constate en pratique, un simple redemarrage suffisait a le
    # reproduire des que la sortie standard n'etait pas explicitement en
    # UTF-8 (ex. redirigee vers un fichier sans PYTHONIOENCODING=utf-8).
    logger.info("Service initialized - Rasa connected")


@app.on_event("shutdown")
async def shutdown():
    # Sans annulation explicite, la tache de fond du polling (voir startup())
    # continue de tourner (et de logger des erreurs de connexion) apres que
    # uvicorn a commence a fermer le reste du process -- bruit inutile dans
    # les logs, sans consequence fonctionnelle mais qui complique le
    # diagnostic d'un vrai arret propre.
    if _registry_poll_task is not None:
        _registry_poll_task.cancel()


async def wait_for_rasa():
    logger.info("Waiting for Rasa to become available...")
    for attempt in range(1, RASA_RETRY_COUNT + 1):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(RASA_PARSE_URL, timeout=5.0)
                if response.status_code == 405 or response.status_code == 200:
                    logger.info("Rasa is available.")
                    return
        except Exception as exc:
            logger.warning("Rasa not ready yet (attempt %s/%s): %s", attempt, RASA_RETRY_COUNT, exc)
        await asyncio.sleep(RASA_RETRY_DELAY)
    logger.warning("Rasa did not become available after %s attempts.", RASA_RETRY_COUNT)


# Alias de /complaints/create (meme fonction, pas une reimplementation) :
# c'est l'URL que Rasa appelle reellement (TICKET_SERVICE_URL, voir
# rasa/actions/reclamation.py) -- avant ce changement, les deux routes
# dupliquaient la meme logique dans deux fichiers, avec le risque reel de
# les faire diverger silencieusement (deja arrive pendant le developpement
# de la tracabilite d'acteur : une seule des deux avait ete mise a jour).
app.add_api_route(
    "/tickets/create",
    complaints_create_ticket,
    methods=["POST"],
    response_model=TicketCreateResponse,
)


@app.get("/")
def read_root():
    # Remplace l'ancienne page placeholder ("Testeur de modele Rasa") --
    # redirige vers le nouveau frontend (frontend/index.html, monte plus bas
    # via StaticFiles). Route enregistree avant le montage : reste prioritaire
    # sur "/" exact, comme requis par Starlette (routes explicites d'abord).
    return RedirectResponse(url="/index.html")


@app.get("/chat", response_class=HTMLResponse)
def chat_page():
    return """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Chat NGONI</title>
  <style>
    body {
      font-family: Arial, sans-serif;
      background: #f4f7fb;
      margin: 0;
      padding: 0;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
    }
    .chat-container {
      width: min(960px, 100%);
      max-width: 960px;
      background: #ffffff;
      border-radius: 16px;
      box-shadow: 0 16px 50px rgba(0, 0, 0, 0.1);
      overflow: hidden;
    }
    .chat-header {
      background: linear-gradient(135deg, #4b6cb7 0%, #182848 100%);
      color: white;
      padding: 24px;
      text-align: center;
    }
    .chat-body {
      padding: 24px;
      display: grid;
      gap: 16px;
    }
    .messages {
      min-height: 280px;
      max-height: 520px;
      overflow-y: auto;
      display: grid;
      gap: 12px;
    }
    .message {
      max-width: 85%;
      padding: 14px 18px;
      border-radius: 18px;
      line-height: 1.5;
      white-space: pre-wrap;
      word-wrap: break-word;
    }
    .message.user {
      background: #dfe7ff;
      justify-self: end;
      border-bottom-right-radius: 4px;
    }
    .message.bot {
      background: #f0f3f8;
      justify-self: start;
      border-bottom-left-radius: 4px;
    }
    .message-buttons {
      max-width: 85%;
      justify-self: start;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .message-buttons button {
      background: white;
      color: #4b6cb7;
      border: 1px solid #4b6cb7;
      border-radius: 16px;
      padding: 8px 14px;
      font-size: 0.9rem;
      cursor: pointer;
    }
    .message-buttons button:hover {
      background: #4b6cb7;
      color: white;
    }
    .message-buttons button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .meta {
      font-size: 0.9rem;
      color: #495057;
      margin-top: 4px;
    }
    .chat-input {
      display: grid;
      gap: 12px;
    }
    .chat-input textarea {
      resize: vertical;
      min-height: 80px;
      border: 1px solid #d1d5db;
      border-radius: 12px;
      padding: 14px;
      font-size: 1rem;
      width: 100%;
      outline: none;
    }
    .chat-input button {
      background: #4b6cb7;
      color: white;
      border: none;
      border-radius: 12px;
      padding: 14px 20px;
      cursor: pointer;
      font-size: 1rem;
    }
    .chat-input button:hover {
      filter: brightness(1.05);
    }
    .info-box {
      background: #eef2ff;
      color: #1f2937;
      padding: 14px 18px;
      border-radius: 12px;
      font-size: 0.95rem;
    }
    .typing-indicator {
      display: flex;
      align-items: center;
      gap: 4px;
      padding: 14px 18px;
      width: fit-content;
    }
    .typing-indicator span {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #9aa5b1;
      animation: typing-bounce 1.2s infinite ease-in-out;
    }
    .typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
    .typing-indicator span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes typing-bounce {
      0%, 60%, 100% { transform: translateY(0); opacity: 0.5; }
      30% { transform: translateY(-6px); opacity: 1; }
    }
    .chat-input button:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }
  </style>
</head>
<body>
  <div class="chat-container">
    <div class="chat-header">
      <h1>Chat NGONI</h1>
      <p>Interface dédiée sans Swagger pour parler au modèle via Rasa et FastAPI.</p>
    </div>
    <div class="chat-body">
      <div class="messages" id="messages"></div>
      <div class="info-box" id="parse-info">Envoyez un message pour voir l'intent et le score de confiance.</div>
      <form id="chat-form" class="chat-input">
        <input id="user-id-input" type="text" placeholder="User ID (UUID wallet, optionnel — sinon un ID de test propre à cet onglet)" aria-label="Identifiant utilisateur" style="border:1px solid #d1d5db;border-radius:12px;padding:10px 14px;font-size:0.95rem;" />
        <textarea id="user-input" placeholder="Écris ton message ici..." aria-label="Message utilisateur" maxlength="4000"></textarea>
        <button type="submit">Envoyer</button>
      </form>
    </div>
  </div>
  <script>
    const messagesEl = document.getElementById('messages');
    const parseInfoEl = document.getElementById('parse-info');
    const chatForm = document.getElementById('chat-form');
    const userInput = document.getElementById('user-input');
    const userIdInput = document.getElementById('user-id-input');
    const submitButton = chatForm.querySelector('button[type="submit"]');

    // Sans ceci, deux tests laissant ce champ vide partageaient tous deux le
    // meme sender_id fixe ("frontend_user") cote backend -- l'etat de
    // diagnostic (diagnostic_state) d'un test precedent (le mien ou celui
    // d'un autre visiteur) se melangeait alors a la conversation en cours.
    // Un identifiant aleatoire par onglet (sessionStorage : reinitialise a la
    // fermeture, pas partage entre onglets) evite cette collision tout en
    // laissant la possibilite de tester un vrai user_id via le champ ci-dessus.
    function getDefaultSenderId() {
      let id = sessionStorage.getItem('ngoni_demo_sender_id');
      if (!id) {
        id = 'demo-' + crypto.randomUUID();
        sessionStorage.setItem('ngoni_demo_sender_id', id);
      }
      return id;
    }

    function addMessage(text, sender) {
      const el = document.createElement('div');
      el.className = `message ${sender}`;
      el.textContent = text;
      messagesEl.appendChild(el);
      messagesEl.scrollTop = messagesEl.scrollHeight;
      return el;
    }

    // Boutons Rasa (buttons: [{title, payload}]) : ex. les categories/
    // questions FAQ (voir action_greet_with_time, action_select_faq_category,
    // rasa/actions/faq.py). Un clic envoie le payload exactement comme s'il
    // avait ete tape au clavier -- meme chemin que la saisie libre, aucune
    // logique dupliquee. Desactives apres le premier clic pour eviter un
    // second envoi sur des boutons perimes (ex. deja cliques, ou categorie
    // dont le tirage a change entre-temps).
    function addButtons(buttons) {
      if (!buttons || buttons.length === 0) {
        return;
      }
      const el = document.createElement('div');
      el.className = 'message-buttons';
      for (const button of buttons) {
        const btnEl = document.createElement('button');
        btnEl.type = 'button';
        btnEl.textContent = button.title;
        btnEl.addEventListener('click', () => {
          for (const sibling of el.querySelectorAll('button')) {
            sibling.disabled = true;
          }
          sendMessage(button.payload, button.title);
        });
        el.appendChild(btnEl);
      }
      messagesEl.appendChild(el);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function showTypingIndicator() {
      const el = document.createElement('div');
      el.className = 'message bot';
      el.innerHTML = '<div class="typing-indicator"><span></span><span></span><span></span></div>';
      messagesEl.appendChild(el);
      messagesEl.scrollTop = messagesEl.scrollHeight;
      return el;
    }

    function updateParseInfo(intent, confidence, entities) {
      parseInfoEl.innerHTML = `
        <strong>Intent détecté :</strong> ${intent || 'aucun'}<br />
        <strong>Confidence :</strong> ${confidence !== undefined ? confidence.toFixed(3) : 'n/a'}<br />
        <strong>Entités :</strong> ${entities.length ? entities.map(e => `${e.entity}=${e.value}`).join(', ') : 'aucune'}
      `;
    }

    async function postJson(url, payload) {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const content = await response.text();
        throw new Error(`${response.status} ${response.statusText}: ${content}`);
      }
      return response.json();
    }

    // Point d'entree unique pour tout message sortant, tape au clavier ou
    // issu d'un clic sur un bouton (addButtons ci-dessus) -- les deux doivent
    // suivre exactement le meme chemin (/api/parse puis /api/chat) pour que
    // cliquer une question suggeree se comporte comme si elle avait ete tapee.
    // `payload` est ce qui est envoye a Rasa (peut etre une commande technique
    // du type /select_faq_question{"faq_slug": "..."} pour un c lic de bouton) ;
    // `displayText` est ce qui est affiche dans la bulle utilisateur -- le
    // titre lisible du bouton (la vraie question), jamais le payload. Pour
    // une saisie clavier, displayText est absent et on retombe sur payload
    // (les deux sont deja identiques dans ce cas).
    async function sendMessage(payload, displayText) {
      addMessage(displayText ?? payload, 'user');
      updateParseInfo('En cours...', 0, []);
      submitButton.disabled = true;
      const typingEl = showTypingIndicator();

      try {
        const parseResult = await postJson('/api/parse', { text: payload });
        const intent = parseResult.intent?.name;
        const confidence = parseResult.intent?.confidence;
        const entities = parseResult.entities || [];
        updateParseInfo(intent, confidence, entities);

        const userId = userIdInput.value.trim() || getDefaultSenderId();
        const chatResult = await postJson('/api/chat', { text: payload, user_id: userId });
        const messages = Array.isArray(chatResult.messages) ? chatResult.messages : [];

        typingEl.remove();

        if (messages.length === 0) {
          addMessage('Aucune réponse reçue du bot.', 'bot');
        } else {
          for (const message of messages) {
            const botText = message.text || message.message || JSON.stringify(message);
            addMessage(botText, 'bot');
            addButtons(message.buttons);
          }
        }
      } catch (error) {
        // Le detail technique (status HTTP, corps JSON brut -- qui peut
        // inclure le texte utilisateur renvoye tel quel par une erreur de
        // validation Pydantic, ex. message trop long) reste dans la console
        // pour le debogage, mais n'est plus affiche dans la bulle : un
        // utilisateur reel n'a pas a voir un pave JSON illisible en pleine
        // conversation (constate en pratique sur un message de plus de 4000
        // caracteres, deja borne cote serveur -- voir ParseRequest/
        // ChatRequest ci-dessous -- mais jusqu'ici affiche integralement,
        // texte original inclus, au moindre depassement).
        console.error('Erreur lors de l\'envoi du message :', error);
        typingEl.remove();
        addMessage('Désolé, une erreur est survenue pendant l\'envoi de votre message. Veuillez réessayer dans un instant.', 'bot');
        updateParseInfo('erreur', 0, []);
      } finally {
        submitButton.disabled = false;
      }
    }

    chatForm.addEventListener('submit', (event) => {
      event.preventDefault();
      const text = userInput.value.trim();
      if (!text) {
        return;
      }
      userInput.value = '';
      sendMessage(text);
    });
  </script>
</body>
</html>"""


class ParseRequest(BaseModel):
    # Meme plafond que ChatRequest ci-dessous (voir son commentaire) : ce
    # endpoint recoit exactement le meme texte utilisateur, juste envoye a
    # une route Rasa differente (analyse d'intention plutot que webhook).
    text: str = Field(min_length=1, max_length=4000)
    # None => DEFAULT_ENGINE ("rasa", voir app/domains/nlu/engines.py).
    # Catalogue expose par GET /api/models -- voir frontend/pages/chat/model.store.js.
    model: Optional[str] = Field(default=None, max_length=50)


class ChatRequest(BaseModel):
    # Avant ce schema, `request: dict` n'imposait ni type ni longueur : un
    # texte demesurement long ou un champ non-string passait tel quel jusqu'a
    # Rasa. 4000 caracteres laisse une marge confortable au-dessus du plus
    # grand champ libre reellement valide plus loin dans le flux (description
    # de reclamation, MAX_DESCRIPTION_LENGTH=2000 cote rasa/actions/reclamation.py)
    # tout en bornant la requete des l'entree du systeme, pas seulement une
    # fois arrivee dans le formulaire.
    text: str = Field(min_length=1, max_length=4000)
    user_id: Optional[str] = Field(default=None, max_length=200)
    model: Optional[str] = Field(default=None, max_length=50)
    # Bascule "Mode Super-Agent" (voir frontend/pages/chat/superagent.store.js) --
    # transmise a Rasa via metadata (voir plus bas), jamais interpretee ici :
    # seuls les actions du diagnostic (rasa/actions/diagnostic.py,
    # is_superagent_mode) en tiennent compte.
    superagent: bool = False


@app.post("/api/parse")
async def parse_message(request: ParseRequest):
    text = request.text

    # Payload structure (clic sur un bouton, ex. "/select_faq_question{...}",
    # voir frontend/pages/chat/chat-view.js::addButtons) : deja une intention
    # pre-classifiee cote frontend -- contourne entierement le selecteur de
    # modele, interroge Rasa directement comme avant son introduction.
    if text.startswith("/"):
        try:
            response = await call_rasa_with_retry(RASA_PARSE_URL, {"text": text})
        except HTTPException as error:
            raise error
        except Exception as error:
            raise HTTPException(status_code=502, detail=f"Impossible de contacter Rasa: {error}")
        logger.info("parse_message succeeded using %s", RASA_PARSE_URL)
        return response.json()

    model_id = request.model or DEFAULT_ENGINE
    try:
        prediction = await nlu_predict(model_id, text)
    except HTTPException as error:
        raise error
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Impossible d'obtenir une prediction NLU (model={model_id}): {error}")

    logger.info("parse_message succeeded using model=%s", model_id)
    return {
        "text": text,
        "intent": {"name": prediction.intent, "confidence": prediction.confidence},
        "entities": prediction.entities,
    }


@app.post("/api/chat")
async def send_to_bot(request: ChatRequest, db=Depends(get_db)):
    text = request.text
    sender_id = request.user_id or "frontend_user"
    # Audit observabilite : jusqu'ici, rien ne permettait de relier les logs
    # FastAPI (cette requete) aux logs Rasa/action-server pour le MEME tour de
    # conversation, hors reconstruction manuelle par timestamp. Un identifiant
    # genere ici, journalise a chaque etape et transmis en header vers Rasa,
    # rend cette correlation directe (grep sur trace_id).
    trace_id = str(uuid.uuid4())

    repository = FaqRepository(db)
    faq_service = FaqService(repository)

    # Payload structure (bouton) : contourne le selecteur de modele, aucune
    # classification a faire (voir /api/parse ci-dessus, meme garde-fou).
    is_structured_payload = text.startswith("/")
    intent_name = None

    if not is_structured_payload:
        model_id = request.model or DEFAULT_ENGINE
        try:
            prediction = await nlu_predict(model_id, text)
        except HTTPException as error:
            raise HTTPException(status_code=502, detail=f"Impossible de parser le message (model={model_id}): {error.detail}")
        except Exception as error:
            raise HTTPException(status_code=502, detail=f"Impossible de parser le message (model={model_id}): {error}")

        intent_name = prediction.intent
        logger.info(
            "[trace_id=%s] NLU intent (model=%s): %s (confidence=%.3f)",
            trace_id, model_id, intent_name, prediction.confidence,
        )
        # Egalite stricte (pas "faq" in normalized_intent) : ce test large
        # capturait aussi browse_faq/select_faq_category/select_faq_question
        # (voir rasa/actions/faq.py), qui doivent passer par le webhook Rasa
        # normal ci-dessous (boutons de categorie, cache de suggestions) et
        # non par ce court-circuit de recherche semantique -- celui-ci
        # n'a de sens que pour ask_faq, la seule intention ou le texte tape
        # est une vraie question libre a chercher par embedding.
        if intent_name.lower() == "ask_faq":
            # find_best_answer renvoie desormais un FaqAnswer(question, answer,
            # score) -- l'ancien unpacking a 2 valeurs (faq_answer, score)
            # levait un ValueError sur ce 3-uplet.
            # run_in_threadpool : find_best_answer fait un model.encode() CPU
            # bloquant (voir app/shared/embeddings/service.py) + une requete DB
            # synchrone. Appele tel quel dans cet `async def`, il gelait toute
            # la boucle d'evenements FastAPI pendant son execution -- TOUTES
            # les requetes concurrentes (meme sans rapport avec la FAQ)
            # attendaient, pas seulement celle-ci. Le delegue a un thread du
            # pool le rend non-bloquant pour le reste du serveur.
            faq_match = await run_in_threadpool(faq_service.find_best_answer, text)
            record_faq_lookup(
                db,
                question=text,
                matched_question=faq_match.question if faq_match else None,
                score=faq_match.score if faq_match else None,
                session_id=sender_id,
            )
            if faq_match:
                logger.info(
                    "[trace_id=%s] FAQ answer returned for intent %s with score=%.3f (matched=%r)",
                    trace_id, intent_name, faq_match.score, faq_match.question,
                )
                return {
                    "messages": [
                        {
                            "text": faq_match.answer,
                            "similarity_score": faq_match.score,
                        }
                    ]
                }
            logger.info("[trace_id=%s] Aucune réponse FAQ trouvée pour l'intent %s", trace_id, intent_name)

    # Le webhook Rasa recoit toujours le texte BRUT, quel que soit le moteur
    # NLU selectionne : Core (stories/rules/formulaires -- ex. le formulaire
    # de reclamation, rasa/actions/reclamation.py) s'appuie sur sa propre
    # analyse pour gerer un tour de conversation en cours (remplissage de
    # slot, relance...), un besoin que le moteur choisi ci-dessus ne couvre
    # pas (simple classification d'intention isolee, sans etat conversationnel).
    # Verifie empiriquement : remplacer `text` par une intention synthetique
    # injectee (syntaxe "/intent_name", voir addButtons cote frontend) cassait
    # la poursuite du formulaire de reclamation des que le moteur selectionne
    # classifiait la reponse libre de l'utilisateur autrement que Rasa ne
    # l'aurait fait lui-meme. Le moteur selectionne pilote reellement les deux
    # endroits ou FastAPI decide seul, sans dependre de l'etat de conversation
    # cote Rasa : l'intention/confiance renvoyees par /api/parse, et le
    # raccourci ask_faq ci-dessus.
    try:
        # metadata.superagent : seul canal utilise par ce endpoint pour
        # transporter un signal jusqu'aux actions Rasa qui n'est NI le texte
        # NI une intention -- verifie empiriquement que Rasa preserve
        # `metadata` telle quelle jusque dans tracker.latest_message (voir
        # rasa/actions/common.py::is_superagent_mode).
        rasa_response = await call_rasa_with_retry(
            RASA_WEBHOOK_URL,
            {"sender": sender_id, "message": text, "metadata": {"superagent": request.superagent}},
            headers={"X-Trace-ID": trace_id},
        )
    except HTTPException as error:
        raise HTTPException(status_code=502, detail=f"Impossible de contacter le bot Rasa: {error.detail}")
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Impossible de contacter le bot Rasa: {error}")

    logger.info("[trace_id=%s] send_to_bot succeeded using %s", trace_id, RASA_WEBHOOK_URL)
    return {"messages": rasa_response.json()}


# Monte APRES toutes les routes explicites ci-dessus : Starlette verifie les
# routes dans leur ordre d'enregistrement, donc /api/*, /admin/*, /audit/*,
# /feedback/*, /chat, /docs restent prioritaires sur ce montage generique.
# Aucun fichier de frontend/ ne porte l'un de ces chemins, donc pas de
# collision reelle. html=True sert index.html sur "/".
_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if _FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
else:
    logger.warning("[FastAPI] Dossier frontend/ introuvable (%s) -- montage statique ignore.", _FRONTEND_DIR)
