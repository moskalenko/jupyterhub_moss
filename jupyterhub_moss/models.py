from __future__ import annotations

import re
from typing import Dict, Optional

from pydantic import BaseModel, Extra, validator

# validators


def is_positive(v: Optional[int]) -> Optional[int]:
    if v is not None and v < 0:
        raise ValueError("Value must be positive")
    return v


def is_strictly_positive(v: Optional[int]) -> Optional[int]:
    if v is not None and v <= 0:
        raise ValueError("Value must be strictly positive")
    return v


def check_match_gpu(v: Optional[int], values: dict) -> Optional[int]:
    if v is not None and v > 0 and values.get("gpu") == "":
        return 0  # GPU explicitly disabled
    return v


# models


class PartitionResources(BaseModel, allow_mutation=False, extra=Extra.allow):
    """SLURM partition required resources information

    This information retrieved from SLURM is used to constraint user's selection.
    Extra fields (e.g., as in :class:`PartitionAllResources`) can be used to display
    information about available resources.
    """

    max_nprocs: int
    max_mem: int
    gpu: str
    max_ngpus: int
    max_runtime: int

    # validators
    _is_positive = validator("max_ngpus", allow_reuse=True)(is_positive)
    _check_match_gpu = validator("max_ngpus", allow_reuse=True)(check_match_gpu)
    _is_strictly_positive = validator(
        "max_nprocs", "max_mem", "max_runtime", allow_reuse=True
    )(is_strictly_positive)


class PartitionAllResources(
    PartitionResources, allow_mutation=False, extra=Extra.forbid
):
    """SLURM partition resources information

    Extends resource constraints information with information
    used to display available resources.
    """

    nnodes_total: int
    nnodes_idle: int
    ncores_total: int
    ncores_idle: int

    # validators
    _is_positive = validator(
        "nnodes_total", "nnodes_total", "ncores_total", "ncores_idle", allow_reuse=True
    )(is_positive)


class JupyterEnvironment(BaseModel, allow_mutation=False, extra=Extra.forbid):
    """Single Jupyter environement description"""

    add_to_path = True
    description: str
    path: str
    prologue = ""

    @validator("path", "description")
    def check_not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("String must not be empty")
        return v


class PartitionConfig(BaseModel, allow_mutation=False, extra=Extra.forbid):
    """Information about partition description and available environments"""

    architecture = ""
    description = ""
    jupyter_environments: Dict[str, JupyterEnvironment]
    simple = True


class PartitionInfo(
    PartitionConfig, PartitionResources, allow_mutation=False, extra=Extra.allow
):
    """Complete information about a partition: config and resources"""

    pass


class _PartitionTraits(PartitionConfig, allow_mutation=False, extra=Extra.forbid):
    """Configuration of a single partition passed as ``partitions`` traits"""

    gpu: Optional[str] = None
    max_ngpus: Optional[int] = None
    max_nprocs: Optional[int] = None
    max_runtime: Optional[int] = None

    # validators
    _is_positive = validator("max_ngpus", allow_reuse=True)(is_positive)
    _check_match_gpu = validator("max_ngpus", allow_reuse=True)(check_match_gpu)
    _is_strictly_positive = validator("max_nprocs", "max_runtime", allow_reuse=True)(
        is_strictly_positive
    )


class PartitionsTrait(BaseModel, allow_mutation=False, extra=Extra.forbid):
    """Configuration passed as ``partitions`` trait"""

    __root__: Dict[str, _PartitionTraits]

    def dict(self, *args, **kwargs):
        return {k: v.dict(*args, **kwargs) for k, v in self.__root__.items()}

    def items(self):
        return self.__root__.items()


class UserOptions(BaseModel):
    """Options passed as `Spawner.user_options`"""

    # Options received through the form or GET request
    partition: str
    runtime = ""
    nprocs = 1
    memory = ""
    reservation = ""
    ngpus = 0
    options = ""
    output = "/dev/null"
    environment_path = ""
    default_url = ""
    root_dir = ""
    # Extra fields
    gres = ""
    prologue = ""

    @classmethod
    def parse_formdata(cls, formdata: dict[str, list[str]]) -> UserOptions:
        # Those keys should not come from the request, they are set later by the spawner
        excluded_keys = "gres", "prologue"
        fields = {
            k: v[0].strip() for k, v in formdata.items() if k not in excluded_keys
        }

        # Compatibility with mem query param renamed memory
        if "mem" in fields and "memory" not in fields:
            fields["memory"] = fields["mem"]

        # Convert output boolean query param to file pattern
        fields["output"] = (
            "slurm-%j.out" if fields.get("output", "false") == "true" else "/dev/null"
        )
        return cls.parse_obj(fields)

    # validators
    _is_positive = validator("ngpus", allow_reuse=True)(is_positive)
    _is_strictly_positive = validator("nprocs", allow_reuse=True)(is_strictly_positive)

    @validator(
        "partition",
        "runtime",
        "memory",
        "reservation",
        "options",
        "output",
        "environment_path",
        "default_url",
        "root_dir",
    )
    def has_no_newline(cls, v: str) -> str:
        if "\n" in v:
            raise ValueError("Must not contain newline")
        return v

    @validator("default_url")
    def is_absolute_path(cls, v: str) -> str:
        if v and not v.startswith("/"):
            raise ValueError("Must start with /")
        return v

    @validator("runtime")
    def check_timelimit(cls, v: str) -> str:
        from .utils import parse_timelimit  # avoid circular imports

        if v:
            parse_timelimit(v)  # Raises exception if malformed
        return v

    _MEM_REGEXP = re.compile("^[0-9]*([0-9]+[KMGT])?$")

    @validator("memory")
    def check_memory(cls, v: str) -> str:
        if v and cls._MEM_REGEXP.match(v) is None:
            raise ValueError("Error in memory syntax")
        return v
