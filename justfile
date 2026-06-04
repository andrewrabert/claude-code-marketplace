[private]
list: setup
    @just --list

# Validate the marketplace and plugins
lint: setup
    claude plugin validate .

# Regenerate README.md from plugin and skill metadata
readme: setup
    "{{justfile_directory()}}/dev/marketplace.py" readme

# Bump the version of every plugin with staged changes
bump: setup
    "{{justfile_directory()}}/dev/marketplace.py" bump

# Scaffold a new plugin
new-plugin name description: setup
    "{{justfile_directory()}}/dev/marketplace.py" new-plugin "{{name}}" "{{description}}"

# Normalize plugin manifests to the canonical shape
check-plugin *names: setup
    "{{justfile_directory()}}/dev/marketplace.py" check-plugin {{names}}

# Checks run by the git pre-commit hook
pre-commit: check-plugin bump readme lint
    git add README.md

# Install or replace the marketplace
install: setup
    config_dir="${CLAUDE_CONFIG_DIR:-${HOME}/.claude}"; \
    marketplace="${config_dir}/plugins/marketplaces/andrewrabert-marketplace"; \
    rsync -a --delete "{{justfile_directory()}}/" "${marketplace}/"

# Install the git pre-commit hook if missing
setup:
    #!/bin/sh
    set -eu
    hook="{{justfile_directory()}}/.git/hooks/pre-commit"
    [ -f "${hook}" ] && exit 0
    cp "{{justfile_directory()}}/dev/pre-commit" "${hook}"
    echo "Installed git pre-commit hook"
