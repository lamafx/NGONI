# -*- coding: utf-8 -*-
import json

data = json.load(open("conversations_transcripts.json", encoding="utf-8"))

lines = []
flags = []

FALLBACK_MARKERS = [
    "je n'ai pas bien compris", "je n'ai pas réussi à rattacher",
    "erreur interne", "difficulté pour accéder", "réessayer",
]

for c in data:
    lines.append(f"=== {c['id']} [{c['category']}] === {c['notes']}")
    prev_bot_texts = []
    for turn in c["transcript"]:
        lines.append(f"  U: {turn['user']}")
        bot = turn["bot"]
        if not bot:
            lines.append("  B: <<AUCUNE REPONSE>>")
            flags.append((c["id"], "AUCUNE_REPONSE", turn["user"]))
            continue
        for msg in bot:
            if "__error__" in msg:
                lines.append(f"  B: <<ERREUR REQUETE: {msg['__error__']}>>")
                flags.append((c["id"], "ERREUR_REQUETE", msg["__error__"]))
                continue
            text = msg.get("text", "")
            buttons = msg.get("buttons")
            if text:
                lines.append(f"  B: {text}")
                if text in prev_bot_texts:
                    flags.append((c["id"], "REPETITION_EXACTE", text[:80]))
                prev_bot_texts.append(text)
                for marker in FALLBACK_MARKERS:
                    if marker in text.lower():
                        flags.append((c["id"], "MARQUEUR:" + marker, text[:100]))
            if buttons:
                lines.append(f"     [boutons: {[b['title'] for b in buttons]}]")
    lines.append("")

with open("transcripts_summary.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

with open("auto_flags.txt", "w", encoding="utf-8") as f:
    for cid, kind, detail in flags:
        f.write(f"{cid}\t{kind}\t{detail}\n")

print(f"{len(data)} conversations, {len(flags)} signalements automatiques")
