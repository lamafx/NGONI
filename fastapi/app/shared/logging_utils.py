"""Aide pour journaliser des entites diagnostiques sans exposer leur valeur en
clair (audit robustesse). Les entites d'un diagnostic (voir DiagnosticResolveRequest.entities)
sont un dict libre defini par CHAQUE microservice externe (wallet, user...) --
aucune liste fixe de champs "surs" n'existe cote Engine, et certains champs
courants (montant, reference de transaction, numero de compte...) sont
sensibles sur une plateforme wallet/KYC. Plutot que de maintenir une liste
blanche/noire de noms de champs fragile a chaque nouveau service, on ne
journalise JAMAIS la valeur -- seuls les noms de champs presents restent
visibles (suffisant pour deboguer "quels champs ont ete envoyes", jamais
"quelle etait la valeur").
"""

from typing import Any, Dict


def redact_entities(entities: Dict[str, Any] | None) -> Dict[str, str]:
    if not entities:
        return {}
    return {key: "<redacted>" for key in entities}
