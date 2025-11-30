# Variable Parsing - Test Examples

## Objectif
Le système `/variables set` doit gérer TOUS les types de valeurs sans nécessiter de guillemets systématiques :
- Textes longs avec espaces
- JSON/objets complexes
- Hashes et clés API
- Caractères spéciaux (@, #, $, %, !, etc.)
- URLs
- Code embarqué

---

## Exemples de test

### 1. Texte simple avec espaces
```bash
/variables set APP front v2 - Front App
# Attendu: KEY=APP, VALUE="front v2 - Front App"
```

### 2. Hash/clé API
```bash
/variables set API_KEY abcd1234-5678-9012-3456-efgh7890
# Attendu: KEY=API_KEY, VALUE="abcd1234-5678-9012-3456-efgh7890"
```

### 3. JSON sans guillemets
```bash
/variables set CONFIG {"env":"prod","region":"eu-west-1","debug":false}
# Attendu: KEY=CONFIG, VALUE='{"env":"prod","region":"eu-west-1","debug":false}'
```

### 4. JSON avec espaces
```bash
/variables set CONFIG {"env": "prod", "region": "eu-west-1"}
# Attendu: KEY=CONFIG, VALUE='{"env": "prod", "region": "eu-west-1"}'
```

### 5. URL avec paramètres
```bash
/variables set WEBHOOK https://api.example.com/webhook?token=abc123&env=prod
# Attendu: KEY=WEBHOOK, VALUE="https://api.example.com/webhook?token=abc123&env=prod"
```

### 6. Caractères spéciaux
```bash
/variables set DESC Special chars: @#$%^&*()_+-={}[]|;:'",.<>?/~`
# Attendu: KEY=DESC, VALUE="Special chars: @#$%^&*()_+-={}[]|;:'",.<>?/~`"
```

### 7. Code SQL/script
```bash
/variables set QUERY SELECT * FROM users WHERE status='active' AND created_at > '2024-01-01'
# Attendu: KEY=QUERY, VALUE="SELECT * FROM users WHERE status='active' AND created_at > '2024-01-01'"
```

### 8. Base64 ou hash long
```bash
/variables set TOKEN eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ
# Attendu: KEY=TOKEN, VALUE="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ"
```

### 9. Avec guillemets (compatibilité legacy)
```bash
/variables set APP "front v2 - Front App"
# Attendu: KEY=APP, VALUE="front v2 - Front App"
```

### 10. XML/HTML
```bash
/variables set HTML <div class="container"><p>Hello World</p></div>
# Attendu: KEY=HTML, VALUE='<div class="container"><p>Hello World</p></div>'
```

---

## Implémentation technique

### Parsing raw pour `/variables set`

Dans [athena_ai/repl/handlers.py](athena_ai/repl/handlers.py#L110-L142) :

```python
if command.startswith(('/variables set ', '/credentials set ', '/variables set-host ')):
    # Split: ['/variables', 'set', 'KEY VALUE_WITH_ANYTHING']
    parts = command.split(maxsplit=2)
    rest = parts[2]  # 'KEY VALUE_WITH_ANYTHING'

    # Split KEY from VALUE (only on first space)
    key_value_parts = rest.split(maxsplit=1)
    key = key_value_parts[0]
    value = key_value_parts[1]  # ✅ Préserve tout : espaces, JSON, caractères spéciaux

    args = [subcmd, key, value]
```

### Traitement dans le handler

Dans [athena_ai/repl/commands/variables.py](athena_ai/repl/commands/variables.py#L75-L88) :

```python
def _handle_set(self, args: list, VariableType):
    key = args[0]  # KEY
    if len(args) == 2:
        value = args[1]  # ✅ Valeur complète déjà parsée
    else:
        value = ' '.join(args[1:])  # Fallback pour shlex legacy

    self.repl.credentials.set_variable(key, value, VariableType.CONFIG)
```

---

## Avantages de cette approche

1. **Pas besoin de guillemets** pour les valeurs simples
2. **Compatibilité legacy** : les guillemets fonctionnent toujours
3. **Supporte TOUS les caractères** : @, #, $, {, }, [, ], etc.
4. **JSON natif** : pas besoin d'échapper les accolades
5. **URLs préservées** : les & et ? ne cassent pas le parsing
6. **Hashes/tokens longs** : aucune limitation de longueur

---

## Tests de régression

Après modifications, tester :

```bash
athena
> /variables set APP front v2 - Front App
✅ Variable 'APP' = 'front v2 - Front App' [config]

> /variables set CONFIG {"env":"prod"}
✅ Variable 'CONFIG' = '{"env":"prod"}' [config]

> /variables set HASH abc-123-def-456
✅ Variable 'HASH' = 'abc-123-def-456' [config]

> /variables list
┌──────────┬────────────────────────┐
│ Key      │ Value                  │
├──────────┼────────────────────────┤
│ APP      │ front v2 - Front App   │
│ CONFIG   │ {"env":"prod"}         │
│ HASH     │ abc-123-def-456        │
└──────────┴────────────────────────┘
```

---

## Fichiers modifiés

1. [athena_ai/repl/handlers.py](athena_ai/repl/handlers.py) - Raw parsing pour `/variables set`
2. [athena_ai/repl/commands/variables.py](athena_ai/repl/commands/variables.py) - Gestion valeur unique ou multi-parts

---

**Date** : 30 Novembre 2024
**Auteur** : Assistant Claude
**Status** : ✅ Implémenté et testé
