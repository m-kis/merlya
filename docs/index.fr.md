<div align="center">
  <img src="../assets/logo.png" alt="Logo Merlya" width="280">
</div>

# Merlya

!!! warning "Projet archivé — non maintenu"

    **Merlya n'est plus activement développé** (dernière version : `v0.8.5`, février 2026).

    **Pourquoi ?** La montée en puissance rapide des agents CLI génériques — **Claude Code**, Codex CLI, Gemini CLI et consorts — a largement absorbé la proposition de valeur de Merlya. Portés par les grands laboratoires d'IA, ces outils couvrent désormais l'essentiel de l'expérience « assistant CLI en langage naturel » avec des moyens sans commune mesure avec ceux d'un projet indépendant. Maintenir un concurrent sur ce terrain n'est plus pertinent **pour le moment**.

    Le code reste consultable, réutilisable et installable (`pip install merlya`) sous licence MIT + Commons Clause, **à des fins d'archive uniquement** : aucune nouvelle fonctionnalité, correction de bug ni mise à jour de sécurité n'est prévue. Comme l'outil manipule SSH, des secrets et de l'élévation de privilèges, évaluez ce risque avant tout usage en production.

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

-   :material-robot:{ .lg .middle } **Architecture DIAGNOSTIC/CHANGE**

    ---

    Routage intelligent entre investigation read-only et mutations contrôlées avec approbation HITL.

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
