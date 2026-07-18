from os import getenv
from typing import Any, Dict, List, Optional, Text

import requests
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher

from .common import pick

FEEDBACK_SERVICE_URL = getenv("FEEDBACK_SERVICE_URL", "http://fastapi:8000/feedback")
# Sous-ressource de FEEDBACK_SERVICE_URL (pas une variable d'environnement
# separee) : /feedback/ratings vit dans le meme domaine FastAPI que /feedback,
# voir app/domains/feedback/router.py.
RATING_SERVICE_URL = f"{FEEDBACK_SERVICE_URL}/ratings"


def _submit_feedback(tracker: Tracker, feedback_type: Text) -> Optional[Dict[str, Any]]:
    # Retourne le corps JSON de la reponse (contient "ticket_id" pour
    # suggestion/complaint_sentiment, voir app/domains/feedback/service.py)
    # plutot qu'un simple bool -- necessaire pour que le bot puisse
    # communiquer la reference du ticket cree cote FastAPI.
    text = tracker.latest_message.get("text") or ""
    if not text.strip():
        return None
    payload = {
        "type": feedback_type,
        "message": text,
        "user_id": tracker.sender_id,
    }
    try:
        response = requests.post(FEEDBACK_SERVICE_URL, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError):
        return None


class ActionStoreSuggestion(Action):
    # Remplace l'ancien appel direct a utter_thanks_for_suggestion (voir
    # docs/suggestion-plainte-flow.md) : ce dernier promettait une
    # transmission a l'equipe qui n'existait pas. FastAPI cree desormais
    # reellement un ticket de suivi (complaints.complaints) en plus de
    # l'entree feedback.entries -- la reponse mentionne sa reference quand
    # disponible, et retombe sur le message generique sinon (echec best-
    # effort de la creation de ticket, ou service indisponible).
    def name(self) -> Text:
        return "action_store_suggestion"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        result = _submit_feedback(tracker, "suggestion")
        if result is None:
            dispatcher.utter_message(response="utter_suggestion_storage_failed")
            return []
        ticket_id = result.get("ticket_id")
        if ticket_id:
            # Formulations variees (pas de dispatcher.utter_message(text=f"...")
            # fige) : trouve par test conversationnel (400 tests suggestion,
            # 2026-07-18) -- ce message revenait mot pour mot identique sur
            # 330 suggestions distinctes (seule la reference variait), la
            # branche utter_thanks_for_suggestion (avec ses propres variantes,
            # domain.yml) n'etant jamais atteinte en pratique des qu'un ticket
            # est cree avec succes -- le cas courant.
            dispatcher.utter_message(
                text=pick(
                    f"Merci pour votre suggestion ! Je la transmets à notre équipe pour étude (référence : {ticket_id}).",
                    f"C'est noté, merci ! Votre suggestion est transmise à notre équipe (référence : {ticket_id}).",
                    f"Merci, bonne idée : je la fais remonter à notre équipe (référence : {ticket_id}).",
                )
            )
        else:
            dispatcher.utter_message(response="utter_thanks_for_suggestion")
        return []


class ActionAcknowledgeComplaint(Action):
    # Depuis l'ajout de la creation automatique de ticket (voir
    # app/domains/feedback/service.py), une plainte cree desormais un ticket
    # de suivi (complaints.complaints) en plus de l'entree feedback.entries.
    # Le message reste best-effort : sa formulation depend de la presence
    # d'un ticket_id reel dans la reponse, jamais d'une supposition -- si la
    # persistance echoue completement (service indisponible ou creation de
    # ticket en echec), on retombe sur le message d'origine, qui n'a jamais
    # pretendu qu'un ticket existait.
    def name(self) -> Text:
        return "action_acknowledge_complaint"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        result = _submit_feedback(tracker, "complaint_sentiment")
        ticket_id = (result or {}).get("ticket_id")
        if ticket_id:
            # Memes raisons que ActionStoreSuggestion ci-dessus : ce message
            # revenait identique sur 103 plaintes distinctes lors du test
            # conversationnel (400 tests plainte, 2026-07-18).
            dispatcher.utter_message(
                text=pick(
                    "Je suis désolé que vous ne soyez pas satisfait. "
                    f"J'ai transmis votre remarque à notre équipe (référence : {ticket_id}). "
                    "Si vous souhaitez un suivi personnalisé, dites-le-moi et j'ouvre une réclamation.",

                    "Je comprends votre frustration. "
                    f"Votre remarque a bien été transmise à notre équipe (référence : {ticket_id}). "
                    "Dites-le-moi si vous voulez un suivi personnalisé, j'ouvre une réclamation.",

                    "Merci de nous en faire part, je suis désolé pour ce désagrément. "
                    f"C'est transmis à notre équipe (référence : {ticket_id}). "
                    "N'hésitez pas à demander un suivi personnalisé si besoin.",
                )
            )
        else:
            dispatcher.utter_message(response="utter_acknowledge_complaint")
        return []


class ActionRecordResponseRating(Action):
    # Declenchee par les boutons "Utile"/"Pas utile" affiches apres une
    # reponse FAQ (voir ActionFaqSearch, faq.py), via les payloads structures
    # /rate_response_useful et /rate_response_not_useful -- une seule action
    # pour les deux, qui lit l'intention du tour courant pour savoir laquelle
    # a ete cliquee, plutot que deux actions quasi identiques.
    def name(self) -> Text:
        return "action_record_response_rating"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        interaction_type = tracker.get_slot("pending_rating_type")
        question = tracker.get_slot("pending_rating_question")
        answer = tracker.get_slot("pending_rating_answer")

        reset_events = [
            {"event": "slot", "name": "pending_rating_type", "value": None},
            {"event": "slot", "name": "pending_rating_question", "value": None},
            {"event": "slot", "name": "pending_rating_answer", "value": None},
        ]

        if not interaction_type or not question or not answer:
            # Notation recue hors contexte (ex. l'utilisateur tape "c'etait
            # utile" sans qu'aucune reponse recente n'attende de retour, ou
            # un bouton perime clique apres qu'une autre notation ait deja
            # vide ces slots) : rien de precis a persister, mais on reste
            # courtois plutot que de laisser le message sans reponse.
            dispatcher.utter_message(response="utter_thanks_for_rating")
            return reset_events

        # Meme convention que le reste du pipeline diagnostic/reclamation
        # pour lire l'intention du tour courant (voir diagnostic.py).
        intent_name = (tracker.latest_message.get("intent") or {}).get("name")
        is_useful = intent_name == "rate_response_useful"

        payload = {
            "interaction_type": interaction_type,
            "question": question,
            "answer": answer,
            "is_useful": is_useful,
            "user_id": tracker.sender_id,
        }
        try:
            response = requests.post(RATING_SERVICE_URL, json=payload, timeout=10)
            response.raise_for_status()
            dispatcher.utter_message(response="utter_thanks_for_rating")
        except requests.RequestException:
            dispatcher.utter_message(response="utter_rating_storage_failed")

        return reset_events
