<div align="center">
  <img src="../assets/logo.png" alt="Logo Merlya" width="280">
</div>

# Merlya

**Assistant d'infrastructure propulsé par l'IA pour les équipes DevOps et SRE.**

Merlya est un outil en ligne de commande qui combine la puissance des LLM avec des capacités pratiques de gestion d'infrastructure :
inventaire SSH, exécution à distance sécurisée, diagnostics et automatisation.

## Fonctionnalités clés

<div class="grid cards" markdown>

-   :material-chat-processing:{ .lg .middle } **Interface en langage naturel**

    ---

    Posez des questions comme "vérifie l'espace disque sur web-01" ou "analyse ce log d'incident".

-   :material-server-network:{ .lg .middle } **Gestion SSH**

    ---

    Pool SSH asynchrone, jump hosts, test de connexion, import/export d'inventaire.

-   :material-robot:{ .lg .middle } **Routage local + fallback LLM**

    ---

    Le routage d'intention préfère les classifieurs locaux quand disponibles, avec des fallbacks sûrs.

-   :material-security:{ .lg .middle } **Sécurisé par conception**

    ---

    Secrets stockés dans le keyring système ; entrées validées ; logs cohérents.

</div>

## Exemple rapide

```bash
pip install merlya

# Option A : laissez l'assistant de configuration vous guider (recommandé)
merlya

# Option B : pour CI/CD, fournissez les clés API via variables d'environnement
export OPENAI_API_KEY="..."
merlya run "Vérifie l'espace disque sur web-01"
```

## Documentation

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } **Démarrage**

    ---

    - [Installation](getting-started/installation.md)
    - [Démarrage rapide](getting-started/quickstart.md)
    - [Configuration](getting-started/configuration.md)

-   :material-book-open-variant:{ .lg .middle } **Guides**

    ---

    - [Mode REPL](guides/repl-mode.md)
    - [Gestion SSH](guides/ssh-management.md)
    - [Fournisseurs LLM](guides/llm-providers.md)
    - [Automatisation](guides/automation.md)

-   :material-file-document:{ .lg .middle } **Référence**

    ---

    - [CLI](reference/cli.md)
    - [Commandes slash](commands.md)
    - [Outils](tools.md)
    - [Configuration](reference/configuration.md)

-   :material-cog:{ .lg .middle } **Architecture**

    ---

    - [Vue d'ensemble](architecture.md)
    - [Décisions (ADR)](architecture/decisions.md)

</div>

[Commencer :material-arrow-right:](getting-started/installation.md){ .md-button .md-button--primary }
[Voir sur GitHub :material-github:](https://github.com/m-kis/merlya){ .md-button }
