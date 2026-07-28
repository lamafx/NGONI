from typing import Any, Dict, List, NamedTuple, Optional, Text

from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher

from .common import QUICK_ACTION_BUTTONS, _conversation_is_free, pick
from .diagnostic import _fetch_capabilities


class AgentCapability(NamedTuple):
    description: Text


# Source UNIQUE des modules geres par l'agent : toute reponse qui decrit "ce
# que le bot sait faire" (action_describe_capabilities ci-dessous, et le
# message d'accueil dans greeting.py) lit cette liste, jamais une
# description recopiee en dur dans un utter_message. Ajouter un module (ex.
# un futur suivi de commande) = ajouter une entree ici, aucune autre
# modification necessaire pour que les deux reponses la reprennent.
AGENT_CAPABILITIES: List[AgentCapability] = [
    AgentCapability("répondre à vos questions sur le fonctionnement de NGONI"),
    AgentCapability("vous aider à créer et suivre une réclamation"),
    AgentCapability("effectuer un diagnostic sur certains services"),
    AgentCapability("recueillir vos suggestions et vos remarques"),
]


def _diagnostic_labels() -> Optional[List[Text]]:
    """Libelles humains des problemes diagnosticables, tels que declares par
    chaque manifeste de service (ProblemDefinition.label cote FastAPI) --
    jamais une liste recopiee ici : reflete exactement ce que
    /diagnostic/capabilities renvoie au moment de l'appel, via le meme cache
    que le reste du pipeline diagnostic (voir _fetch_capabilities,
    diagnostic.py). None si le registre est injoignable et qu'aucun cache
    n'est disponible pour amortir la panne -- a distinguer d'une liste vide
    reelle (aucun probleme diagnosticable declare).
    """
    problems = _fetch_capabilities()
    if problems is None:
        return None
    # Deduplique tout en preservant l'ordre d'arrivee -- plusieurs manifestes
    # pourraient en theorie declarer le meme libelle, un set seul perdrait
    # l'ordre, gardé ici pour produire une phrase lisible.
    seen = set()
    labels: List[Text] = []
    for problem in problems:
        label = problem.get("label")
        if label and label not in seen:
            seen.add(label)
            labels.append(label)
    return labels


def _join_naturally(items: List[Text]) -> Text:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " et " + items[-1]


def build_capabilities_message() -> Text:
    # Ton conversationnel (audit UX) : les puces se terminaient auparavant
    # toutes par " ;", y compris la derniere -- lisible comme un document
    # (liste a la Word), pas comme une phrase dite dans une bulle de chat.
    # Retire, et l'intro varie desormais au lieu d'etre toujours identique.
    lines = [
        pick(
            "Je peux vous accompagner sur plusieurs sujets :",
            "Voici ce que je peux faire pour vous :",
            "Je peux notamment vous aider sur ces points :",
        )
    ]
    lines.extend(f"- {capability.description}" for capability in AGENT_CAPABILITIES)

    labels = _diagnostic_labels()
    if labels:
        # Libelles repris tels quels (pas de reformulation grammaticale par
        # probleme) : les transformer proprement ("un probleme de X" avec le
        # bon genre/article) exigerait une connaissance linguistique par
        # libelle, donc une forme de connaissance metier codee en dur --
        # contraire a l'objectif d'une liste entierement pilotee par le
        # registre.
        lines.append(
            "\nConcernant le diagnostic, je peux actuellement analyser les problèmes suivants : "
            f"{_join_naturally(labels)}."
        )
    elif labels is None:
        # Meme principe de non-mensonge que le reste du projet (voir
        # action_create_ticket, action_store_suggestion) : ne jamais
        # affirmer une capacite de diagnostic precise si elle ne peut pas
        # etre confirmee aupres du registre au moment de repondre.
        lines.append(
            "\nLe détail des services diagnosticables est momentanément indisponible, "
            "mais vous pouvez tout de même me décrire votre problème."
        )
    return "\n".join(lines)


class ActionDescribeCapabilities(Action):

    def name(self) -> Text:
        return "action_describe_capabilities"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        # Boutons de relance seulement si aucun flux structure n'est en
        # attente (voir _conversation_is_free, common.py) : ask_capabilities
        # a ses propres variantes de regle "while diagnostic is pending"/
        # "while reclamation form is active" (rules.yml) qui relancent deja
        # le champ ou le formulaire en attente juste apres, dans le meme
        # tour -- y ajouter des boutons generiques serait premature.
        extra = {"buttons": QUICK_ACTION_BUTTONS} if _conversation_is_free(tracker) else {}
        dispatcher.utter_message(text=build_capabilities_message(), **extra)
        return []
