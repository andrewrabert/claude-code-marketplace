#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "pydantic-settings>=2.16,<3",
#   "ruamel.yaml>=0.18,<0.19",
#   "typesafe-sdk>=0.7.5,<0.8",
# ]
# ///
"""Ask TypeSafe's Jev a question set about the text on stdin and print one answer per question as JSON."""

import argparse
import io
import json
import os
import pathlib
import sys

import pydantic
import pydantic_settings
import ruamel.yaml
import typesafe_sdk

# Seconds per request; the SDK's own default of 10 cuts off long states.
TIMEOUT = 90.0

# Jev's context window in tokens, estimated as a payload's bytes over 4.
MAX_CONTEXT_TOKENS = 32_000

# Exit status when the request would fail or waste a call, so nothing was sent.
REJECTED = 2

EPILOG = """\
examples:
  git diff -W | jev-ask.py -q standards.yaml
  jev-ask.py --dry-run -q standards.yaml < /dev/null

settings, read from the environment, then TYPESAFE_ENV_FILE:
  TYPESAFE_API_KEY        API key
  TYPESAFE_DEFAULT_MODEL  model; default jev-latest
  TYPESAFE_BASE_URL       API root; default https://api.typesafe.ai
  TYPESAFE_ENV_FILE       dotenv file holding the settings above; read from the environment only
"""


# A key absent from a question, as distinct from one present with a null value.
MISSING = object()


class UserError(Exception):
    pass


class Rejected(Exception):
    """Problems found before sending, each a (rule, path, message, help) tuple."""


