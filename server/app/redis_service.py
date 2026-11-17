"""
Service Redis pour le cache des sessions et des données fréquemment accédées.
"""

import json
import logging
from typing import Any, Optional
from datetime import datetime, timedelta

from .config import settings

logger = logging.getLogger(__name__)

# Try to import redis, but make it optional
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("Redis n'est pas installé. Le cache sera désactivé.")


class RedisService:
    """Service de cache Redis pour les sessions et données fréquentes."""
    
    def __init__(self):
        self.client = None
        self.enabled = settings.redis_enabled and REDIS_AVAILABLE
        
        if self.enabled:
            try:
                self.client = redis.from_url(
                    settings.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True
                )
                # Test connection
                self.client.ping()
                logger.info("Redis connecté avec succès")
            except Exception as e:
                logger.error(f"Échec de connexion à Redis: {e}")
                self.enabled = False
                self.client = None
    
    def is_available(self) -> bool:
        """Vérifie si Redis est disponible."""
        if not self.enabled or not self.client:
            return False
        
        try:
            self.client.ping()
            return True
        except Exception:
            self.enabled = False
            return False
    
    def cache_session(self, session_id: str, user_data: dict, ttl: Optional[int] = None) -> bool:
        """Cache les données de session dans Redis."""
        if not self.is_available():
            return False
        
        try:
            ttl = ttl or settings.session_cache_ttl
            key = f"session:{session_id}"
            self.client.setex(key, ttl, json.dumps(user_data))
            return True
        except Exception as e:
            logger.error(f"Erreur lors du cache de la session: {e}")
            return False
    
    def get_session(self, session_id: str) -> Optional[dict]:
        """Récupère les données de session depuis Redis."""
        if not self.is_available():
            return None
        
        try:
            key = f"session:{session_id}"
            data = self.client.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.error(f"Erreur lors de la récupération de la session: {e}")
        
        return None
    
    def delete_session(self, session_id: str) -> bool:
        """Supprime une session du cache Redis."""
        if not self.is_available():
            return False
        
        try:
            key = f"session:{session_id}"
            self.client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Erreur lors de la suppression de la session: {e}")
            return False
    
    def cache_user_data(self, user_id: str, data: dict, ttl: int = 300) -> bool:
        """Cache les données utilisateur fréquemment accédées."""
        if not self.is_available():
            return False
        
        try:
            key = f"user:{user_id}:data"
            self.client.setex(key, ttl, json.dumps(data))
            return True
        except Exception as e:
            logger.error(f"Erreur lors du cache des données utilisateur: {e}")
            return False
    
    def get_user_data(self, user_id: str) -> Optional[dict]:
        """Récupère les données utilisateur depuis le cache."""
        if not self.is_available():
            return None
        
        try:
            key = f"user:{user_id}:data"
            data = self.client.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des données utilisateur: {e}")
        
        return None
    
    def invalidate_user_cache(self, user_id: str) -> bool:
        """Invalide le cache pour un utilisateur."""
        if not self.is_available():
            return False
        
        try:
            pattern = f"user:{user_id}:*"
            keys = self.client.keys(pattern)
            if keys:
                self.client.delete(*keys)
            return True
        except Exception as e:
            logger.error(f"Erreur lors de l'invalidation du cache utilisateur: {e}")
            return False
    
    def cache_auth_attempt(self, identifier: str, count: int, ttl: int = 300) -> bool:
        """Cache les tentatives d'authentification pour prévenir les attaques par force brute."""
        if not self.is_available():
            return False
        
        try:
            key = f"auth:attempts:{identifier}"
            self.client.setex(key, ttl, str(count))
            return True
        except Exception as e:
            logger.error(f"Erreur lors du cache des tentatives d'auth: {e}")
            return False
    
    def get_auth_attempts(self, identifier: str) -> int:
        """Récupère le nombre de tentatives d'authentification."""
        if not self.is_available():
            return 0
        
        try:
            key = f"auth:attempts:{identifier}"
            count = self.client.get(key)
            return int(count) if count else 0
        except Exception:
            return 0
    
    def clear_auth_attempts(self, identifier: str) -> bool:
        """Efface le compteur de tentatives d'authentification."""
        if not self.is_available():
            return False
        
        try:
            key = f"auth:attempts:{identifier}"
            self.client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Erreur lors de l'effacement des tentatives d'auth: {e}")
            return False


# Instance globale du service Redis
redis_service = RedisService()