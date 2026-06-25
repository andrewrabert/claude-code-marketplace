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

# Launch Claude to improve the named skills with the skill-creator skill
improve *skills: setup
    claude "Use the skill-creator skill to improve these skills: {{skills}}"

# Checks run by the git pre-commit hook
pre-commit: check-plugin bump readme lint
    git add README.md

# Install or replace the marketplace and enable all plugins
install: setup
    #!/bin/sh
    set -eu
    config_dir="${CLAUDE_CONFIG_DIR:-${HOME}/.claude}"
    src="{{justfile_directory()}}"
    manifest="${src}/.claude-plugin/marketplace.json"
    marketplace_name="$(jq -r '.name' "${manifest}")"
    # Refresh the on-disk marketplace source; `claude plugin install` copies from
    # here into the plugin cache, so the rsync must land before any install.
    rsync -a --delete "${src}/" "${config_dir}/plugins/marketplaces/${marketplace_name}/"
    # install is a no-op when a plugin is already installed and never refreshes the
    # cache from changed local source, so uninstall first to force a clean copy.
    jq -r '.plugins[].name' "${manifest}" | while read -r plugin; do
        ref="${plugin}@${marketplace_name}"
        claude plugin uninstall "${ref}" >/dev/null 2>&1 || true
        claude plugin install "${ref}" --scope user
    done

# Install the git pre-commit hook if missing
setup:
    #!/bin/sh
    set -eu
    hook="{{justfile_directory()}}/.git/hooks/pre-commit"
    [ -f "${hook}" ] && exit 0
    cp "{{justfile_directory()}}/dev/pre-commit" "${hook}"
    echo "Installed git pre-commit hook"
