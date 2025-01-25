# noqa: INP001
"""Make conda env.yaml and pip requirements.txt files from environments.json data."""

from __future__ import annotations

from itertools import chain
from json import load as json_load
from pathlib import Path
from typing import Any

from packaging.requirements import Requirement
from tomllib import load as tomllib_load

# path to package's pyproject and the config json file
PYPROJECT_PATH = "./pyproject.toml"
ENVS_CONFIG_PATH = "./environments/requirements/environments.json"

# what channels to specify in conda env yaml files
CHANNELS = ["conda-forge"]

HEADER = (
    "# Do not edit this file. It is automatically generated by the script\n"
    "# /environments/make-env-files.py using the environment definition files in\n"
    "# /environments/requirements/ and the requirements in pyproject.toml.\n"
)


def make_requirement(
    requirement: Requirement,
    pin_exact: bool = False,  # noqa: FBT001,FBT002
    is_conda: bool = True,  # noqa: FBT001,FBT002
) -> str:
    """
    Make a requirement specification string.

    The string result comprises the requirement's name and its specifier(s).

    Parameters
    ----------
    requirement
        A requirement object.
    pin_exact
        If True, pin requirement to version rather than using existing
        specifier. Allows you to convert minimum versions to pinned versions.
    is_conda
        If True and if `pin_exact` is True, format the requirement string to
        end with ".*" for conda environment file pinning format compatibility.

    Returns
    -------
    requirement_str
        The requirement's name and its specifier(s).
    """
    specifiers = list(requirement.specifier)
    if pin_exact and len(specifiers) == 1:
        spec = f"{requirement.name}=={specifiers[0].version}"
        if is_conda and not spec.endswith(".*"):
            spec += ".*"
        return spec
    return str(requirement)


def make_file(env: dict[str, Any]) -> None:
    """
    Write a conda environment yaml file or pip requirements.txt file.

    Parameters
    ----------
    env
        An environment configuration dictionary.

    Returns
    -------
    None
    """
    depends_on = []
    output_path = Path(env["output_path"])

    # it's conda env if it's a yaml file, otherwise it's pip requirements.txt
    is_conda = output_path.suffix in {".yaml", ".yml"}

    # determine which dependencies to add based on the configuration
    if is_conda:
        depends_on.append(Requirement(f"python{pyproject['project']['requires-python']}"))
    if env["needs_dependencies"]:
        depends_on.extend(Requirement(d) for d in pyproject["project"]["dependencies"])
        optionals = pyproject["project"]["optional-dependencies"].values()
        depends_on.extend({Requirement(o) for o in chain.from_iterable(optionals)})

    # make the list of requirements
    requirements = [make_requirement(dep, env["pin_exact"], is_conda) for dep in depends_on]

    # inject any additional requirement files if specified by the config
    if env["extras"] is not None:
        for extras_filepath in env["extras"]:
            with Path(extras_filepath).open() as f:
                requirements += f.read().splitlines()

    # convert the requirements to conda env yaml or pip requirements text
    requirements = sorted(requirements)
    if not is_conda:
        text = HEADER + "\n".join(requirements) + "\n"
    else:
        env_name = Path(output_path).stem
        data = {"name": env_name, "channels": CHANNELS, "dependencies": requirements}
        text = ""
        for k, v in data.items():
            if isinstance(v, list):
                text += k + ":\n  - " + "\n  - ".join(v) + "\n"
            elif isinstance(v, str):
                text += k + ": " + v + "\n"
        text = HEADER + text

    # write the text to file on disk
    with Path(output_path).open("w") as f:
        f.writelines(text)

    print(f"Wrote {len(requirements)} requirements to {str(output_path)!r}")  # noqa: T201


if __name__ == "__main__":
    # load the pyproject.toml and the environments.json config files
    with Path(PYPROJECT_PATH).open("rb") as f:
        pyproject = tomllib_load(f)
    with Path(ENVS_CONFIG_PATH).open("rb") as f:
        envs = json_load(f)

    # make each environment/requirements file as configured
    for env in envs:
        make_file(env)
