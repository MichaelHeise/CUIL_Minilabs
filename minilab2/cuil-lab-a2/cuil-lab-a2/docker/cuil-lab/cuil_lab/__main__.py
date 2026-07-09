"""cuil-lab CLI entry point."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml
from docker.errors import DockerException

from .controller import DockerController
from .schema import Lab
from .tui import CuilLabApp


def _load_lab(path: Path) -> Lab:
    if not path.exists():
        print(f"error: {path} not found", file=sys.stderr)
        sys.exit(1)
    try:
        data = yaml.safe_load(path.read_text())
        return Lab.model_validate(data)
    except Exception as e:
        print(f"error parsing {path}: {e}", file=sys.stderr)
        sys.exit(1)


_DAEMON_HINT = (
    "error: cannot reach the Docker daemon.\n"
    "       Start Docker Desktop (or the docker service) and retry."
)


def cmd_run(args: argparse.Namespace) -> int:
    config = Path(args.config).resolve()
    lab = _load_lab(config)
    try:
        # docker-py negotiates the API version in the constructor, so a
        # stopped daemon raises here rather than in is_up().
        controller = DockerController()
    except DockerException as e:
        print(_DAEMON_HINT, file=sys.stderr)
        print(f"       ({e})", file=sys.stderr)
        return 1
    if not controller.is_up():
        print(_DAEMON_HINT, file=sys.stderr)
        return 1
    try:
        controller.up(lab, project_name=args.project, work_dir=config.parent)
    except subprocess.CalledProcessError:
        print("error: `docker compose up` failed (see output above).",
              file=sys.stderr)
        print("       If the cuil/host or cuil/shaper image is missing, "
              "build them first: ./run-lab.sh --build (or `cuil-lab build`).",
              file=sys.stderr)
        controller.down()
        return 1
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        controller.down()
        return 1
    try:
        app = CuilLabApp(lab=lab, controller=controller)
        app.run()
    finally:
        # Teardown happens here, after the TUI has closed, so quitting the
        # app is instant and the compose output lands in the real terminal.
        print("stopping lab containers ...")
        controller.down()
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    here = Path(__file__).resolve()
    images_dir = here.parents[2] / "images"
    if not images_dir.exists():
        print(f"error: images dir not found at {images_dir}", file=sys.stderr)
        return 1
    for name in ("host", "shaper"):
        ctx = images_dir / name
        print(f"building cuil/{name} from {ctx}")
        rc = subprocess.run(
            ["docker", "build", "-t", f"cuil/{name}", str(ctx)],
        ).returncode
        if rc != 0:
            return rc
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="cuil-lab")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="start the lab and open the TUI")
    run.add_argument("--config", default="lab.yaml")
    run.add_argument("--project", default="cuil")
    run.set_defaults(func=cmd_run)

    build = sub.add_parser("build", help="build cuil/host and cuil/shaper images")
    build.set_defaults(func=cmd_build)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
