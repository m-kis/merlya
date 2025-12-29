# Démarrage rapide

Lancez Merlya en 5 minutes.

<a id="setup-wizard"></a>

## 1. Premier lancement - Assistant de configuration

Au premier lancement, l'assistant de configuration de Merlya vous guide :

```bash
merlya
```

### Sélection de la langue

```
╭─────────────────────────────────────────────────────────────────╮
│                        Merlya Setup                              │
├─────────────────────────────────────────────────────────────────┤
│  Welcome to Merlya! / Bienvenue dans Merlya!                    │
│                                                                  │
│  Select your language / Choisissez votre langue:                │
│    1. English                                                    │
│    2. Français                                                   │
╰─────────────────────────────────────────────────────────────────╯
```

### Sélection du fournisseur LLM

```
╭───────────────────────────────────────────────────────────────────╮
│                      Configuration LLM                            │
├───────────────────────────────────────────────────────────────────┤
│  1. OpenRouter (recommandé - multi-modèles)                       │
│  2. Anthropic (Claude direct)                                     │
│  3. OpenAI (modèles GPT)                                          │
│  4. Mistral (Mistral AI)                                          │
│  5. Groq (inférence rapide)                                       │
│  6. Ollama (modèles locaux)                                       │
╰───────────────────────────────────────────────────────────────────╯

Sélectionner le provider [1]:
```

!!! tip "OpenRouter recommandé"
    OpenRouter offre des modèles gratuits et l'accès à plus de 100 LLMs. Obtenez votre clé API sur [openrouter.ai/keys](https://openrouter.ai/keys)

### Découverte des hôtes

L'assistant détecte automatiquement les hôtes depuis :

- `~/.ssh/config` - Configuration SSH
- `~/.ssh/known_hosts` - Hôtes précédemment connectés
- `/etc/hosts` - Définitions d'hôtes locaux
- Fichiers d'inventaire Ansible

```
Sources d'inventaire détectées :
  • SSH Config: 12 hôtes
  • Known Hosts: 45 hôtes

Importer tous les hôtes ? [O/n]:
```

---

## 2. Configuration manuelle (alternative)

Si vous sautez l'assistant ou voulez modifier les paramètres plus tard :

=== "Interactif (clés API stockées dans le keyring)"

    ```bash
    merlya
    # puis dans le REPL :
    /model provider openrouter
    /model model amazon/nova-2-lite-v1:free
    ```

=== "CI/CD (clés API via variables d'environnement)"

    ```bash
    export OPENAI_API_KEY="..."
    merlya config set model.provider openai
    merlya config set model.model gpt-4o-mini
    merlya run "Vérifie l'espace disque sur web-01"
    ```

=== "Ollama (local)"

    ```bash
    # D'abord, installez Ollama : https://ollama.com
    ollama pull llama3.2

    merlya config set model.provider ollama
    merlya config set model.model llama3.2
    merlya run "Vérifie l'espace disque sur web-01"
    ```

---

## 3. Démarrer le REPL

```bash
merlya
```

Utilisez `/help` pour lister les commandes disponibles, et `/exit` pour quitter.

!!! warning "Logiciel expérimental"
    Vérifiez toujours les commandes avant de les exécuter sur des systèmes de production.

---

## 4. Essayez quelques commandes

### Langage naturel

```
Merlya > Qu'est-ce que tu peux m'aider à faire ?

Je peux vous aider avec :
- Gérer les connexions SSH aux serveurs
- Exécuter des commandes sur des machines distantes
- Vérifier l'état et les métriques système
- Automatiser les tâches DevOps routinières

Décrivez simplement ce dont vous avez besoin !
```

### Connexion à un serveur

```
Merlya > Connecte-toi à mon-serveur.example.com et montre-moi l'uptime

Connexion à mon-serveur.example.com...

> ssh mon-serveur.example.com "uptime"

 14:32:01 up 45 days,  3:21,  2 users,  load average: 0.15, 0.10, 0.05

Le serveur fonctionne depuis 45 jours avec de faibles moyennes de charge.
```

### Référencer les hôtes par leur nom

```
Merlya > Vérifie l'espace disque sur web-01 et web-02

> ssh web-01 "df -h /"
> ssh web-02 "df -h /"

Résumé :
- web-01: 45% utilisé (55Go libre)
- web-02: 62% utilisé (38Go libre)
```

### Commandes slash

```
Merlya > /hosts

Nom      | Hostname              | User   | Tags
---------|----------------------|--------|------------------
web-01   | web-01.example.com   | deploy | ssh-config
web-02   | web-02.example.com   | deploy | ssh-config
db-01    | 10.0.1.50            | admin  | known-hosts
```

---

## Commandes courantes

| Commande | Description |
|----------|-------------|
| `merlya` | Démarrer le REPL interactif |
| `merlya run "..."` | Exécuter une commande de manière non-interactive |
| `merlya config list` | Afficher la configuration actuelle |
| `merlya config set KEY VALUE` | Définir une valeur de configuration |
| `/help` | Afficher les commandes slash disponibles |
| `/hosts` | Lister les hôtes configurés |
| `/new` | Démarrer une nouvelle conversation |
| `/exit` | Quitter le REPL |

---

## Étapes suivantes

- [Mode REPL](../guides/repl-mode.md) - Plongée dans l'interface interactive
- [Guide d'automatisation](../guides/automation.md) - Mode non-interactif, CI/CD, scripting
- [Guide de configuration](configuration.md) - Options de configuration avancées
- [Gestion SSH](../guides/ssh-management.md) - Fonctionnalités SSH et pool de connexions
- [Fournisseurs LLM](../guides/llm-providers.md) - Configurer différents fournisseurs LLM
