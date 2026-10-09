from dataclasses import dataclass


GREY_BASE_URL = "https://grey.devops.moego.pet"
GREY_NAMESPACE = "ns-testing"
GREY_TIMEOUT = 30.0


@dataclass(frozen=True)
class Config:
    grey_base_url: str = GREY_BASE_URL
    grey_namespace: str = GREY_NAMESPACE
    timeout: float = GREY_TIMEOUT


def load_config():
    return Config()
