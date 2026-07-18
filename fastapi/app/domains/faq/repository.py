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
        # Audit FAQ #8 : remplace la boucle Python qui rapatriait TOUS les
        # items publies pour calculer chaque similarite cote client. pgvector
        # calcule et trie directement en SQL (`<=>`, distance cosinus sur des
        # vecteurs normalises) -- un seul item transite reseau, pas toute la
        # table. Pas d'index ivfflat/hnsw pour l'instant : premature a la
        # taille actuelle (quelques dizaines d'items), ces index approximatifs
        # sont meme contre-productifs sur une table aussi petite. A ajouter
        # (`CREATE INDEX ... USING ivfflat (embedding vector_cosine_ops)`)
        # si la table grossit significativement.
        distance = FaqItem.embedding.cosine_distance(embedding)
        stmt = (
            select(FaqItem, distance.label("distance"))
            .where(FaqItem.status == FaqStatus.PUBLISHED, FaqItem.locale == locale)
            .order_by(distance)
            .limit(1)
        )
        row = self.session.execute(stmt).first()
        if row is None:
            return None
        item, cosine_distance = row
        return item, 1.0 - float(cosine_distance)

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
