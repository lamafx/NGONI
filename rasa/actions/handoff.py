"""Actions liees a la mise en relation avec un conseiller humain.

Une seule action pour l'instant : ANNULER une demande de conseiller encore
en attente. Le sens inverse (demander un conseiller) n'a pas besoin d'action
-- `utter_ask_human_reason` (voir la regle "Human agent request response"
dans data/rules.yml) demande d'abord la raison, et c'est la creation du
ticket qui met reellement la conversation dans la file des conseillers,
cote FastAPI (voir domains/complaints/router.py).

Ici, en revanche, il faut ecrire quelque part : sans appel au moteur, dire
"c'est annule" a l'usager serait un mensonge -- la conversation resterait
dans la file du conseiller.
"""

import logging
from os import getenv
from typing import Any, Dict, List, Text

import requests
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher

logger = logging.getLogger(__name__)

WITHDRAW_SERVICE_URL = getenv(
    "WITHDRAW_SERVICE_URL", "http://fastapi:8000/conversations/withdraw"
)
# Meme ordre de grandeur que les autres appels sortants de ce serveur
# d'actions (voir faq.py / feedback.py) : au-dela, mieux vaut repondre
# honnetement que faire attendre l'usager.
REQUEST_TIMEOUT_SECONDS = 10


class ActionCancelHumanAgentRequest(Action):
    """« Finalement, laisse tomber le conseiller. »

    Trois issues possibles, et chacune se dit differemment :
      - la demande est retiree -> l'assistant reprend simplement ;
      - un conseiller a DEJA pris le dossier -> on ne l'efface pas de sa
        file dans son dos, on le dit ;
      - le moteur ne repond pas -> on ne pretend pas avoir annule quoi que
        ce soit.
    """

    def name(self) -> Text:
        return "action_cancel_human_agent_request"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        try:
            response = requests.post(
                WITHDRAW_SERVICE_URL,
                json={
                    # sender_id = identifiant de la conversation cote moteur
                    # (voir domains/conversations/models.py) : c'est la meme
                    # cle des deux cotes, aucune correspondance a maintenir.
                    "conversation_id": tracker.sender_id,
                    "reason": "annulee_par_usager",
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            result = response.json()
        except requests.RequestException as error:
            logger.warning("[HANDOFF] Retrait de la demande impossible : %s", error)
            dispatcher.utter_message(
                text=(
                    "Je n'arrive pas à mettre à jour votre demande pour le moment. "
                    "Si un conseiller vous contacte malgré tout, dites-lui simplement "
                    "que votre problème est réglé."
                )
            )
            return []
        except ValueError as error:  # reponse non-JSON
            logger.warning("[HANDOFF] Reponse inattendue du moteur : %s", error)
            dispatcher.utter_message(
                text="Je n'arrive pas à mettre à jour votre demande pour le moment."
            )
            return []

        if result.get("withdrawn"):
            dispatcher.utter_message(
                text=(
                    "C'est noté, je retire votre demande de mise en relation. "
                    "Je reste à votre disposition — dites-moi ce dont vous avez besoin."
                )
            )
        else:
            dispatcher.utter_message(
                text=(
                    "Un conseiller a déjà pris votre dossier en charge : je préfère "
                    "le laisser vous répondre plutôt que d'annuler sans le prévenir. "
                    "Vous pourrez le lui dire directement."
                )
            )
        return []
