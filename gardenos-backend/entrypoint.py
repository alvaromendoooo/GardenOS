from src.gardenos import create_app
from src.config.config import settings

def main():
    app = create_app()

    app.run(host = settings.HOST, port = settings.PORT, debug = settings.DEBUG)

if __name__ == '__main__':
    main()