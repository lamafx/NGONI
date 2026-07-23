# -*- coding: utf-8 -*-
"""Scripte ~100 conversations realistes contre le bot NGONI en direct
(webhook REST Rasa) et sauvegarde chaque transcript en JSON pour analyse.

Usage: python run_conversations.py
"""
import json
import time
import uuid
import requests

WEBHOOK = "http://localhost:5005/webhooks/rest/webhook"
OUT_FILE = "conversations_transcripts.json"

# UUID de test seedes en base (voir seed_test_data.sql) :
U_ACTIVE_KYC_OK = "11111111-0000-0000-0000-000000000001"       # wallet actif, kyc verifie, transactions variees
U_KYC_PENDING = "22222222-0000-0000-0000-000000000002"          # wallet actif mais kyc PAS verifie
U_LIMIT_REACHED = "33333333-0000-0000-0000-000000000003"        # plafond atteint, retrait bloque hors SLA
U_FROZEN = "44444444-0000-0000-0000-000000000004"                # wallet gele
U_KYC_REJECTED = "55555555-0000-0000-0000-000000000005"
U_COMPLIANCE_DEADLINE = "66666666-0000-0000-0000-000000000006"
U_COMPLIANCE_MANUAL_REVIEW = "77777777-0000-0000-0000-000000000007"
U_SUSPENDED = "88888888-0000-0000-0000-000000000008"
U_BANNED = "99999999-0000-0000-0000-000000000009"


def new_id():
    return str(uuid.uuid4())


