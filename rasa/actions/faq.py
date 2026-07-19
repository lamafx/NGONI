import json
import uuid
from os import getenv
from typing import Any, Dict, List, Optional, Text, Tuple

import requests
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher

FAQ_SERVICE_URL = getenv("FAQ_SERVICE_URL", "http://fastapi:8000/faq/search")
FAQ_SUGGESTIONS_SERVICE_URL = getenv("FAQ_SUGGESTIONS_SERVICE_URL", "http://fastapi:8000/faq/suggestions")
FAQ_SUGGESTIONS_COUNT = 10

# Libelles francais des valeurs de core.FaqCategory (voir
# app/domains/faq/models.py) : utilises comme titres de boutons de categorie
# (fetch_faq_category_buttons) plutot que les noms d'enum bruts (ex.
# "NGONI_PLUS").
FAQ_CATEGORY_LABELS: Dict[Text, Text] = {
    "ACCOUNT": "Compte",
    "WALLET": "Portefeuille",
    "COINS": "Pièces",
    "VPP": "Vidéos Privées Payantes",
    "LPP": "Lives Privés Payants",
    "WITHDRAWAL": "Retraits",
    "NGONI_PLUS": "NGONI Plus",
    "KYC": "Vérification d'identité (KYC)",
    "PARENTAL_CONTROL": "Contrôle parental",
    "GIFTS": "Cadeaux",
    "ASSISTANCE": "Assistance",
    "GENERAL": "Général",
}


def _present_answer(
    dispatcher: CollectingDispatcher, tracker: Tracker, question: Text, answer: Text
) -> List[Dict[Text, Any]]:
    # Presentation pure (aucun appel reseau) : partagee par _present_faq_answer
    # ci-dessous (question tapee au clavier, reponse resolue via /faq/search)
    # et ActionSelectFaqQuestion (question choisie via un bouton, deja
    # accompagnee de sa reponse dans le cache faq_suggestions_cache -- voir
    # fetch_faq_category_buttons) : les deux doivent produire exactement la meme
    # experience de reponse + notation, seule la provenance de `answer`
    # differe (recherche semantique vs cache local).
    #
    # Reponse + demande de notation dans un seul utter_message : un seul
    # objet message dans la reponse HTTP du webhook REST pour ce tour, rien
    # qu'un client puisse etaler dans le temps pour simuler un effet
    # "streaming". Demande de notation (voir action_record_response_rating,
    # feedback.py) uniquement ici : impossible de noter utilement une reponse
    # qui n'existe pas ou un service en panne (voir _present_faq_answer).
    #
    # Audit robustesse (fluidite de la conversation) : question/answer
    # etaient auparavant memorises dans des slots UNIQUES (pending_rating_*),
    # ecrases par la PROCHAINE reponse FAQ si l'utilisateur ne notait pas la
    # premiere avant d'en demander une seconde -- cliquer un bouton "perime"
    # notait alors silencieusement la MAUVAISE reponse. Chaque reponse recoit
    # desormais sa propre reference courte (rating_ref), encodee dans le
    # payload de SES boutons et utilisee comme cle dans le dict pending_ratings
    # (slot unique, mais MERGE plutot qu'ecrasement) -- plusieurs notations en
    # attente coexistent sans se marcher dessus.
    rating_ref = uuid.uuid4().hex[:8]
    try:
        pending_ratings = json.loads(tracker.get_slot("pending_ratings") or "{}")
        if not isinstance(pending_ratings, dict):
            pending_ratings = {}
    except ValueError:
        pending_ratings = {}
    pending_ratings[rating_ref] = {"type": "faq", "question": question, "answer": answer}

    dispatcher.utter_message(
        text=f"{answer}\n\nCette réponse vous a-t-elle été utile ?",
        buttons=[
            {"title": "👍 Utile", "payload": f'/rate_response_useful{{"rating_ref": "{rating_ref}"}}'},
            {"title": "👎 Pas utile", "payload": f'/rate_response_not_useful{{"rating_ref": "{rating_ref}"}}'},
        ],
    )
    return [{"event": "slot", "name": "pending_ratings", "value": json.dumps(pending_ratings, ensure_ascii=False)}]


