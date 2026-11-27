import uvicorn

from app.core.config import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run(
        "app.main:create_app", factory=True, host=settings.backend_host, port=settings.backend_port
    )


if __name__ == "__main__":
    main()