def send(sender, message):
    try:
        resp = requests.post(WEBHOOK, json={"sender": sender, "message": message}, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        return [{"__error__": str(exc)}]


CONVERSATIONS = []


def conv(cid, category, sender, turns, notes=""):
    CONVERSATIONS.append({"id": cid, "category": category, "sender": sender, "turns": turns, "notes": notes})


# ---------------------------------------------------------------------------
# 1) Diagnostic - retrait (withdrawal_pending) -- 14 conversations
# ---------------------------------------------------------------------------
conv("D01", "diagnostic_withdrawal", U_ACTIVE_KYC_OK,
     ["J'ai fait un retrait hier qui n'a pas abouti."],
     "Extraction tour 1 : verifier que le bot ne redemande pas la date deja donnee")

conv("D02", "diagnostic_withdrawal", U_ACTIVE_KYC_OK,
     ["Mon retrait est bloqué depuis hier.", "WDR-PENDING01"],
     "Reprend l'exemple exact du rapport initial")

conv("D03", "diagnostic_withdrawal", U_ACTIVE_KYC_OK,
     ["Mon retrait de 20000 FCFA d'hier n'est jamais arrivé, référence WDR-FAILED01"],
     "Toutes les infos dans le premier message, y compris la reference -- capture opportuniste par pattern")

conv("D04", "diagnostic_withdrawal", U_ACTIVE_KYC_OK,
     ["Je veux retirer de l'argent mais ça n'a jamais été crédité", "WDR-SUCCESS01"],
     "Cas resolu avec succes (transaction SUCCESS)")

conv("D05", "diagnostic_withdrawal", U_ACTIVE_KYC_OK,
     ["Mon retrait ne passe pas depuis ce matin", "WDR-CANCEL01"],
     "Transaction CANCELLED")

conv("D06", "diagnostic_withdrawal", U_LIMIT_REACHED,
     ["Impossible de retirer mon argent, ça coince depuis hier soir", "WDR-INEXISTANT-9999"],
     "Reference inexistante + plafond atteint -> devrait expliquer le plafond, pas juste 'introuvable'")

conv("D07", "diagnostic_withdrawal", U_FROZEN,
     ["Mon retrait est resté bloqué, pourquoi ?", "WDR-FROZEN01"],
     "Compte gele -- doit mentionner le gel comme cause")

conv("D08", "diagnostic_withdrawal", U_LIMIT_REACHED,
     ["Ça reste bloqué, je n'arrive pas à retirer mon argent.", "WDR-STUCK01"],
     "PENDING au-dela du SLA -- doit escalader et proposer un ticket")

conv("D09", "diagnostic_withdrawal", "00000000-aaaa-0000-0000-000000000000",
     ["Mon retrait n'a jamais été crédité", "WDR-XXXX"],
     "Utilisateur totalement inconnu -- WALLET_NOT_FOUND")

conv("D10", "diagnostic_withdrawal_fallback", U_ACTIVE_KYC_OK,
     ["J'ai fait un retrait hier qui n'a pas abouti.", "je ne l'ai pas", "hier", "15000"],
     "Test cle du Workstream 4 : bascule vers date+montant apres refus de donner la reference")

conv("D11", "diagnostic_withdrawal_fallback", U_ACTIVE_KYC_OK,
     ["Mon retrait de 15000 FCFA d'hier est bloqué", "je n'ai pas ce numéro"],
     "La date/montant deja donnes au tour 1 devraient deja suffire une fois en mode repli (rien a redemander)")

conv("D12", "diagnostic_withdrawal", U_ACTIVE_KYC_OK,
     ["Mon retrait est bloqué et je n'arrive plus à me connecter", "WDR-PENDING01"],
     "Message multi-problemes (retrait + connexion) -- lequel est traite en premier ?")

conv("D13", "diagnostic_withdrawal", U_ACTIVE_KYC_OK,
     ["Bonjour, comment allez-vous ? J'ai fait un retrait hier qui n'a jamais été crédité.", "WDR-PENDING01"],
     "Preambule de politesse avant la vraie description")

conv("D14", "diagnostic_withdrawal", U_ACTIVE_KYC_OK,
     ["Mon retrait est bloqué depuis hier, ça fait plusieurs jours que j'attends, toujours pas résolu", "WDR-STUCK01"],
     "Signal de persistance explicite")

# ---------------------------------------------------------------------------
# 2) Diagnostic - recharge (topup_not_credited) -- 5 conversations
# ---------------------------------------------------------------------------
conv("D15", "diagnostic_topup", U_ACTIVE_KYC_OK,
     ["J'ai rechargé mon compte mais mon solde n'a pas bougé.", "TOPUP-OK01"],
     "Recharge deja creditee (succes)")

conv("D16", "diagnostic_topup", U_ACTIVE_KYC_OK,
     ["Ma recharge n'apparaît pas sur mon solde, l'argent n'a pas été ajouté.", "TOPUP-WAIT01"],
     "Recharge en attente")

conv("D17", "diagnostic_topup", U_ACTIVE_KYC_OK,
     ["J'ai crédité mon wallet mais mon compte ne montre rien de nouveau.", "TOPUP-INCONNU"],
     "Reference inconnue")

conv("D18", "diagnostic_topup", U_ACTIVE_KYC_OK,
     ["Ma recharge de ce matin n'a toujours pas été créditée sur mon compte."],
     "Sans reference au premier message -- doit la redemander")

conv("D19", "diagnostic_topup_fallback", U_ACTIVE_KYC_OK,
     ["J'ai rechargé mais ça n'apparaît pas", "je ne connais pas la référence"],
     "topup_not_credited n'a PAS de fallback_fields declares -- verifier que le bot gere proprement (pas de crash), meme comportement qu'avant Workstream 4")

# ---------------------------------------------------------------------------
# 3) Diagnostic - cadeau (gift_not_received) -- 3 conversations
# ---------------------------------------------------------------------------
conv("D20", "diagnostic_gift", U_ACTIVE_KYC_OK,
     ["J'ai envoyé un cadeau à un ami mais il dit qu'il ne l'a pas reçu.", "GFT-XXXX"],
     "Reference inexistante")

conv("D21", "diagnostic_gift", U_ACTIVE_KYC_OK,
     ["Mon cadeau a débité mes pièces mais n'est jamais arrivé chez le destinataire."],
     "Sans reference")

conv("D22", "diagnostic_gift", U_ACTIVE_KYC_OK,
     ["J'ai offert des pièces à quelqu'un et il ne les a pas reçues.", "je ne l'ai pas"],
     "gift_not_received n'a pas de fallback -- verifier reaction au refus sans repli disponible")

# ---------------------------------------------------------------------------
# 4) Diagnostic - KYC (kyc_status_issue) -- 5 conversations
# ---------------------------------------------------------------------------
conv("D23", "diagnostic_kyc", U_ACTIVE_KYC_OK,
     ["Pourquoi mon KYC est refusé ?"],
     "KYC deja verifie -- doit rassurer, pas dire 'refuse'")

conv("D24", "diagnostic_kyc", U_KYC_PENDING,
     ["Ça fait longtemps que ma vérification d'identité est en attente."],
     "KYC en cours d'examen")

conv("D25", "diagnostic_kyc", U_KYC_REJECTED,
     ["Mon dossier KYC a été rejeté."],
     "KYC rejete avec motif")

conv("D26", "diagnostic_kyc", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
     ["Je n'arrive pas à valider mon identité."],
     "Utilisateur inconnu -- KYC pas encore commence ou USER_NOT_FOUND")

conv("D27", "diagnostic_kyc_vs_compliance", U_ACTIVE_KYC_OK,
     ["Mon compte est bloqué, je ne sais pas pourquoi."],
     "Phrase ambigue KYC vs compliance vs acces bloque -- laquelle gagne ?")

# ---------------------------------------------------------------------------
# 5) Diagnostic - compliance / acces bloque -- 5 conversations
# ---------------------------------------------------------------------------
conv("D28", "diagnostic_compliance", U_COMPLIANCE_DEADLINE,
     ["Ça dit que mon compte est bloqué pour conformité, je ne comprends pas."],
     "Hold actif avec echeance")

conv("D29", "diagnostic_compliance", U_COMPLIANCE_MANUAL_REVIEW,
     ["Mon compte est en attente de vérification conformité (compliance hold)."],
     "Hold necessitant une revue manuelle -- doit escalader")

conv("D30", "diagnostic_account_access", U_SUSPENDED,
     ["Mon compte a été bloqué, je ne sais pas pourquoi."],
     "Compte suspendu")

conv("D31", "diagnostic_account_access", U_BANNED,
     ["Je ne peux plus du tout accéder à mon compte, c'est écrit que je suis banni."],
     "Compte banni -- doit escalader")

conv("D32", "diagnostic_compliance", U_ACTIVE_KYC_OK,
     ["Pourquoi mon compte est sous contrôle ?"],
     "Compte normal -- doit dire qu'aucun blocage n'est actif")

# ---------------------------------------------------------------------------
# 6) Reclamation -- creation, 10 conversations
# ---------------------------------------------------------------------------
conv("R01", "reclamation_creation", new_id(),
     ["Je veux faire une réclamation", "Mon compte KYC a été refusé sans explication depuis 2 semaines", "oui"],
     "Creation simple, categorie deductible de la description")

conv("R02", "reclamation_creation", new_id(),
     ["j'ai un problème avec mon compte", "je n'arrive plus du tout à me connecter depuis hier, mot de passe refusé", "oui"],
     "Categorie Auth deductible")

conv("R03", "reclamation_creation", new_id(),
     ["Je veux signaler un souci", "un autre utilisateur me menace dans le chat, question de sécurité", "oui"],
     "Cas Safety historiquement fragile (audit code, faux positif bot_challenge)")

conv("R04", "reclamation_creation", new_id(),
     ["réclamation", "ça"],
     "Description beaucoup trop vague -- doit redemander, pas planter")

conv("R05", "reclamation_creation", new_id(),
     ["je veux me plaindre", "", "mon compte est bloqué et personne ne répond depuis 3 jours", "oui"],
     "Message vide en cours de formulaire")

conv("R06", "reclamation_creation", new_id(),
     ["Je veux ouvrir un ticket", "j'ai acheté des pièces mais mon achat n'a pas fonctionné correctement", "non", "modifier", "description", "en fait c'est ma recharge qui n'a pas été créditée", "oui"],
     "Correction de description en cours de confirmation")

conv("R07", "reclamation_creation", new_id(),
     ["j'ai un souci avec une vidéo qui ne se charge pas depuis hier", "oui"],
     "Categorie Video, sans passer par 'je veux faire une reclamation' explicitement")

conv("R08", "reclamation_creation", new_id(),
     ["Je veux faire une réclamation", "mon retrait n'a jamais été crédité si ça continue je veux faire une réclamation", "oui"],
     "Avertissement conditionnel deja evoque -- verifier coherence du message final")

conv("R09", "reclamation_creation", new_id(),
     ["plainte", "Fuck ce bot est nul et inutile", "mon compte est bloqué depuis une semaine sans réponse", "oui"],
     "Insulte en cours de formulaire -- ne doit pas casser le flux")

conv("R10", "reclamation_creation", new_id(),
     ["je veux signaler un probleme de parental control pour mon enfant", "oui"],
     "Categorie moins courante (PARENTAL_CONTROL absente de CATEGORY_KEYWORDS ?)")

# ---------------------------------------------------------------------------
# 7) Reclamation -- annulation/modification, 4 conversations
# ---------------------------------------------------------------------------
conv("R11", "reclamation_cancel", new_id(),
     ["Aujourd'hui j'ai effectué un retrait qui n'a pas été effectué", "Votre systeme plante et n'est pas efficace",
      "cest bon laisse tomber", "annuler"],
     "Reprend EXACTEMENT la conversation du rapport initial de l'utilisateur")

conv("R12", "reclamation_cancel", new_id(),
     ["je veux faire une réclamation", "mon compte est bloqué depuis hier sans raison", "non", "modifier", "categorie", "KYC", "oui"],
     "Modification de la categorie avant confirmation")

conv("R13", "reclamation_cancel", new_id(),
     ["plainte", "je n'arrive pas à recharger mon compte depuis avant-hier", "non", "annuler complètement"],
     "Annulation totale directe")

conv("R14", "reclamation_cancel", new_id(),
     ["je veux ouvrir un ticket", "mon retrait est bloqué", "non", "je veux juste changer la date", "modifier", "date", "avant-hier", "oui"],
     "Modification d'un champ moins commun (incident_date)")

# ---------------------------------------------------------------------------
# 8) Consultation des reclamations (Workstream 3) -- 4 conversations
# ---------------------------------------------------------------------------
_r_user1 = new_id()
conv("C01", "ask_complaint_status", _r_user1,
     ["je veux faire une réclamation", "mon retrait de 15000 FCFA d'hier n'est jamais arrivé", "oui",
      "Où en est ma réclamation ?"],
     "Consultation juste apres creation, dans la MEME session")

_r_user2 = new_id()
conv("C02", "ask_complaint_status", _r_user2,
     ["plainte", "mon compte KYC est bloqué depuis 3 jours", "oui",
      "Quel est le statut de ma dernière réclamation ?"],
     "Formulation 'derniere reclamation'")

conv("C03", "ask_complaint_status", new_id(),
     ["Affiche toutes mes réclamations"],
     "Aucune reclamation existante -- doit dire clairement qu'il n'y en a aucune, pas planter")

_r_user3 = new_id()
conv("C04", "ask_complaint_status", _r_user3,
     ["je veux faire une réclamation", "mon retrait n'a jamais été crédité depuis hier", "oui",
      "La réclamation concernant mon retrait a-t-elle avancé ?"],
     "Recherche par sujet/mot-cle dans la liste")

# ---------------------------------------------------------------------------
# 9) FAQ -- 10 conversations
# ---------------------------------------------------------------------------
conv("F01", "faq", new_id(), ["Comment recharger mon compte NGONI ?"], "Question FAQ directe")
conv("F02", "faq", new_id(), ["Qu'est-ce que NGONI Plus ?"], "Question FAQ NGONI Plus")
conv("F03", "faq", new_id(), ["Montre-moi des questions fréquentes"], "browse_faq")
conv("F04", "faq", new_id(), ["Des questions sur le KYC"], "select_faq_category")
conv("F05", "faq", new_id(), ["Combien de temps prend un retrait ?", "oui"], "FAQ puis note utile (bouton simule par texte)")
conv("F06", "faq", new_id(), ["Comment supprimer mon compte NGONI ?"], "Question sensible (suppression compte)")
conv("F07", "faq", new_id(), ["c'est quoi le controle parental sur NGONI"], "Question FAQ avec fautes/minuscules")
conv("F08", "faq", new_id(), ["Question sur un sujet totalement absent de la FAQ, comme la meteo a Paris demain"], "Aucune reponse FAQ trouvee -- verifier le repli")
conv("F09", "faq", new_id(), ["Comment fonctionne le parrainage sur NGONI ?"], "FAQ parrainage")
conv("F10", "faq", new_id(), ["je ne comprends pas comment gagner des pieces sur l'appli"], "FAQ formulee de facon tres familiere")

# ---------------------------------------------------------------------------
# 10) Chitchat / social -- 8 conversations
# ---------------------------------------------------------------------------
conv("S01", "chitchat", new_id(), ["Bonjour"], "Salutation simple")
conv("S02", "chitchat", new_id(), ["Au revoir, merci"], "Au revoir")
conv("S03", "chitchat", new_id(), ["Es-tu un robot ?"], "bot_challenge")
conv("S04", "chitchat", new_id(), ["Qui a conçu ce bot pourri, il devrait revoir sa copie"], "bot_challenge agressif")
conv("S05", "chitchat", new_id(), ["Merci beaucoup, c'était exactement ça"], "Remerciement hors contexte FAQ")
conv("S06", "chitchat", new_id(), ["Que peux-tu faire pour moi ?"], "ask_capabilities")
conv("S07", "chitchat", new_id(), ["Bonsoir, comment allez-vous ?"], "Salutation seule, sans probleme derriere")
conv("S08", "chitchat", new_id(), ["allo ?"], "Message ambigu court (connu pour etre mal classe historiquement)")

# ---------------------------------------------------------------------------
# 11) Edge cases -- 12 conversations
# ---------------------------------------------------------------------------
conv("E01", "edge_case", new_id(), ["fuck"], "Insulte pure, hors contexte")
conv("E02", "edge_case", new_id(), ["azefgzeg zzzz xyzxyz"], "Texte hors-vocabulaire complet")
conv("E03", "edge_case", new_id(), ["."], "Message quasi-vide")
conv("E04", "edge_case", new_id(),
     ["Bonjour, alors voila, depuis maintenant plusieurs semaines j'ai un probleme assez complique a expliquer "
      "avec mon compte, en fait j'ai essaye de faire plusieurs choses, un retrait, une recharge, et aussi "
      "changer mon numero de telephone, et rien de tout ca ne fonctionne correctement, je ne sais meme plus "
      "par ou commencer tellement c'est confus, pouvez vous m'aider s'il vous plait c'est vraiment urgent"],
     "Message tres long et confus, plusieurs problemes meles")
conv("E05", "edge_case", U_ACTIVE_KYC_OK,
     ["Mon retrait est bloqué", "azefgzeg", "WDR-PENDING01"],
     "Reponse hors-sujet au milieu d'une collecte de champ")
conv("E06", "edge_case", U_ACTIVE_KYC_OK,
     ["Mon retrait est bloqué depuis hier", "en fait je voulais plutôt savoir comment fonctionne le parrainage"],
     "Changement de sujet net en cours de diagnostic (FAQ pendant diagnostic)")
conv("E07", "edge_case", new_id(), ["je veux faire une réclamation à propos d'un retrait", "c'est bon merci ça va aller"], "Resolution spontanee en cours de formulaire")
conv("E08", "edge_case", new_id(), ["ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"], "Chaine aleatoire longue")
conv("E09", "edge_case", U_ACTIVE_KYC_OK, ["Mon retrait est bloqué", "je préfère ne pas dire", "WDR-PENDING01"], "Refus explicite puis reponse quand meme plus tard")
conv("E10", "edge_case", new_id(), ["Bonjour comment ça va ? J'ai fait un retrait qui n'a pas abouti et j'ai aussi une question sur le KYC"], "Deux problemes distincts dans un seul message (retrait + kyc)")
conv("E11", "edge_case", new_id(), ["URGENT URGENT je n'arrive pas a recuperer mon argent AIDEZ MOI"], "Ton alarmiste en majuscules")
conv("E12", "edge_case", new_id(), ["test"], "Message de test generique, sans contenu metier")

# ---------------------------------------------------------------------------
# 12) Variantes de classification (paires historiquement fragiles) -- 6
# ---------------------------------------------------------------------------
conv("V01", "classification_stress", U_ACTIVE_KYC_OK, ["mon retrait est resté bloqué, pourquoi ?"], "withdrawal vs compliance/account_access")
conv("V02", "classification_stress", U_KYC_PENDING, ["j'ai soumis mes documents d'identité mais rien ne se passe depuis"], "kyc vs compliance")
conv("V03", "classification_stress", U_ACTIVE_KYC_OK, ["ma recharge de ce matin n'a toujours pas été créditée sur mon compte"], "topup vs withdrawal (mots partages)")
conv("V04", "classification_stress", U_SUSPENDED, ["je ne peux plus rien faire sur mon compte, un message parle de conformité"], "compliance vs account_access (les deux plausibles)")
conv("V05", "classification_stress", U_ACTIVE_KYC_OK, ["j'ai un problème avec mon compte, je n'arrive plus a me connecter et mon KYC semble aussi bloqué"], "auth (reclamation) vs kyc (diagnostic) dans le meme message")
conv("V06", "classification_stress", new_id(), ["ma vérification KYC est bloquée depuis des jours"], "reprend exactement le message du test unitaire qui echoue cote FastAPI (marge trop fine)")

# ---------------------------------------------------------------------------
# 13) Turn-1 extraction -- combinaisons supplementaires -- 4
# ---------------------------------------------------------------------------
conv("T01", "turn1_extraction", U_ACTIVE_KYC_OK, ["Depuis hier j'attends mon retrait de 500 pièces, il reste en attente"], "date+montant+statut des le 1er message, sans reference")
conv("T02", "turn1_extraction", U_ACTIVE_KYC_OK, ["Mon transfert de 200 pièces est bloqué depuis avant-hier", "WDR-PENDING01"], "operation_type=transfer, mais catalogue ne connait que withdrawal/topup/gift -- que se passe-t-il ?")
conv("T03", "turn1_extraction", U_ACTIVE_KYC_OK, ["Mon retrait est en attente depuis trois jours, WDR-STUCK01"], "issue_status + reference dans le meme message")
conv("T04", "turn1_extraction", U_ACTIVE_KYC_OK, ["J'ai fait un retrait le 15 juillet de 8000 FCFA qui reste bloqué", "je ne l'ai pas"], "date explicite (pas relative) + montant + refus reference -> repli direct")

# ---------------------------------------------------------------------------
# 14) Edge cases supplementaires -- 4
# ---------------------------------------------------------------------------
conv("E13", "edge_case", new_id(), ["My withdrawal never arrived, can you help me?"], "Message entierement en anglais")
conv("E14", "edge_case", new_id(), ["mon retrait 😡😡 est bloqué depuis hier 😭"], "Emojis autour d'un vrai message de diagnostic")
conv("E15", "edge_case", U_ACTIVE_KYC_OK, ["retrait bloqué", "hier", "WDR-PENDING01", "oui", "non"], "Reponses tres courtes/telegraphiques enchainees")
conv("E16", "edge_case", new_id(), ["Je veux faire une réclamation", "d'accord laisse tomber en fait"], "Abandon du formulaire des le 2e tour, sans jamais donner de description")

# ---------------------------------------------------------------------------
# 15) Reclamation -- variantes supplementaires -- 3
# ---------------------------------------------------------------------------
conv("R15", "reclamation_creation", new_id(),
     ["je veux faire une réclamation", "mon compte a été suspendu sans aucune explication", "oui", "combien de temps ça va prendre ?"],
     "Question de suivi juste apres la creation, dans la foulee")
conv("R16", "reclamation_creation", new_id(),
     ["plainte", "impossible de me connecter, ça dit mot de passe incorrect alors qu'il est bon", "oui"],
     "Categorie Auth via formulation differente")
conv("R17", "reclamation_creation", new_id(),
     ["j'ai un souci de sécurité, quelqu'un a accédé à mon compte sans autorisation", "oui"],
     "Categorie Safety, contenu sensible (compte pirate)")

# ---------------------------------------------------------------------------
# 16) Consultation reclamations -- variantes supplementaires -- 2
# ---------------------------------------------------------------------------
_r_user4 = new_id()
conv("C05", "ask_complaint_status", _r_user4,
     ["je veux faire une réclamation", "mon compte est suspendu depuis 2 jours", "oui",
      "Quelles sont mes réclamations en cours ?"],
     "Filtre 'en cours' juste apres creation (statut OPEN)")

conv("C06", "ask_complaint_status", new_id(),
     ["Ma réclamation a-t-elle été traitée ?"],
     "Consultation sans avoir jamais rien cree dans cette session (utilisateur inconnu du backend)")

print(f"Total conversations definies : {len(CONVERSATIONS)}")

if __name__ == "__main__":
    results = []
    for i, c in enumerate(CONVERSATIONS, 1):
        print(f"[{i}/{len(CONVERSATIONS)}] {c['id']} ({c['category']}) sender={c['sender'][:8]}...")
        transcript = []
        for turn in c["turns"]:
            responses = send(c["sender"], turn)
            transcript.append({"user": turn, "bot": responses})
            time.sleep(0.15)
        results.append({**c, "transcript": transcript})

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"Termine. {len(results)} conversations sauvegardees dans {OUT_FILE}")
