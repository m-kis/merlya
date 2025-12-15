# Installation

## Prérequis

- Python 3.11 ou supérieur
- pip (gestionnaire de paquets Python)
- Une clé API de fournisseur LLM (OpenAI, Anthropic, ou Ollama local)

## Installation depuis PyPI

La méthode recommandée pour installer Merlya est via pip :

```bash
pip install merlya
```

## Installation depuis les sources

Pour la dernière version de développement :

```bash
git clone https://github.com/m-kis/merlya.git
cd merlya
pip install -e ".[dev]"
```

## Vérifier l'installation

```bash
merlya --version
```

Vous devriez voir une sortie comme :

```
merlya 0.7.5
```

## Autocomplétion du shell

=== "Bash"

    ```bash
    # Ajoutez à ~/.bashrc
    eval "$(_MERLYA_COMPLETE=bash_source merlya)"
    ```

=== "Zsh"

    ```bash
    # Ajoutez à ~/.zshrc
    eval "$(_MERLYA_COMPLETE=zsh_source merlya)"
    ```

=== "Fish"

    ```fish
    # Ajoutez à ~/.config/fish/completions/merlya.fish
    _MERLYA_COMPLETE=fish_source merlya | source
    ```

## Installation Docker

```bash
# Copier et configurer les variables d'environnement
cp .env.example .env
# Éditez .env avec vos clés API

# Démarrer le conteneur
docker compose up -d

# Mode développement (code source monté)
docker compose --profile dev up -d
```

**Configuration SSH pour Docker :**

Le conteneur monte votre répertoire SSH local. Par défaut, il utilise `$HOME/.ssh`.

## Étapes suivantes

- [Démarrage rapide](quickstart.md) - Démarrez en 5 minutes
- [Configuration](configuration.md) - Configurez votre fournisseur LLM et paramètres
