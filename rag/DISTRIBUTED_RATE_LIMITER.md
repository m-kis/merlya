# Rate Limiter Distribué - Migration de Map vers Durable Objects

## Résumé des Changements

Cette migration remplace l'implémentation Map-based rate limiter par une solution distribuée utilisant Cloudflare Durable Objects, permettant le partage des compteurs entre plusieurs instances de Worker.

## Problèmes Corrigés

### 1. Problèmes de Sécurité
- **Avant** : Utilisation de `X-Forwarded-For` qui peut être spoofé
- **Après** : Utilisation exclusive de `CF-Connecting-IP` (fiable via Cloudflare)

### 2. Problèmes de Performance
- **Avant** : Rate limiter scoped à une seule instance Worker
- **Après** : Rate limiter distribué partagé entre toutes les instances

### 3. Problèmes de Robustesse
- **Avant** : Pas de timeout sur les appels OpenAI, modèle obsolète
- **Après** : Timeout de 10s, modèle `gpt-4o-mini` actuel, gestion d'erreurs complète

## Architecture de la Solution

### Durable Object RateLimiter

```typescript
class RateLimiter {
  private state: DurableObjectState;
  private storage: DurableObjectStorage;
  
  // Gestion atomique des compteurs par IP
  // Nettoyage automatique des entrées expirées
  // Persistance distribuée
}
```

### Fonctionnalités Clés

1. **Compteurs Atomiques** : Chaque IP a son propre compteur géré atomiquement
2. **Fenêtres de Temps** : Gestion automatique des reset windows (60s)
3. **Nettoyage Automatique** : Suppression des entrées expirées > 1h
4. **Distribution** : Hash SHA-256 de l'IP pour routing vers DO stable
5. **Fail-Safe** : En cas d'erreur DO, fail-closed pour sécurité

### Configuration Durable Objects

```toml
[[durable_objects.bindings]]
name = "RATE_LIMITER_DO"
class_name = "RateLimiter"

[[migrations]]
tag = "v1"
new_classes = ["RateLimiter"]
```

## Flux de Rate Limiting

1. **Requête entrante** → Extraction IP via `CF-Connecting-IP`
2. **Hash IP** → Génération ID Durable Object stable
3. **Appel DO** → `/check` endpoint avec timeout 5s
4. **Vérification** → Lecture/écriture atomique du compteur
5. **Réponse** → `{allowed, remaining, resetIn}`

## Améliorations de Sécurité

### 1. IP Source Fiable
```typescript
function getClientIP(request: Request): string {
  // SECURITY: Only use CF-Connecting-IP to prevent spoofing
  const cfIP = request.headers.get('CF-Connecting-IP');
  if (!cfIP) {
    console.warn('No CF-Connecting-IP header found');
    return 'unknown';
  }
  return cfIP;
}
```

### 2. Fail-Closed Strategy
```typescript
try {
  // Appel Durable Object
} catch (error) {
  // Network error - fail closed for security
  console.error('Rate limiter error:', error);
  return { allowed: false, remaining: 0, resetIn: 60 };
}
```

## Améliorations de Performance

### 1. Timeout Management
```typescript
const controller = new AbortController();
const timeoutId = setTimeout(() => controller.abort(), 10000);

try {
  const response = await fetch(url, { signal: controller.signal });
} finally {
  clearTimeout(timeoutId);
}
```

### 2. Model Update
```typescript
model: "gpt-4o-mini",  // Updated to current cost-effective model
```

## Tests et Validation

### Compilation TypeScript
```bash
cd rag && npx tsc --noEmit
# ✅ Success: No compilation errors
```

### Déploiement Dry-Run
```bash
cd rag && npx wrangler deploy --dry-run
# ✅ Success: All bindings configured correctly
```

## Configuration Requise

### Variables d'Environnement
- `OPENAI_API_KEY` : Clé API OpenAI
- `CORS_ORIGIN` : Origine CORS autorisée
- `RATE_LIMITER_DO` : Binding Durable Object (auto-généré)

### Permissions Requises
- Accès Durable Objects
- Accès au stockage distribué
- Timeout configuré pour les appels externes

## Migration et Déploiement

### Étapes de Migration

1. **Déploiement Durable Objects**
   ```bash
   npx wrangler deploy
   ```

2. **Migration des Données**
   - Les anciennes entrées Map sont ignorées
   - Nouvelle architecture démarre avec compteurs vides
   - Nettoyage automatique des anciennes données

3. **Validation**
   - Vérifier les métriques de rate limiting
   - Monitorer les performances DO
   - Confirmer la distribution entre instances

### Monitoring

```typescript
// Logs de nettoyage
console.log(`Rate limiter cleanup: removed ${cleanedCount} expired entries`);

// Logs d'erreurs
console.error('Rate limiter DO unavailable:', response.status);
console.error('Rate limiter error:', error);
```

## Avantages de la Solution

### Scalabilité
- ✅ Distribution automatique via hash IP
- ✅ Pas de瓶颈 single Worker
- ✅ Échelle horizontale transparente

### Fiabilité
- ✅ Persistance durable des compteurs
- ✅ Récupération après restart Worker
- ✅ Gestion d'erreurs robuste

### Sécurité
- ✅ IP source fiable (Cloudflare)
- ✅ Compteurs atomiques (pas de race conditions)
- ✅ Fail-closed en cas d'erreur

### Performance
- ✅ Latence optimisée (DO co-located)
- ✅ Timeout pour éviter les blocages
- ✅ Nettoyage automatique de la mémoire

## Considérations Futures

### Optimisations Possibles
1. **Rate Limiting Adaptatif** : Ajustement basé sur la charge
2. **Métriques Avancées** : Dashboards de performance
3. **Cache L2** : Cache local pour IPs fréquentes
4. **Geo-Distribution** : DO dans multiple régions

### Alertes et Monitoring
1. **Taux d'Erreur DO** : Monitoring des unavailable
2. **Latence P95** : Performance des appels DO
3. **Taux de Nettoyage** : Santé du système de cleanup

## Conclusion

Cette migration résout efficacement les limitations du rate limiter Map-based original en fournissant une solution distribuée, sécurisée et robuste pour le rate limiting multi-instance dans Cloudflare Workers.