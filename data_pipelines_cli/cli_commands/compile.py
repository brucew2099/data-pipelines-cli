import pathlib
import shutil
from typing import Optional

import click

from ..cli_constants import (
    BUILD_DIR,
    DATAHUB_URL_ENV,
    DOCKER_REPOSITORY_URL_TO_REPLACE,
    IMAGE_TAG_TO_REPLACE,
    INGEST_ENDPOINT_TO_REPLACE,
)
from ..cli_utils import echo_info, echo_warning, get_argument_or_environment_variable
from ..config_generation import (
    copy_config_dir_to_build_dir,
    copy_dag_dir_to_build_dir,
    generate_profiles_yml,
)
from ..data_structures import DockerArgs
from ..dbt_utils import run_dbt_command
from ..errors import DockerNotInstalledError
from ..io_utils import replace


def _replace_image_tag(k8s_config: pathlib.Path, docker_args: DockerArgs) -> None:
    echo_info(f"Replacing <IMAGE_TAG> with commit SHA = {docker_args.commit_sha}")
    replace(k8s_config, IMAGE_TAG_TO_REPLACE, docker_args.commit_sha)


def _replace_docker_repository_url(
    k8s_config: pathlib.Path, docker_args: DockerArgs
) -> None:
    echo_info(
        "Replacing <DOCKER_REPOSITORY_URL> with repository URL = "
        f"{docker_args.repository}"
    )
    replace(k8s_config, DOCKER_REPOSITORY_URL_TO_REPLACE, docker_args.repository)


def _docker_build(docker_args: DockerArgs) -> None:
    """
    :param docker_args: Arguments required by the Docker to make a push to \
        the repository
    :raises DataPipelinesError: Docker not installed
    """
    try:
        import docker
    except ModuleNotFoundError:
        raise DockerNotInstalledError()

    echo_info("Building Docker image")
    docker_client = docker.from_env()
    docker_tag = docker_args.docker_build_tag()
    _, logs_generator = docker_client.images.build(path=".", tag=docker_tag)
    click.echo(
        "".join(
            map(
                lambda log: log["stream"],
                filter(lambda log: "stream" in log, logs_generator),
            )
        )
    )


def _dbt_compile(env: str) -> None:
    profiles_path = generate_profiles_yml(env, False)
    echo_info("Running dbt commands:")
    run_dbt_command(("deps",), env, profiles_path)
    run_dbt_command(("compile",), env, profiles_path)
    run_dbt_command(("docs", "generate"), env, profiles_path)
    run_dbt_command(("source", "freshness"), env, profiles_path)


def _copy_dbt_manifest() -> None:
    echo_info("Copying DBT manifest")
    shutil.copyfile(
        pathlib.Path.cwd().joinpath("target", "manifest.json"),
        BUILD_DIR.joinpath("dag", "manifest.json"),
    )


def _try_replace_datahub_address(datahub_gms_uri: Optional[str]) -> None:
    datahub_gms_uri = get_argument_or_environment_variable(
        datahub_gms_uri, DATAHUB_URL_ENV
    )
    if not datahub_gms_uri:
        echo_warning(
            "'--datahub-gms-uri' argument not provided, "
            f"{INGEST_ENDPOINT_TO_REPLACE} will not be replaced"
        )
        return

    echo_info(
        f"Replacing {INGEST_ENDPOINT_TO_REPLACE} with DataHub URI = {datahub_gms_uri}"
    )
    replace(
        BUILD_DIR.joinpath("dag", "config", "base", "datahub.yml"),
        INGEST_ENDPOINT_TO_REPLACE,
        datahub_gms_uri,
    )


def compile_project(
    docker_repository_uri: Optional[str],
    datahub_gms_uri: Optional[str],
    docker_build: bool,
    env: str,
) -> None:
    """
    Create local working directories and build artifacts

    :param docker_repository_uri: URI of the Docker repository
    :type docker_repository_uri: Optional[str]
    :param datahub_gms_uri: URI of the DataHub ingestion endpoint
    :type datahub_gms_uri: Optional[str]
    :param docker_build: Whether to build a Docker image
    :type docker_build: bool
    :param env: Name of the environment
    :type env: str
    :raises DataPipelinesError:
    """
    copy_dag_dir_to_build_dir()
    copy_config_dir_to_build_dir()

    docker_args = None
    k8s_config: pathlib.Path = BUILD_DIR.joinpath("dag", "config", "base", "k8s.yml")
    if docker_repository_uri:
        docker_args = DockerArgs(docker_repository_uri)
        _replace_image_tag(k8s_config, docker_args)
        _replace_docker_repository_url(k8s_config, docker_args)

    _dbt_compile(env)
    _copy_dbt_manifest()
    _try_replace_datahub_address(datahub_gms_uri)

    if docker_build and docker_args:
        _docker_build(docker_args)


@click.command(
    name="compile",
    help="Create local working directories and build artifacts",
)
@click.option(
    "--env",
    default="local",
    type=str,
    show_default=True,
    required=True,
    help="Name of the environment",
)
@click.option(
    "--docker-repository-uri", default=None, help="URI of the Docker repository"
)
@click.option(
    "--datahub-gms-uri", default=None, help="URI of the DataHub ingestion endpoint"
)
@click.option(
    "--docker-build",
    is_flag=True,
    default=False,
    help="Whether to build a Docker image",
)
def compile_project_command(
    env: str,
    docker_repository_uri: Optional[str],
    datahub_gms_uri: Optional[str],
    docker_build: bool,
) -> None:
    compile_project(docker_repository_uri, datahub_gms_uri, docker_build, env)
