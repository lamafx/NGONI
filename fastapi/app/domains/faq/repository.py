from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import FaqItem, FaqStatus


class FaqRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_all(self) -> List[FaqItem]:
        stmt = select(FaqItem)
        result = self.session.execute(stmt)
        return result.scalars().all()

    def find_random(self, count: int, locale: str = "fr") -> List[FaqItem]:
        # ORDER BY RANDOM() cote SQL, pas un sample() Python sur list_all() :
        # meme raisonnement que find_closest ci-dessous (Audit FAQ #8), un
        # tri aleatoire complet reste largement suffisant a la taille actuelle
        # de la table (quelques dizaines d'items), a revoir si elle grossit
        # significativement (TABLESAMPLE, alternative moins couteuse mais
        # moins uniforme).
        stmt = (
            select(FaqItem)
            .where(FaqItem.status == FaqStatus.PUBLISHED, FaqItem.locale == locale)
            .order_by(func.random())
            .limit(count)
        )
        return self.session.execute(stmt).scalars().all()

    def find_closest(self, embedding: List[float], locale: str = "fr") -> Optional[Tuple[FaqItem, float]]:
        # Cas particulier de find_top_k(k=1) -- conserve comme methode dediee
        # (plutot que d'exiger [0] partout) pour les appelants qui ne veulent
        # reellement que le meilleur candidat (ex. le garde-fou anti-doublon
        # de FaqService.add_faq).
        results = self.find_top_k(embedding, k=1, locale=locale)
        return results[0] if results else None

    def find_top_k(self, embedding: List[float], k: int, locale: str = "fr") -> List[Tuple[FaqItem, float]]:
        # Audit FAQ #8 : remplace la boucle Python qui rapatriait TOUS les
        # items publies pour calculer chaque similarite cote client. pgvector
        # calcule et trie directement en SQL (`<=>`, distance cosinus sur des
        # vecteurs normalises) -- seuls k items transitent reseau, pas toute la
        # table. Pas d'index ivfflat/hnsw pour l'instant : premature a la
        # taille actuelle (quelques dizaines d'items), ces index approximatifs
        # sont meme contre-productifs sur une table aussi petite. A ajouter
        # (`CREATE INDEX ... USING ivfflat (embedding vector_cosine_ops)`)
        # si la table grossit significativement.
        #
        # k > 1 (audit FAQ #8, "vouliez-vous dire...") : FaqService recalcule
        # un score hybride (semantique + mots-cles) sur ces k candidats avant
        # de decider du meilleur -- k doit donc rester assez large pour ne pas
        # exclure a tort un candidat que le seul cosinus aurait sous-classe.
        distance = FaqItem.embedding.cosine_distance(embedding)
        stmt = (
            select(FaqItem, distance.label("distance"))
            .where(FaqItem.status == FaqStatus.PUBLISHED, FaqItem.locale == locale)
            .order_by(distance)
            .limit(k)
        )
        rows = self.session.execute(stmt).all()
        return [(item, 1.0 - float(cosine_distance)) for item, cosine_distance in rows]

    def find_by_slug(self, slug: str) -> Optional[FaqItem]:
        # Utilise par le bouton de suggestion "vouliez-vous dire..." (audit
        # FAQ #8) quand le clic n'a pas la question/reponse deja en cache
        # cote Rasa (contrairement a une categorie parcourue via
        # /faq/suggestions, voir ActionSelectFaqQuestion) : slug unique
        # (contrainte DB), donc au plus une ligne.
        stmt = select(FaqItem).where(FaqItem.slug == slug, FaqItem.status == FaqStatus.PUBLISHED)
        return self.session.execute(stmt).scalars().first()

    def add(self, item: FaqItem) -> FaqItem:
        self.session.add(item)
        self.session.commit()
        self.session.refresh(item)
        return item

    def update_embedding(self, item: FaqItem, embedding: List[float]) -> None:
        # Utilise uniquement par le script de migration ponctuel (voir
        # scripts/reembed_faq.py) lors d'un changement de modele d'embedding :
        # les vecteurs stockes ne sont comparables qu'entre eux s'ils viennent
        # tous du MEME modele, donc un changement de modele exige de tout
        # recalculer, pas seulement les nouveaux items.
        item.embedding = embedding
        self.session.add(item)
        self.session.commit()