class Settings(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix="TYPESAFE_",
        env_file=os.environ.get("TYPESAFE_ENV_FILE"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_key: pydantic.SecretStr | None = None
    base_url: str = typesafe_sdk.constants.DEFAULT_BASE_URL
    default_model: str = typesafe_sdk.constants.DEFAULT_MODEL


def json_dumps(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def parse_value(text):
    try:
        return json.loads(text)
    except ValueError:
        pass
    try:
        return ruamel.yaml.YAML(typ="safe", pure=True).load(io.StringIO(text))
    except ruamel.yaml.YAMLError as e:
        raise UserError(
            f"input is neither valid JSON nor valid YAML: {e}"
        ) from e


def stringify_scalar(value):
    """An unquoted YAML number or boolean as the text its author wrote."""
    match value:
        case bool():
            return "true" if value else "false"
        case int() | float():
            return json_dumps(value)
        case _:
            return value


def build(kind, instructions, criteria):
    match kind:
        case "noul":
            question = {"type": "noul", "instructions": instructions}
            if criteria is not MISSING:
                question["criteria"] = criteria
            return question
        case "choice":
            if criteria is MISSING:
                raise UserError(
                    "`choice` requires criteria; the API rejects the request without them"
                )
            if not isinstance(criteria, dict):
                raise UserError(
                    "`choice` criteria must be a mapping of option to description"
                )
            return {
                "type": "choice",
                "instructions": instructions,
                "criteria": {
                    k: stringify_scalar(v) for k, v in sorted(criteria.items())
                },
            }
        case "score":
            if criteria is MISSING:
                raise UserError(
                    "`score` requires criteria; the API rejects the request without them"
                )
            if not isinstance(criteria, list):
                raise UserError(
                    "`score` criteria must be a list of level descriptions, lowest first"
                )
            return {
                "type": "score",
                "instructions": instructions,
                "criteria": [stringify_scalar(v) for v in criteria],
            }
        case _:
            raise UserError(
                f"unknown question type {kind!r}; expected `noul`, `choice`, or `score`"
            )


def parse_question(raw):
    if not isinstance(raw, dict):
        raise UserError("expected a mapping")
    if isinstance(raw.get("type"), str):
        if "instructions" not in raw:
            raise UserError("`instructions` is required")
        return build(
            raw["type"], raw["instructions"], raw.get("criteria", MISSING)
        )
    for kind in ("noul", "choice", "score"):
        if kind in raw:
            criteria = next(
                (
                    raw[k]
                    for k in ("options", "levels", "criteria")
                    if k in raw
                ),
                MISSING,
            )
            if criteria is MISSING:
                criteria = {
                    k: v for k, v in raw.items() if k != kind
                } or MISSING
            return build(kind, raw[kind], criteria)
    raise UserError(
        "no question type found; expected a `type` field, or one of `noul`, `choice`, `score` as a key"
    )


def parse_questions(text):
    value = parse_value(text)
    if not isinstance(value, dict):
        raise UserError("expected a mapping of question name to question")
    questions = {}
    for name, raw in sorted(value.items()):
        try:
            questions[name] = parse_question(raw)
        except UserError as e:
            raise UserError(f"question {name!r}: {e}") from e
    return questions


def guidance_text(value):
    """Every string in an instructions value, joined, so emptiness can be judged."""
    match value:
        case str():
            return value
        case dict():
            return " ".join(guidance_text(v) for v in value.values())
        case list():
            return " ".join(guidance_text(v) for v in value)
        case None:
            return ""
        case _:
            return json_dumps(value)


def check(request):
    """The problems that would make a request fail or waste a call, so it is not sent."""
    problems = []
    if not request["questions"]:
        problems.append(
            ("no-questions", "questions", "request has no questions", None)
        )
    for name, question in request["questions"].items():
        path = f"questions.{name}"
        if not guidance_text(question["instructions"]).strip():
            problems.append(
                (
                    "empty-instructions",
                    f"{path}.instructions",
                    f"{question['type']} question has empty instructions",
                    None,
                )
            )
        if question["type"] == "noul" and not isinstance(
            question.get("criteria", {}), dict
        ):
            problems.append(
                (
                    "noul-criteria-shape",
                    f"{path}.criteria",
                    "noul criteria must be an object with `true` and `false` keys",
                    "Omit criteria entirely if you do not need them.",
                )
            )
    if not request["state"].strip():
        problems.append(("empty-state", "state", "state is empty", None))
    tokens = len(json_dumps(request).encode()) // 4 + 1
    if tokens > MAX_CONTEXT_TOKENS * 4:
        problems.append(
            (
                "context-overflow",
                "state",
                f"roughly {tokens} estimated tokens cannot fit the {MAX_CONTEXT_TOKENS}-token limit",
                "Split the state, or drop questions that do not need the full context.",
            )
        )
    if problems:
        raise Rejected(sorted(problems, key=lambda p: p[1]))


def summary(response):
    values = {}
    for name, answer in sorted(response.answers.items()):
        match answer:
            case typesafe_sdk.NoulAnswer():
                values[name] = answer.noul
            case typesafe_sdk.ChoiceAnswer():
                values[name] = answer.choice
            case typesafe_sdk.ScoreAnswer():
                values[name] = answer.score
    return values


class Ask(pydantic_settings.BaseSettings):
    """Ask TypeSafe's Jev a question set about the text on stdin and print one answer per question as JSON."""

    model_config = pydantic_settings.SettingsConfigDict(
        cli_enforce_required=True,
        cli_implicit_flags="toggle",
        cli_kebab_case=True,
        cli_shortcuts={"questions": "q"},
    )

    questions: pathlib.Path = pydantic.Field(
        description="question set file (YAML or JSON)"
    )
    dry_run: bool = pydantic.Field(
        False,
        description="print the request that would be sent, and exit without sending it",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        # Only the command line sets these; the environment holds `Settings`.
        return (init_settings,)

    def cli_cmd(self) -> None:
        try:
            text = self.questions.read_text()
        except OSError as e:
            raise UserError(
                f"failed to read {self.questions}: {e.strerror}"
            ) from e
        questions = parse_questions(text)
        if sys.stdin.isatty():
            raise UserError("no input given, and stdin is a terminal")
        state = sys.stdin.read()
        try:
            settings = Settings()
        except pydantic.ValidationError as e:
            raise UserError(f"invalid settings: {e}") from e
        request = {
            "model": settings.default_model,
            "state": state,
            "questions": questions,
        }
        check(request)
        if self.dry_run:
            print(json_dumps(request))
            return
        if settings.api_key is None:
            raise UserError(
                "TYPESAFE_API_KEY is not set in the environment or TYPESAFE_ENV_FILE"
            )
        try:
            with typesafe_sdk.TypeSafeClient(
                api_key=settings.api_key.get_secret_value(),
                base_url=settings.base_url,
                model=settings.default_model,
                timeout=TIMEOUT,
                # LiteLLM's pass-through fails on zstd request bodies, which the SDK sends from 1 KiB up.
                compression=False,
            ) as client:
                response = client.system_one(state=state, questions=questions)
        except typesafe_sdk.TypeSafeError as e:
            raise UserError(str(e)) from e
        print(json_dumps(summary(response)))


def main():
    parser = argparse.ArgumentParser(
        prog="jev-ask.py",
        description=Ask.__doc__,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pydantic_settings.CliApp.run(
        Ask,
        cli_settings_source=pydantic_settings.CliSettingsSource(
            Ask, root_parser=parser
        ),
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except UserError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    except Rejected as e:
        (problems,) = e.args
        for rule, path, message, help in problems:
            print(f"error[{rule}]: {path}: {message}", file=sys.stderr)
            if help:
                print(f"  help: {help}", file=sys.stderr)
        print(
            f"{len(problems)} problem(s) would cause a failed or wasted call; fix them",
            file=sys.stderr,
        )
        sys.exit(REJECTED)