def _present_faq_answer(
    dispatcher: CollectingDispatcher, tracker: Tracker, user_question: Text
) -> List[Dict[Text, Any]]:
    # Point d'entree pour une question tapee au clavier (ActionFaqSearch) :
    # contrairement a une question choisie via bouton (deja accompagnee de sa
    # reponse, voir ActionSelectFaqQuestion), une question libre doit passer
    # par la recherche semantique /faq/search pour trouver sa reponse.
    try:
        response = requests.post(
            FAQ_SERVICE_URL,
            json={"question": user_question},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()

        answer = payload.get("answer") or payload.get("response") or payload.get("result")

        if answer:
            return _present_answer(dispatcher, tracker, user_question, answer)
        else:
            # Audit ton/clarite : utter_faq_not_found/utter_faq_error
            # (domain.yml) etaient definies mais jamais utilisees -- ce texte
            # inline dupliquait le second, et le premier promettait "je peux
            # vous mettre en relation avec le support", sans qu'aucun
            # mecanisme ne permette reellement d'accepter cette offre
            # (impasse conversationnelle). Route desormais vers ces reponses
            # existantes, qui ne font pas cette promesse.
            dispatcher.utter_message(response="utter_faq_not_found")
    except requests.RequestException:
        dispatcher.utter_message(response="utter_faq_error")

    return []


class ActionFaqSearch(Action):

    def name(self) -> Text:
        return "action_faq_search"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        user_question = tracker.latest_message.get("text")

        if not user_question:
            dispatcher.utter_message(text="Je n'ai pas reçu de question.")
            return []

        return _present_faq_answer(dispatcher, tracker, user_question)


def _fetch_faq_suggestions(count: int = FAQ_SUGGESTIONS_COUNT) -> Optional[List[Dict[Text, Any]]]:
    # None distingue une panne/reponse invalide (fetch_faq_category_buttons
    # affiche un message d'erreur) d'une liste simplement vide (aucune
    # categorie publiee) -- meme raisonnement que find_best_answer cote
    # FastAPI (service.py) pour ses propres cas None.
    try:
        response = requests.get(FAQ_SUGGESTIONS_SERVICE_URL, params={"count": count}, timeout=5)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return None
    categories = payload.get("categories")
    return categories if isinstance(categories, list) else None


def fetch_faq_category_buttons(
    tracker: Tracker,
) -> Tuple[Optional[List[Dict[Text, Any]]], List[Dict[Text, Any]]]:
    # Factorise entre ActionGreetWithTime (greeting.py -- categories
    # affichees directement dans le message d'accueil) et ActionBrowseFaq
    # (reprise de la decouverte FAQ en cours de conversation, ex. l'utilisateur
    # tape "montre-moi des questions" plus tard) : les deux doivent proposer
    # les memes boutons de categorie et mettre en cache le meme tirage dans
    # faq_suggestions_cache, pour que ActionSelectFaqCategory reste coherent
    # avec ce qui a ete affiche.
    #
    # Audit robustesse : cette coherence etait DECRITE ici mais jamais
    # implementee -- chaque appel refaisait un tirage aleatoire et ECRASAIT
    # le cache de l'AUTRE point d'entree, meme quand un tirage recent et
    # encore valide existait deja. Un bouton de categorie affiche par l'un
    # des deux pouvait alors renvoyer "cette categorie n'est plus disponible"
    # des que l'autre avait ecrase le cache entre-temps. Reutilise desormais
    # le cache existant s'il y en a un, plutot que d'en refaire un nouveau a
    # chaque appel.
    try:
        cached = json.loads(tracker.get_slot("faq_suggestions_cache") or "null")
    except ValueError:
        cached = None
    categories = cached if isinstance(cached, list) and cached else _fetch_faq_suggestions()

    if not categories:
        return None, [{"event": "slot", "name": "faq_suggestions_cache", "value": "{}"}]

    buttons = [
        {
            "title": FAQ_CATEGORY_LABELS.get(group["category"], group["category"]),
            "payload": f'/select_faq_category{{"faq_category": "{group["category"]}"}}',
        }
        for group in categories
        if group.get("questions")
    ]
    cache_event = {
        "event": "slot",
        "name": "faq_suggestions_cache",
        "value": json.dumps(categories, ensure_ascii=False),
    }
    return buttons, [cache_event]


class ActionBrowseFaq(Action):
    # Declenchee par l'intention browse_faq (ex. l'utilisateur tape "montre-
    # moi des questions frequentes" en cours de conversation) : les
    # categories sont normalement deja affichees directement dans le message
    # d'accueil (voir action_greet_with_time, greeting.py), cette action sert
    # a les reafficher/rafraichir a la demande.

    def name(self) -> Text:
        return "action_browse_faq"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        buttons, events = fetch_faq_category_buttons(tracker)

        if buttons is None:
            dispatcher.utter_message(
                text="Désolé, aucune question fréquente n'est disponible pour le moment."
            )
        else:
            dispatcher.utter_message(
                text="Choisissez une catégorie pour voir des exemples de questions :", buttons=buttons
            )

        return events


class ActionSelectFaqCategory(Action):
    # Declenchee par un bouton de categorie (payload
    # /select_faq_category{"faq_category": "..."}), affiche soit directement
    # dans l'accueil (ActionGreetWithTime) soit par ActionBrowseFaq : deplie
    # cette categorie en boutons de questions, a partir du cache pose par
    # fetch_faq_category_buttons (pas un nouvel appel reseau).

    def name(self) -> Text:
        return "action_select_faq_category"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        entities = tracker.latest_message.get("entities") or []
        faq_category = next((e["value"] for e in entities if e.get("entity") == "faq_category"), None)

        try:
            categories = json.loads(tracker.get_slot("faq_suggestions_cache") or "{}")
        except ValueError:
            categories = None

        questions = next(
            (group.get("questions", []) for group in (categories or []) if group.get("category") == faq_category),
            [],
        ) if isinstance(categories, list) else []

        if not faq_category or not questions:
            dispatcher.utter_message(text="Cette catégorie n'est plus disponible, vous pouvez en choisir une autre.")
            return []

        buttons = [
            {
                "title": question["question"],
                "payload": f'/select_faq_question{{"faq_slug": "{question["slug"]}"}}',
            }
            for question in questions
        ]

        dispatcher.utter_message(text="Cliquez sur une question, ou tapez la vôtre directement :", buttons=buttons)
        return []


class ActionSelectFaqQuestion(Action):
    # Declenchee par un bouton de question envoye par
    # ActionSelectFaqCategory (payload /select_faq_question{"faq_slug": "..."})
    # : la reponse est deja presente dans le cache faq_suggestions_cache
    # (pose par fetch_faq_category_buttons, /faq/suggestions renvoie
    # desormais aussi la reponse de chaque question) -- aucun appel a
    # /faq/search ni requete
    # supplementaire vers la base, contrairement a ActionFaqSearch (question
    # libre tapee au clavier, qui doit passer par la recherche semantique).

    def name(self) -> Text:
        return "action_select_faq_question"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        entities = tracker.latest_message.get("entities") or []
        faq_slug = next((e["value"] for e in entities if e.get("entity") == "faq_slug"), None)

        try:
            categories = json.loads(tracker.get_slot("faq_suggestions_cache") or "{}")
        except ValueError:
            categories = None

        question_text = None
        answer_text = None
        if faq_slug and isinstance(categories, list):
            for group in categories:
                for question in group.get("questions", []):
                    if question.get("slug") == faq_slug:
                        question_text = question.get("question")
                        answer_text = question.get("answer")
                        break
                if question_text:
                    break

        if not question_text or not answer_text:
            dispatcher.utter_message(text="Cette question n'est plus disponible, vous pouvez la reformuler.")
            return []

        return _present_answer(dispatcher, tracker, question_text, answer_text)
