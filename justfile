set default-list := true

# Write the generated files, or with --pre-commit only check them
[private]
[positional-arguments]
generate *flags:
    "{{justfile_directory()}}/dev/marketplace.py" render-readme "$@"

# Validate the marketplace, plugins, and generated files
lint: setup (generate "--pre-commit")
    claude plugin validate .

# Regenerate generated files: README.md
render: setup (generate)

# Bump the version of every plugin with staged changes
bump: setup
    "{{justfile_directory()}}/dev/marketplace.py" bump

# Scaffold a new plugin
new-plugin name description: setup
    "{{justfile_directory()}}/dev/marketplace.py" new-plugin "{{name}}" "{{description}}"

# Normalize plugin manifests to the canonical shape
[positional-arguments]
check-plugin *names: setup
    "{{justfile_directory()}}/dev/marketplace.py" check-plugin "$@"

# Launch Claude to improve the named skills with the skill-creator skill
[positional-arguments]
improve *skills: setup
    claude "Use the skill-creator skill to improve these skills: $*"

# Launch Claude with only this checkout's plugins enabled
[positional-arguments]
claude *args: setup
    #!/bin/sh
    set -eu
    # Disable every installed plugin for this session; --plugin-dir loads each
    # checkout plugin, so unpublished edits take effect without reinstalling.
    settings="$(command claude plugin list --json | jq -c '{enabledPlugins: (map({key: .id, value: false}) | from_entries)}')"
    exec claude --settings "${settings}" --plugin-dir "{{justfile_directory()}}/plugins" "$@"

# Checks run by the git pre-commit hook
pre-commit: check-plugin bump lint

# Install the git pre-commit hook if missing
setup:
    #!/bin/sh
    set -eu
    hook="{{justfile_directory()}}/.git/hooks/pre-commit"
    [ -f "${hook}" ] && exit 0
    cp "{{justfile_directory()}}/dev/pre-commit" "${hook}"
    echo "Installed git pre-commit hook"
