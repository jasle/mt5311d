"""Fixtures for the OpenWrt test container.

The container runs the OpenWrt 25.12.5 userland (tests/container/Containerfile)
with the repository mounted read-only. Code runs in it only through exec; the
container itself just waits.
"""

from collections.abc import Iterator

import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.image import DockerImage

from ucode import CONTAINER_REPO, REPO, Executor, Ucode

CONTAINER_DIR = REPO / "tests" / "container"
IMAGE_TAG = "mt5311d-test:latest"


@pytest.fixture(scope="session")
def test_image() -> Iterator[str]:
    # Keep the image after the run so that podman's layer cache makes the next
    # build cheap.
    with DockerImage(path=CONTAINER_DIR, dockerfile_path="Containerfile", tag=IMAGE_TAG,
                     clean_up=False) as image:
        yield str(image)


@pytest.fixture(scope="session")
def container(test_image) -> Iterator[DockerContainer]:
    container = (
        DockerContainer(test_image)
        .with_command("sleep infinity")
        .with_volume_mapping(str(REPO), str(CONTAINER_REPO), "ro")
        .with_kwargs(network_mode="none", cap_add=["NET_ADMIN", "NET_RAW"], init=True)
    )
    with container:
        yield container


@pytest.fixture(scope="session")
def execute(container) -> Executor:
    """Runs a command in the container: argv -> (exit code, stdout, stderr)."""
    wrapped = container.get_wrapped_container()

    def execute(argv: list[str]) -> tuple[int, str, str]:
        result = wrapped.exec_run(argv, demux=True)
        stdout, stderr = result.output
        return (result.exit_code,
                (stdout or b"").decode(errors="surrogateescape"),
                (stderr or b"").decode(errors="surrogateescape"))

    return execute


@pytest.fixture(scope="session")
def ucode(execute) -> Ucode:
    """Runs ucode in the container with the modules from src/ on the search path."""
    return Ucode(execute)
